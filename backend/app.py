"""Customer composition root; never imports legacy engines or local CLI accounts."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib
import json
import logging
import mimetypes
import os
import re
import secrets
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
RELEASE_TREE = ROOT.parent if (ROOT.parent / "release.json").is_file() else ROOT
VERSION = "0.1.0-preview.1"
API_PREFIX = "/api/v1"  # Internal contract paths; public mounting is configurable.
MODULES = tuple((name, f"backend.{name}") for name in (
    "storage", "sessions", "providers", "auth", "spaces", "workflow", "tasks", "releases"))
REQUIRED = ("storage", "sessions", "providers", "spaces", "tasks", "workflow", "releases")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOG = logging.getLogger("asset_lab.http")


class ConfigurationError(ValueError):
    pass


class APIError(Exception):
    def __init__(self, status, code, message, *, retryable=False, details=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.details = retryable, details or {}


def normalize_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise ConfigurationError("PUBLIC_ORIGIN must be one HTTP(S) origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("Invalid public origin port") from exc
    host = parsed.hostname.lower()
    if parsed.scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigurationError("A non-loopback public origin must use HTTPS")
    if ":" in host:
        host = f"[{host}]"
    suffix = f":{port}" if port is not None and port != {"http": 80, "https": 443}[parsed.scheme] else ""
    return f"{parsed.scheme}://{host}{suffix}"


def normalize_path(value, trailing=False):
    if (not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9/_-]*", value)
            or "//" in value):
        raise ConfigurationError("Public paths must be absolute same-origin paths without query or traversal")
    result = value.rstrip("/")
    return (result + "/") if trailing else (result or "/")


@dataclass(frozen=True)
class Config:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8890
    public_origin: str | None = None
    public_base_path: str = "/"
    api_base: str | None = None
    max_request_bytes: int = 12 * 1024 * 1024
    request_timeout_seconds: int = 15
    frontend_dir: Path = ROOT / "frontend"
    allowPaidSubmission: bool = False
    videoGeneration: bool = False
    secret_key_file: Path | None = None
    release_root: Path | None = None
    running_manifest: Path | None = None
    local_client: bool = False

    def __post_init__(self):
        supplied = Path(self.data_dir)
        if not supplied.is_absolute():
            raise ConfigurationError("DATA_DIR must be absolute and outside the release")
        resolved = supplied.resolve()
        if resolved == RELEASE_TREE or resolved.is_relative_to(RELEASE_TREE) or RELEASE_TREE.is_relative_to(resolved):
            raise ConfigurationError("DATA_DIR must be outside the release directory")
        if any(path.is_symlink() for path in (supplied, *supplied.parents)):
            raise ConfigurationError("DATA_DIR must not pass through symlinks")
        if resolved.exists() and not resolved.is_dir():
            raise ConfigurationError("DATA_DIR must be a directory")
        if self.port in {8768, 8870}:
            raise ConfigurationError("Ports 8768 and 8870 are reserved; use an independent port")
        if not 0 <= self.port <= 65535:
            raise ConfigurationError("Invalid port")
        if self.videoGeneration or (self.allowPaidSubmission and (not self.local_client or self.host != "127.0.0.1")):
            raise ConfigurationError("Image submission requires an explicitly enabled loopback local client; video remains disabled")
        if self.max_request_bytes < 1 or self.request_timeout_seconds < 1:
            raise ConfigurationError("Request limits must be positive")
        if self.secret_key_file is not None:
            key_path = Path(self.secret_key_file)
            if not key_path.is_absolute():
                raise ConfigurationError("SECRET_KEY_FILE must be an absolute path")
            if key_path.resolve().is_relative_to(RELEASE_TREE) or key_path.resolve().is_relative_to(resolved):
                raise ConfigurationError("SECRET_KEY_FILE must be outside release and data directories")
            object.__setattr__(self, "secret_key_file", key_path)
        origin = self.public_origin
        if origin is None:
            if self.host not in {"localhost", "127.0.0.1"}:
                raise ConfigurationError("Set PUBLIC_ORIGIN when listening beyond loopback")
            origin = f"http://{self.host}:{self.port}"
        base = normalize_path(self.public_base_path, trailing=True)
        api = normalize_path(self.api_base or base + "api/v1")
        if api == "/" or api == base.rstrip("/"):
            raise ConfigurationError("API_BASE must not replace the frontend mount")
        object.__setattr__(self, "public_origin", normalize_origin(origin))
        if self.local_client and (self.host != "127.0.0.1" or
                urlsplit(self.public_origin).scheme != "http" or
                urlsplit(self.public_origin).hostname != "127.0.0.1" or
                urlsplit(self.public_origin).port != self.port or self.port == 0):
            raise ConfigurationError("Local authorization requires a fixed 127.0.0.1 listener and origin")
        object.__setattr__(self, "public_base_path", base)
        object.__setattr__(self, "api_base", api)
        object.__setattr__(self, "data_dir", resolved)
        object.__setattr__(self, "frontend_dir", Path(self.frontend_dir).resolve())
        if (self.release_root is None) != (self.running_manifest is None):
            raise ConfigurationError("RELEASE_ROOT and RUNNING_MANIFEST must be configured together")
        if self.release_root is not None:
            object.__setattr__(self, "release_root", Path(self.release_root).resolve())
            object.__setattr__(self, "running_manifest", Path(self.running_manifest).resolve())

    @property
    def dataDir(self):
        return self.data_dir

    @property
    def publicOrigin(self):
        return self.public_origin

    @property
    def publicBasePath(self):
        return self.public_base_path

    @property
    def apiBase(self):
        return self.api_base

    @property
    def session_cookie_path(self):
        # An explicitly separated same-origin API still needs the site's cookie.
        # Names remain isolated per mount/instance; never broaden Domain.
        frontend = self.public_base_path.strip("/").split("/") if self.public_base_path != "/" else []
        api = self.api_base.strip("/").split("/")
        common = []
        for left, right in zip(frontend, api):
            if left != right:
                break
            common.append(left)
        return "/" + "/".join(common) + ("/" if common else "")

    def browser_config(self):
        return {"publicBasePath": self.public_base_path, "apiBase": self.api_base,
                "apiVersion": 1, "mode": "local-client" if self.local_client else "customer-development"}


class Headers(dict):
    def __init__(self, values=()):
        super().__init__((k.lower(), v) for k, v in dict(values).items())

    def __getitem__(self, key):
        return super().__getitem__(key.lower())

    def get(self, key, default=None):
        return super().get(key.lower(), default)

    def __contains__(self, key):
        return super().__contains__(key.lower())


@dataclass
class RequestContext:
    requestId: str
    method: str
    path: str
    headers: Headers = field(default_factory=Headers)
    query: dict = field(default_factory=dict)
    json: dict = field(default_factory=dict)
    tenantId: str | None = None
    siteSessionId: str | None = None
    csrfVerified: bool = False
    origin: str | None = None
    cookies: dict = field(default_factory=dict)
    session: object = None
    publicPath: str = ""


@dataclass
class Response:
    status: int = 200
    body: dict | list | bytes | None = None
    headers: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    expression: object
    handler: object
    public: bool = False
    capability: str | None = None


def route_shape(pattern):
    return re.sub(r"\{[^}]+\}", "{}", pattern)


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler, *, public=False, capability=None):
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported route method; HEAD inherits GET")
        if not pattern.startswith(API_PREFIX + "/") or "?" in pattern:
            raise ValueError("Module routes must use logical /api/v1/ paths")
        if any(r.method == method and route_shape(r.pattern) == route_shape(pattern) for r in self.routes):
            raise ValueError(f"Duplicate or ambiguous route: {method} {pattern}")
        pieces, names = [], set()
        for part in pattern.split("/"):
            if part.startswith("{") and part.endswith("}"):
                name = part[1:-1]
                if not name.isidentifier() or name in names:
                    raise ValueError("Invalid route parameter")
                pieces.append(f"(?P<{name}>[^/]+)")
                names.add(name)
            else:
                if "{" in part or "}" in part:
                    raise ValueError("Parameters must occupy a full path segment")
                pieces.append(re.escape(part))
        expression = re.compile("^" + "/".join(pieces) + "$")
        self.routes.append(Route(method, pattern, expression, handler, public, capability))
        self.routes.sort(key=lambda r: (r.pattern.count("{"), -len(r.pattern)))

    def match(self, method, path):
        effective = "GET" if method == "HEAD" else method
        found_path = False
        for route in self.routes:
            match = route.expression.fullmatch(path)
            if match:
                found_path = True
                if route.method == effective:
                    return route, match.groupdict()
        if found_path:
            raise APIError(405, "METHOD_NOT_ALLOWED", "此接口不支持该请求方法")
        raise APIError(404, "NOT_FOUND", "接口不存在")


@dataclass(frozen=True)
class UnavailableService:
    name: str
    available: bool = False

    def readiness(self):
        return {"ready": False, "reason": "module_not_integrated"}


class Services(MutableMapping):
    """Both services.tasks and services['tasks'] address the same binding."""
    def __init__(self, config):
        object.__setattr__(self, "_values", {k: UnavailableService(k) for k in REQUIRED})
        self.config = config
        self.clock = lambda: datetime.now(timezone.utc)

    def __getitem__(self, key):
        return self._values[key]

    def __setitem__(self, key, value):
        self._values[key] = value

    def __delitem__(self, key):
        del self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __getattr__(self, key):
        try:
            return self._values[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self._values[key] = value


class SessionHTTPAdapter:
    """Adapt module 3 without changing its standalone API or credential storage."""
    def __init__(self, service, config):
        self.service, self.config = service, config
        self.configure_origin()

    def __getattr__(self, name):
        return getattr(self.service, name)

    def configure_origin(self):
        self.service.public_origin = self.config.public_origin
        if self.service.secure:
            if self.config.public_base_path == "/":
                name = "__Host-asset_lab_session"
            else:
                digest = hashlib.sha256(self.config.public_base_path.encode()).hexdigest()[:10]
                name = "__Secure-asset_lab_session_" + digest
        else:
            # Cookies are not port-scoped; independent localhost previews need namespacing.
            digest = hashlib.sha256((self.config.public_origin + self.config.public_base_path).encode()).hexdigest()[:10]
            name = "asset_lab_session_" + digest
        self.service.cookie_name = name

    def resolve_request(self, ctx):
        token = self.service.token_from_cookie(ctx.headers.get("Cookie"))
        if token is None:
            return None
        # Bootstrap refreshes the persistent cookie's idle expiry; ordinary reads do not.
        return self.service.restore(token, request_id=ctx.requestId, touch=False).context

    def verify_csrf(self, ctx, token):
        self.service.verify_mutation(ctx, origin=ctx.origin, csrf_token=token)
        return True

    def response_cookie(self, response):
        name = next((k for k in response.headers if k.lower() == "set-cookie"), None)
        if name:
            cookie = SimpleCookie()
            cookie.load(response.headers[name])
            if self.service.cookie_name in cookie:
                cookie[self.service.cookie_name]["path"] = self.config.session_cookie_path
                response.headers[name] = cookie.output(header="").strip()
        return response

    def readiness(self):
        return {"ready": True, "reason": "persistent_session_wired"}


class ModuleRouter:
    def __init__(self, router, public_routes):
        self.router, self.public_routes = router, public_routes

    def add(self, method, pattern, handler, **kwargs):
        if (method.upper(), pattern) in self.public_routes:
            kwargs["public"] = True
        self.router.add(method, pattern, handler, **kwargs)


def not_implemented(ctx, params):
    raise APIError(501, "NOT_IMPLEMENTED", "此客户版模块尚未接入；操作未执行")


PLACEHOLDERS = {
    "GET": ("/session", "/provider-accounts", "/oauth/libtv/callback", "/authorization-attempts/{id}",
            "/provider-accounts/{id}/spaces", "/provider-accounts/{id}/spaces/{spaceId}/quota",
            "/projects", "/projects/{id}", "/projects/{id}/scripts/{scriptId}",
            "/projects/{id}/plan", "/projects/{id}/assets", "/projects/{id}/export",
            "/assets/{id}/content", "/assets/{id}/thumbnail", "/tasks", "/tasks/{id}",
            "/version", "/releases/latest"),
    "POST": ("/provider-accounts/authorize", "/provider-accounts/{id}/reauthorize", "/projects",
             "/projects/{id}/scripts", "/assets/{id}/reviews", "/tasks/prepare",
             "/tasks/{id}/submit", "/tasks/{id}/recover", "/tasks/{id}/cancel"),
    "PUT": ("/selection", "/projects/{id}/plan"),
    "PATCH": ("/projects/{id}",), "DELETE": ("/provider-accounts/{id}",),
}
PUBLIC = {"/session", "/oauth/libtv/callback", "/version", "/releases/latest"}


class Application:
    def __init__(self, config, *, services=None, modules=MODULES):
        self.config = config
        self.services = services if services is not None else Services(config)
        self.router, self.modules = Router(), {}
        self.domain_errors = ()
        imported = {}
        for name, module_name in modules:
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                if exc.name != module_name:
                    raise ConfigurationError(f"Dependency missing in {module_name}") from exc
                self.modules[name] = "missing"
                continue
            imported[name] = module
            self.modules[name] = "loaded"
        # Validate the release/schema contract before Store can create or migrate data.
        if config.running_manifest is not None:
            release_module = imported.get("releases")
            if release_module is None:
                raise ConfigurationError("A running manifest requires the release module")
            from .storage import SCHEMA_VERSION
            try:
                self.services.releases = release_module.ReleaseService(release_root=config.release_root,
                    running_manifest=config.running_manifest, origin=config.public_origin,
                    base_path=config.public_base_path)
                if self.services.releases.current()["dataSchemaVersion"] != SCHEMA_VERSION:
                    raise ConfigurationError("Running release manifest has an incompatible data schema")
            except release_module.ReleaseUnavailable:
                raise ConfigurationError("Running release manifest is invalid") from None
        for name, module in imported.items():
            factory = getattr(module, "create_service", None)
            if factory:
                self.services[name] = factory(self.services)
            self._wire_builtin(name, module, imported)
        for name, module in imported.items():
            binding = "providers" if name == "auth" else name
            if name != "providers" and isinstance(self.services.get(binding), UnavailableService):
                continue  # Retain the explicit 501 placeholder until configured.
            register = getattr(module, "register_routes", None)
            if register:
                register(ModuleRouter(self.router, getattr(module, "PUBLIC_ROUTES", ())), self.services)
        self.router.add("GET", API_PREFIX + "/health", self.health, public=True)
        self.router.add("GET", API_PREFIX + "/ready", self.ready, public=True)
        if config.local_client:
            self.router.add("GET", API_PREFIX + "/oauth/libtv/return", self.local_authorization_return, public=True)
            from .local_workspace import register_routes as register_local_workspace
            register_local_workspace(self)
        if not isinstance(self.services.storage, UnavailableService):
            from .integration_drafts import register_routes as register_drafts
            register_drafts(self.router, self.services)
            from .integration_sessions import register_routes as register_anonymous
            register_anonymous(self.router, self.services)
        for method, paths in PLACEHOLDERS.items():
            for path in paths:
                full_path = API_PREFIX + path
                if not any(r.method == method and route_shape(r.pattern) == route_shape(full_path)
                           for r in self.router.routes):
                    self.router.add(method, full_path, not_implemented, public=path in PUBLIC)
        from .storage import SCHEMA_VERSION
        if self.services.releases is not None and not isinstance(self.services.releases, UnavailableService):
            manifest = self.services.releases.current()
            self.build_info = {key: manifest[key] for key in ("schemaVersion", "product", "version", "buildId", "channel", "apiVersion", "dataSchemaVersion")}
        else:
            digest = hashlib.sha256()
            for folder in (ROOT / "frontend", ROOT / "backend", ROOT / "scripts"):
                for path in sorted(folder.rglob("*")):
                    if path.is_file() and not path.is_symlink() and path.suffix in {".py", ".js", ".mjs", ".html", ".css"} and "legacy" not in path.parts:
                        digest.update(path.relative_to(ROOT).as_posix().encode()); digest.update(path.read_bytes())
            self.build_info = {"schemaVersion": 1, "product": "asset-lab-customer", "version": VERSION,
                "buildId": "dev-" + digest.hexdigest()[:16], "channel": "preview", "apiVersion": 1,
                "dataSchemaVersion": SCHEMA_VERSION}

    def _wire_builtin(self, name, module, imported):
        # Keep explicit adapters in dependency order with optional module factories.
        config = self.config
        if name == "storage":
            storage_module = module
            self.domain_errors += (storage_module.StorageError,)
            if isinstance(self.services.storage, UnavailableService):
                if config.secret_key_file is None:
                    self.modules["storage"] = "unconfigured"
                else:
                    try:
                        self.services.storage = storage_module.Store.from_env(release_root=RELEASE_TREE, environ={
                            "ASSET_LAB_DATA_DIR": str(config.data_dir),
                            "ASSET_LAB_SECRET_KEY_FILE": str(config.secret_key_file),
                        })
                    except storage_module.StorageError as exc:
                        raise ConfigurationError(f"{exc.code}: {exc.message}") from None
            if not isinstance(self.services.storage, UnavailableService):
                self.services.accounts = storage_module.AccountRepository(self.services.storage)
                self.services.selections = storage_module.SelectionRepository(self.services.storage)
        if name == "sessions" and isinstance(self.services.sessions, UnavailableService):
            if isinstance(self.services.storage, UnavailableService):
                self.modules["sessions"] = "unconfigured"
            else:
                self.services.sessions = SessionHTTPAdapter(module.SessionService(
                    self.services.storage, public_origin=config.public_origin), config)
                if config.local_client:
                    self.services.sessions.features["providerAuthorization"] = True
                    self.services.sessions.features["imageGeneration"] = config.allowPaidSubmission
                if hasattr(module, "WorkspaceRecoveryService"):
                    self.services.workspace_recovery = module.WorkspaceRecoveryService(
                        self.services.storage, self.services.sessions)
        if name == "auth" and isinstance(self.services.providers, UnavailableService):
            if isinstance(self.services.storage, UnavailableService):
                self.modules[name] = "unconfigured"
            else:
                from .auth.storage_adapter import StorageAuthRepository
                from .auth.secrets import AesGcmSecretCodec
                from .providers.libtv_oauth import LibTVOAuth, OAuthConfig
                # This is a server-only secret subkey, never a browser CSRF token.
                key = hmac.digest(self.services.storage._csrf_key, b"asset-lab/libtv-aead/v1", "sha256")
                # Authorization stays gated below until official identity/callback verification.
                callback_base = config.api_base if config.api_base.endswith("/api/v1") else config.public_base_path + "api/v1"
                oauth = LibTVOAuth(OAuthConfig(
                    redirect_uri=config.public_origin + callback_base + "/oauth/libtv/callback",
                    return_paths=tuple(dict.fromkeys(("/", config.public_base_path))),
                    client_name="资产实验室 · 本地客户端" if config.local_client else "资产研究室 · 客户网页",
                    allow_loopback_development=config.public_origin.startswith("http:")))
                from .tasks.adapters import StoreTaskRepository
                from .integration_generation import make_adapter
                self.services.task_repository = StoreTaskRepository(self.services.storage,
                    selection_reader=self.services.selections._get)
                self.services.generation = make_adapter(self.services,self.services.task_repository,local_images=config.allowPaidSubmission)
                self.services.providers = module.ProviderService(
                    StorageAuthRepository(self.services.storage), AesGcmSecretCodec({"v1": key}, "v1"), oauth,
                    workspace_recovery=self.services.get("workspace_recovery"),operation_adapter=self.services.generation)
        if name == "spaces" and isinstance(self.services.spaces, UnavailableService):
            selections = self.services.get("selections")
            if selections is None and not isinstance(self.services.storage, UnavailableService):
                storage_module = imported.get("storage")
                selection_repository = getattr(storage_module, "SelectionRepository", None)
                if selection_repository is None:
                    raise ConfigurationError("Storage binding must export SelectionRepository")
                selections = selection_repository(self.services.storage)
                self.services.selections = selections
            self.services.spaces = module.SpaceService(
                providers=self.services.providers, selections=selections, clock=self.services.clock)
        if name == "workflow" and isinstance(self.services.workflow, UnavailableService):
            if not isinstance(self.services.storage, UnavailableService):
                self.services.workflow = module.WorkflowService(module.WorkflowRepository(self.services.storage),
                                                                 api_base=config.api_base)
                if isinstance(self.services.sessions, SessionHTTPAdapter):
                    self.services.sessions.features["persistentProjects"] = True
        if name == "tasks" and isinstance(self.services.tasks, UnavailableService):
            if (not isinstance(self.services.storage, UnavailableService)
                    and not isinstance(self.services.workflow, UnavailableService)):
                from .tasks.adapters import StoreTaskRepository, SelectionAdapter, SpaceAdapter
                from .workflow import WorkflowOutputStore
                repository = self.services.get("task_repository") or StoreTaskRepository(self.services.storage,
                    selection_reader=self.services.selections._get)
                key = hmac.digest(self.services.storage._csrf_key, b"asset-lab/task-confirmation/v1", "sha256")
                self.services.tasks = module.TaskService(repository=repository,
                    providers=self.services.providers, selections=SelectionAdapter(self.services.selections),
                    spaces=SpaceAdapter(self.services.spaces), inputs=self.services.workflow,
                    outputs=WorkflowOutputStore(self.services.workflow, repository),
                    policy=module.TaskPolicy(confirmation_key=key,allow_paid_submission=config.allowPaidSubmission), clock=self.services.clock)
                self.services.workflow.tasks = self.services.tasks
                from .analysis.service import AnalysisService
                from .analysis.provider import LibTVAnalysisProvider
                self.services.analysis = AnalysisService(self.services, LibTVAnalysisProvider(self.services),
                    enabled=config.local_client and config.allowPaidSubmission)
                from .analysis.asset_prompts import PromptService
                self.services.prompt_jobs = PromptService(self.services, LibTVAnalysisProvider(self.services), enabled=self.services.analysis.enabled)
                self.services.workflow.prompt_jobs = self.services.prompt_jobs
                self.services.workflow.analysis = self.services.analysis
                self.services.sessions.features['scriptAnalysis'] = self.services.analysis.enabled
                if hasattr(self.services.providers, "on_account_removed"):
                    self.services.providers.on_account_removed = self.services.tasks.block_account
        if name == "releases" and isinstance(self.services.releases, UnavailableService):
            self.services.releases = None  # Module responds with a deliberate 503 when unconfigured.

    def health(self, ctx, params):
        return Response(body={"status": "ok", "mode": "customer-development", "version": VERSION,
                              "apiVersion": 1, "customerReady": False, "modules": self.modules,
                              "policy": {"allowPaidSubmission": self.config.allowPaidSubmission, "videoGeneration": False}})

    def local_authorization_return(self, ctx, params):
        html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>LibTV 本地授权</title><body style="font-family:system-ui;padding:40px;line-height:1.8">'
                '<h1>请回到资产实验室查看连接结果</h1>'
                '<p>本机已收到官方返回。原工作台会自动核对账号状态，完成后关闭这个窗口。</p>'
                '<p>如果原窗口已经关闭，可以重新打开工作台。</p>'
                '<a href="' + self.config.public_base_path + '">打开资产实验室</a></body></html>')
        return Response(body=html.encode(), headers={"Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    def ready(self, ctx, params):
        checks = {}
        for name in REQUIRED:
            report = getattr(self.services.get(name), "readiness", None)
            try:
                result = report() if callable(report) else {}
                if name == "providers" and self.modules.get("auth") == "loaded" and not isinstance(self.services.providers, UnavailableService):
                    result = {"ready": self.config.local_client, "reason": "local_readonly_oauth_enabled" if self.config.local_client else "public_oauth_callback_unverified"}
                if name in {"spaces", "workflow", "tasks"} and not isinstance(self.services.get(name), UnavailableService):
                    result = {"ready": True, "reason": "module_wired"}
                if name == "releases" and self.services.releases is not None and not isinstance(self.services.releases, UnavailableService):
                    self.services.releases.current()
                    result = {"ready": True, "reason": "running_manifest_loaded"}
                result = result if isinstance(result, dict) else {}
                reason = result.get("reason", "ready" if result.get("ready") is True else "readiness_not_reported")
                if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason):
                    reason = "service_not_ready"
                checks[name] = {"ready": result.get("ready") is True, "reason": reason}
            except Exception:
                checks[name] = {"ready": False, "reason": "readiness_check_failed"}
        ready = all(v["ready"] for v in checks.values())
        from .integration_generation import release_gates
        return Response(200 if ready else 503, {
            "ready": ready, "customerReady": False, "checks": checks,
            "acceptance": {"officialPublicCallback": False, "verifiedIdentitySpacesModels": False,
                           "realTwoAccountIsolation": False, "publicDeployment": False},
            "ownerRecovery": {"serviceInstalled":self.services.get("workspace_recovery") is not None,
                "uiHooksConnected":True,"publicEnabled":False,"realUserBindingVerified":False},
            "officialReadEvidence": {"scope":"separate_isolated_local_instance", "readOnlyOAuthVerified":True,
                "stableIdentityVerified":True,"personalTeamSpacesVerified":True,"balanceState":"unknown",
                "credentialsImported":False,"evidence":"backend/auth/OFFICIAL_READ_EVIDENCE.md"},
            "generation": release_gates(self.services.get("generation")),
            "reason": "customer_acceptance_pending" if ready else "modules_not_ready"})

    def authenticate(self, ctx):
        resolve = getattr(self.services.sessions, "resolve_request", None)
        principal = resolve(ctx) if callable(resolve) else None
        if principal is None:
            return
        def get(name):
            return principal.get(name) if isinstance(principal, Mapping) else getattr(principal, name, None)
        tenant, session_id = get("tenantId"), get("siteSessionId")
        if not isinstance(tenant, str) or not tenant or not isinstance(session_id, str) or not session_id:
            raise RuntimeError("Session service returned an invalid principal")
        ctx.tenantId, ctx.siteSessionId, ctx.session = tenant, session_id, principal

    def dispatch(self, ctx):
        ctx.publicPath = ctx.path
        api = self.config.api_base
        if ctx.path == api or ctx.path.startswith(api + "/"):
            ctx.path = API_PREFIX + ctx.path[len(api):]
        else:
            if ctx.path.startswith(self.config.public_base_path + "api/"):
                raise APIError(410, "LEGACY_API_DISABLED", "旧工作台接口未在客户版启用")
            return self.static(ctx)
        route, params = self.router.match(ctx.method, ctx.path)
        anonymous_bootstrap = ctx.method == "POST" and ctx.path == API_PREFIX + "/session/anonymous"
        if not anonymous_bootstrap and ctx.path not in {API_PREFIX + "/health", API_PREFIX + "/ready"}:
            self.authenticate(ctx)
        if not route.public and not ctx.siteSessionId:
            raise APIError(401, "SESSION_REQUIRED", "请重新打开页面以恢复本站会话")
        if ctx.method not in SAFE_METHODS and not anonymous_bootstrap:
            if ctx.origin != self.config.public_origin:
                raise APIError(403, "ORIGIN_FAILED", "请求来源不受信任，请在本站页面重试")
            if not ctx.siteSessionId:
                raise APIError(401, "SESSION_REQUIRED", "本站会话尚未建立")
            verify = getattr(self.services.sessions, "verify_csrf", None)
            token = ctx.headers.get("X-CSRF-Token", "")
            if not token or not callable(verify) or verify(ctx, token) is not True:
                raise APIError(403, "CSRF_FAILED", "页面校验已失效，请刷新后重试")
            ctx.csrfVerified = True
            if isinstance(self.services.sessions, SessionHTTPAdapter):
                expected_session = ctx.headers.get("X-Asset-Lab-Session", "")
                if not expected_session or not hmac.compare_digest(expected_session, ctx.siteSessionId):
                    raise APIError(409, "WORKSPACE_CONTEXT_CHANGED", "工作区会话已改变；旧页面的写入未执行，请同步工作区")
            authorizing = ctx.path == API_PREFIX + "/provider-accounts/authorize" or re.fullmatch(r"/api/v1/provider-accounts/[^/]+/reauthorize", ctx.path)
            if authorizing:
                if not self.config.local_client:
                    raise APIError(503, "PROVIDER_UNCONFIGURED", "本站正式回调尚未通过验证，官方网页连接暂未开放")
                if ctx.json.get("intent", "connect") != "connect" or ctx.json.get("purpose", "provider_account") != "provider_account":
                    raise APIError(503, "PROVIDER_UNCONFIGURED", "本地版目前仅开放连接 LibTV 账号")
            if "tenantId" in ctx.json:
                raise APIError(422, "VALIDATION_FAILED", "客户归属由本站会话确定，不能从请求指定")
            if route.capability == "videoGeneration" or (ctx.path == API_PREFIX + "/tasks/prepare"
                    and "video" in str(ctx.json.get("recipe", "")).lower()):
                raise APIError(403, "VIDEO_GENERATION_DISABLED", "正式视频生成当前暂停")
            if not self.config.allowPaidSubmission and (route.capability == "paidSubmission" or re.fullmatch(r"/api/v1/tasks/[^/]+/submit", ctx.path)):
                raise APIError(403, "PAID_SUBMISSION_DISABLED", "当前开发版本禁止提交收费生成")
            if ctx.method == "POST" and ctx.path == API_PREFIX + "/tasks/prepare":
                if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", ctx.headers.get("Idempotency-Key", "")):
                    raise APIError(422, "IDEMPOTENCY_KEY_REQUIRED", "创建任务需要有效的幂等标识")
        from .integration_generation import request_scope
        with request_scope(ctx):
            result = route.handler(ctx, params)
        if isinstance(result, Response):
            response = result
        # Framework-neutral modules may define their own Response dataclass.
        elif all(hasattr(result, key) for key in ("status", "body", "headers")):
            response = Response(result.status, result.body, dict(result.headers))
        elif isinstance(result, dict) and {"status", "body"}.issubset(result):
            response = Response(result["status"], result["body"], result.get("headers", {}))
        elif isinstance(result, dict):
            response = Response(body=result)
        else:
            raise RuntimeError("Handler must return Response or JSON object")
        if isinstance(self.services.sessions, SessionHTTPAdapter):
            response = self.services.sessions.response_cookie(response)
        if ctx.path == API_PREFIX + "/oauth/libtv/callback":
            location = response.headers.get("Location", "")
            if self.config.local_client and response.status == 303:
                response.headers["Location"] = self.config.api_base + "/oauth/libtv/return"
            elif location == "/" or location.startswith("/?"):
                response.headers["Location"] = self.config.public_base_path + location[1:]
        return response

    def static(self, ctx):
        if ctx.method not in {"GET", "HEAD"}:
            raise APIError(405, "METHOD_NOT_ALLOWED", "此资源只支持读取")
        base = self.config.public_base_path
        if base != "/" and ctx.path == base.rstrip("/"):
            return Response(308, headers={"Location": base})
        if not ctx.path.startswith(base):
            raise APIError(404, "NOT_FOUND", "资源不存在")
        path = ctx.path[len(base):]
        static_root = self.config.frontend_dir
        immutable = False
        if path.startswith("releases/"):
            parts = path.split("/", 2)
            if (self.config.release_root is None or len(parts) != 3
                    or not re.fullmatch(r"[A-Za-z0-9._-]{1,150}", parts[1])):
                raise APIError(404, "NOT_FOUND", "发布资源不存在")
            release = self.config.release_root / "releases" / parts[1]
            if release.resolve().parent != self.config.release_root / "releases":
                raise APIError(404, "NOT_FOUND", "发布资源不存在")
            static_root, path, immutable = (release / "public").resolve(), parts[2], True
            if not path:
                path = "index.html"
        if path in {"app-config.json", "_app/config.js"}:
            config = json.dumps(self.config.browser_config(), ensure_ascii=False)
            raw = ("export const config = Object.freeze(" + config + "); export default config;\n"
                   if path.endswith(".js") else config).encode()
            mime = "text/javascript" if path.endswith(".js") else "application/json"
            return Response(body=raw, headers={"Content-Type": mime + "; charset=utf-8"})
        if path.startswith("dashixiong-scene-studio/"):
            # Preserve old bookmarked URLs, but canonical HTML lives directly at the mount.
            relative = path[len("dashixiong-scene-studio/"):]
            return Response(308, headers={"Location": base + relative})
        if path in {"", "index.html", "asset-lab.html"}:
            if not (self.config.frontend_dir / "api-client.js").is_file():
                raw = (ROOT / "scripts/templates/integration-shell.html").read_text(encoding="utf-8")
                raw = raw.replace("{{PUBLIC_BASE_PATH}}", base).replace("{{API_BASE}}", self.config.api_base)
                return Response(body=raw.encode(), headers={"Content-Type": "text/html; charset=utf-8"})
            path = "index.html" if (static_root / "index.html").is_file() else "asset-lab.html"
        if path.startswith("_app/") and not (static_root / path).is_file() and not immutable:
            static_root, path = ROOT / "scripts/browser", path[len("_app/"):]
        target = (static_root / path).resolve()
        allowed = {".html", ".js", ".mjs", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff2"}
        if not target.is_relative_to(static_root) or not target.is_file() or target.suffix.lower() not in allowed:
            raise APIError(404, "NOT_FOUND", "资源不存在")
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        raw = target.read_bytes()
        if target.suffix.lower() == ".html":
            from scripts.customer_entry import entry_html
            raw = entry_html(raw.decode(), self.config.browser_config(), self.build_info, add_base=True).encode()
        if target.suffix.lower() in {".html", ".js", ".mjs", ".css", ".svg"}:
            mime += "; charset=utf-8"
        hashed = bool(re.search(r"[.-][0-9a-f]{12,}\.", target.name))
        cache = "public, max-age=31536000, immutable" if (hashed or immutable) and target.suffix != ".html" else "no-cache"
        return Response(body=raw, headers={"Content-Type": mime, "Cache-Control": cache})


def decode_request(handler, request_id):
    if len(handler.path) > 8192:
        raise APIError(414, "URI_TOO_LONG", "请求地址过长")
    parsed = urlsplit(handler.path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise APIError(400, "INVALID_REQUEST", "请求地址无效")
    try:
        path = unquote(parsed.path, errors="strict")
        if (any(ord(c) < 32 for c in path) or "\\" in path or "//" in path
                or any(part in {".", ".."} for part in path.split("/"))):
            raise ValueError()
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100, errors="strict")
        query = dict(pairs)
        if len(query) != len(pairs):
            raise ValueError()
    except (UnicodeError, ValueError) as exc:
        raise APIError(400, "INVALID_REQUEST", "请求地址或参数无效") from exc
    for name in ("Host", "Content-Length", "Content-Type", "Origin", "X-CSRF-Token", "X-Asset-Lab-Session", "X-Asset-Lab-Action", "Idempotency-Key", "Cookie"):
        if len(handler.headers.get_all(name, [])) > 1:
            raise APIError(400, "INVALID_REQUEST", "请求头重复")
    headers = Headers(handler.headers.items())
    if headers.get("Transfer-Encoding"):
        raise APIError(400, "INVALID_REQUEST", "不支持此请求编码")
    expected_host = urlsplit(handler.server.app.config.public_origin).netloc.lower()
    if headers.get("Host", "").lower() != expected_host:
        raise APIError(400, "INVALID_HOST", "请求域名不受信任")
    size = headers.get("Content-Length", "0")
    if not re.fullmatch(r"\d{1,12}", size):
        raise APIError(400, "INVALID_REQUEST", "请求长度无效")
    length = int(size)
    if length > handler.server.app.config.max_request_bytes:
        raise APIError(413, "REQUEST_TOO_LARGE", "上传内容超出允许大小")
    if handler.command in SAFE_METHODS and length:
        raise APIError(400, "INVALID_REQUEST", "读取请求不能携带请求正文")
    body = {}
    if length:
        if headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise APIError(415, "UNSUPPORTED_MEDIA_TYPE", "此接口需要 JSON 请求")
        try:
            raw = handler.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            def invalid_constant(value):
                raise ValueError()
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
            if not isinstance(body, dict):
                raise ValueError()
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise APIError(400, "INVALID_JSON", "请求内容不是有效的 JSON 对象") from exc
    try:
        cookies = SimpleCookie()
        cookies.load(headers.get("Cookie", ""))
    except Exception as exc:
        raise APIError(400, "INVALID_REQUEST", "会话 Cookie 无效") from exc
    return RequestContext(request_id, handler.command, path, headers, query, body,
                          origin=headers.get("Origin"), cookies={k: v.value for k, v in cookies.items()})


def serialize_response(response, request_id):
    if not isinstance(response.status, int) or not 200 <= response.status <= 599:
        raise ValueError("Invalid response status")
    headers = dict(response.headers)
    for key, value in headers.items():
        if not re.fullmatch(r"[A-Za-z0-9-]+", key) or not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError("Invalid response header")
        if key.lower() == "location" and (not value.startswith("/") or value.startswith("//") or "\\" in value):
            raise ValueError("Redirects must remain on this site")
    if isinstance(response.body, bytes):
        return response.body, headers
    if response.status in {204, 304} or response.body is None:
        return b"", headers
    body, meta = response.body, {"requestId": request_id, "apiVersion": 1}
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        result = {"error": body["error"], "meta": meta}
    elif isinstance(body, dict) and "data" in body and set(body).issubset({"data", "meta"}):
        result = {"data": body["data"], "meta": meta}
    else:
        result = {"data": body, "meta": meta}
    headers["Content-Type"] = "application/json; charset=utf-8"
    return json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), headers


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version, protocol_version = "AssetLabCustomer", "", "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.app.config.request_timeout_seconds)

    def log_message(self, format, *args):
        # Raw request URLs can contain OAuth code/state and are never logged.
        pass

    def handle_request(self):
        request_id = "req_" + secrets.token_hex(12)
        self.close_connection = True
        try:
            response = self.server.app.dispatch(decode_request(self, request_id))
            raw, headers = serialize_response(response, request_id)
        except APIError as exc:
            response = Response(exc.status, {"error": {"code": exc.code, "message": exc.message,
                                "retryable": exc.retryable, "details": exc.details}})
            raw, headers = serialize_response(response, request_id)
        except self.server.app.domain_errors as exc:
            response = Response(exc.status, {"error": exc.public()})
            raw, headers = serialize_response(response, request_id)
        except Exception as exc:
            LOG.error("request_failed requestId=%s exceptionType=%s", request_id, type(exc).__name__)
            timed_out = isinstance(exc, (TimeoutError, ConnectionError))
            response = Response(408 if timed_out else 500, {"error": {
                "code": "REQUEST_TIMEOUT" if timed_out else "INTERNAL_ERROR",
                "message": "请求超时，请重试" if timed_out else "服务暂时无法完成请求",
                "retryable": timed_out, "details": {}}})
            raw, headers = serialize_response(response, request_id)
        try:
            self.send_response(response.status)
            fixed = {
                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
                "X-Request-Id": request_id, "Connection": "close",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
            }
            protected = {k.lower() for k in fixed} | {"content-length", "transfer-encoding"}
            for key in ("Referrer-Policy", "Content-Security-Policy"):
                # Callback modules deliberately use a stricter, non-rendering policy.
                if key in headers:
                    fixed[key] = headers[key]
            for key, value in headers.items():
                if key.lower() not in protected:
                    self.send_header(key, value)
            if not self.path.startswith(self.server.app.config.api_base) and "Cache-Control" in headers:
                fixed["Cache-Control"] = headers["Cache-Control"]
            for key, value in fixed.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_request


class CustomerHTTPServer(ThreadingHTTPServer):
    daemon_threads, allow_reuse_address = True, True

    def __init__(self, app):
        self.app = app
        super().__init__((app.config.host, app.config.port), Handler)
        if app.config.port == 0 and app.config.public_origin.endswith(":0"):
            object.__setattr__(app.config, "public_origin", app.config.public_origin[:-2] + f":{self.server_port}")
            if isinstance(app.services.sessions, SessionHTTPAdapter):
                app.services.sessions.configure_origin()


def create_app(config, *, services=None, modules=MODULES):
    return Application(config, services=services, modules=modules)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("ASSET_LAB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.environ.get("ASSET_LAB_PORT", "8890"))
    parser.add_argument("--data-dir", default=os.environ.get("ASSET_LAB_DATA_DIR", str(ROOT.parent / "work/customer-data")))
    parser.add_argument("--public-origin", default=os.environ.get("ASSET_LAB_PUBLIC_ORIGIN"))
    parser.add_argument("--public-base-path", default=os.environ.get("ASSET_LAB_PUBLIC_BASE_PATH", "/"))
    parser.add_argument("--api-base", default=os.environ.get("ASSET_LAB_API_BASE"))
    parser.add_argument("--secret-key-file", type=Path, default=os.environ.get("ASSET_LAB_SECRET_KEY_FILE"))
    parser.add_argument("--frontend-dir", type=Path, default=ROOT / "frontend")
    parser.add_argument("--release-root", type=Path, default=os.environ.get("ASSET_LAB_RELEASE_ROOT"))
    parser.add_argument("--running-manifest", type=Path, default=os.environ.get("ASSET_LAB_RUNNING_MANIFEST"))
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--local-client", action="store_true", help="Enable only account-read OAuth on a fixed loopback origin")
    args = parser.parse_args(argv)
    try:
        for key in ("ASSET_LAB_ALLOW_PAID_SUBMISSION", "ASSET_LAB_VIDEO_GENERATION"):
            if os.environ.get(key, "false").lower() not in {"false", "0", "no", "off", ""}:
                raise ConfigurationError(f"{key} cannot be enabled in this development release")
        config = Config(Path(args.data_dir), args.host, args.port, args.public_origin,
                        args.public_base_path, args.api_base, secret_key_file=args.secret_key_file,
                        frontend_dir=args.frontend_dir, release_root=args.release_root,
                        running_manifest=args.running_manifest, local_client=args.local_client)
        if args.check_config:
            print(json.dumps({"configurationSyntaxValid": True, "databaseInitialized": False,
                              "customerReady": False, **config.browser_config()}))
            return 0
        app = create_app(config)
        with CustomerHTTPServer(app) as server:
            print(f"Customer integration preview: {config.public_origin}{config.public_base_path}", flush=True)
            print("Paid generation disabled; readiness must be checked separately.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (ConfigurationError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    # Modules import Response/RequestContext from backend.app even when launched with -m.
    sys.modules.setdefault("backend.app", sys.modules[__name__])
    raise SystemExit(main())
