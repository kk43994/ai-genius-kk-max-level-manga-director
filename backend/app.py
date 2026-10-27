"""Customer composition root; never imports legacy engines or local CLI accounts."""
from __future__ import annotations

import argparse
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
VERSION = "0.1.0-integration.1"
API_PREFIX = "/api/v1"  # Internal contract paths; public mounting is configurable.
MODULES = tuple((name, f"backend.{name}") for name in (
    "storage", "sessions", "providers", "auth", "spaces", "tasks", "workflow", "releases"))
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

    def __post_init__(self):
        supplied = Path(self.data_dir)
        if not supplied.is_absolute():
            raise ConfigurationError("DATA_DIR must be absolute and outside the release")
        resolved = supplied.resolve()
        if resolved == ROOT or resolved.is_relative_to(ROOT):
            raise ConfigurationError("DATA_DIR must be outside the release directory")
        if resolved.exists() and not resolved.is_dir():
            raise ConfigurationError("DATA_DIR must be a directory")
        if self.port in {8768, 8870}:
            raise ConfigurationError("Ports 8768 and 8870 are reserved; use an independent port")
        if not 0 <= self.port <= 65535:
            raise ConfigurationError("Invalid port")
        if self.allowPaidSubmission or self.videoGeneration:
            raise ConfigurationError("Paid submission and final video cannot be enabled in this development release")
        if self.max_request_bytes < 1 or self.request_timeout_seconds < 1:
            raise ConfigurationError("Request limits must be positive")
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
        object.__setattr__(self, "public_base_path", base)
        object.__setattr__(self, "api_base", api)
        object.__setattr__(self, "data_dir", resolved)
        object.__setattr__(self, "frontend_dir", Path(self.frontend_dir).resolve())

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

    def browser_config(self):
        return {"publicBasePath": self.public_base_path, "apiBase": self.api_base,
                "apiVersion": 1, "mode": "customer-development"}


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
        imported = []
        for name, module_name in modules:
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                if exc.name != module_name:
                    raise ConfigurationError(f"Dependency missing in {module_name}") from exc
                self.modules[name] = "missing"
                continue
            imported.append(module)
            factory = getattr(module, "create_service", None)
            if factory:
                self.services[name] = factory(self.services)
            self.modules[name] = "loaded"
        for module in imported:
            register = getattr(module, "register_routes", None)
            if register:
                register(self.router, self.services)
        self.router.add("GET", API_PREFIX + "/health", self.health, public=True)
        self.router.add("GET", API_PREFIX + "/ready", self.ready, public=True)
        for method, paths in PLACEHOLDERS.items():
            for path in paths:
                full_path = API_PREFIX + path
                if not any(r.method == method and route_shape(r.pattern) == route_shape(full_path)
                           for r in self.router.routes):
                    self.router.add(method, full_path, not_implemented, public=path in PUBLIC)

    def health(self, ctx, params):
        return Response(body={"status": "ok", "mode": "customer-development", "version": VERSION,
                              "apiVersion": 1, "customerReady": False, "modules": self.modules,
                              "policy": {"allowPaidSubmission": False, "videoGeneration": False}})

    def ready(self, ctx, params):
        checks = {}
        for name in REQUIRED:
            report = getattr(self.services.get(name), "readiness", None)
            try:
                result = report() if callable(report) else {}
                result = result if isinstance(result, dict) else {}
                reason = result.get("reason", "ready" if result.get("ready") is True else "readiness_not_reported")
                if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", reason):
                    reason = "service_not_ready"
                checks[name] = {"ready": result.get("ready") is True, "reason": reason}
            except Exception:
                checks[name] = {"ready": False, "reason": "readiness_check_failed"}
        ready = all(v["ready"] for v in checks.values())
        return Response(200 if ready else 503, {
            "ready": ready, "customerReady": False, "checks": checks,
            "acceptance": {"officialPublicCallback": False, "verifiedIdentitySpacesModels": False,
                           "realTwoAccountIsolation": False, "publicDeployment": False},
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
        if ctx.path not in {API_PREFIX + "/health", API_PREFIX + "/ready"}:
            self.authenticate(ctx)
        if not route.public and not ctx.siteSessionId:
            raise APIError(401, "SESSION_REQUIRED", "请重新打开页面以恢复本站会话")
        if ctx.method not in SAFE_METHODS:
            if ctx.origin != self.config.public_origin:
                raise APIError(403, "ORIGIN_FAILED", "请求来源不受信任，请在本站页面重试")
            if not ctx.siteSessionId:
                raise APIError(401, "SESSION_REQUIRED", "本站会话尚未建立")
            verify = getattr(self.services.sessions, "verify_csrf", None)
            token = ctx.headers.get("X-CSRF-Token", "")
            if not token or not callable(verify) or verify(ctx, token) is not True:
                raise APIError(403, "CSRF_FAILED", "页面校验已失效，请刷新后重试")
            ctx.csrfVerified = True
            if "tenantId" in ctx.json:
                raise APIError(422, "VALIDATION_FAILED", "客户归属由本站会话确定，不能从请求指定")
            if route.capability == "videoGeneration" or (ctx.path == API_PREFIX + "/tasks/prepare"
                    and "video" in str(ctx.json.get("recipe", "")).lower()):
                raise APIError(403, "VIDEO_GENERATION_DISABLED", "正式视频生成当前暂停")
            if route.capability == "paidSubmission" or re.fullmatch(r"/api/v1/tasks/[^/]+/submit", ctx.path):
                raise APIError(403, "PAID_SUBMISSION_DISABLED", "当前开发版本禁止提交收费生成")
            if ctx.method == "POST" and ctx.path == API_PREFIX + "/tasks/prepare":
                if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", ctx.headers.get("Idempotency-Key", "")):
                    raise APIError(422, "IDEMPOTENCY_KEY_REQUIRED", "创建任务需要有效的幂等标识")
        result = route.handler(ctx, params)
        if isinstance(result, Response):
            return result
        if isinstance(result, dict) and {"status", "body"}.issubset(result):
            return Response(result["status"], result["body"], result.get("headers", {}))
        if isinstance(result, dict):
            return Response(body=result)
        raise RuntimeError("Handler must return Response or JSON object")

    def static(self, ctx):
        if ctx.method not in {"GET", "HEAD"}:
            raise APIError(405, "METHOD_NOT_ALLOWED", "此资源只支持读取")
        base = self.config.public_base_path
        if base != "/" and ctx.path == base.rstrip("/"):
            return Response(308, headers={"Location": base})
        if not ctx.path.startswith(base):
            raise APIError(404, "NOT_FOUND", "资源不存在")
        path = ctx.path[len(base):]
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
                raw = (ROOT / "scripts/templates/integration-shell.html").read_text()
                raw = raw.replace("{{PUBLIC_BASE_PATH}}", base).replace("{{API_BASE}}", self.config.api_base)
                return Response(body=raw.encode(), headers={"Content-Type": "text/html; charset=utf-8"})
            path = "asset-lab.html"
        target = (self.config.frontend_dir / path).resolve()
        allowed = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff2"}
        if not target.is_relative_to(self.config.frontend_dir) or not target.is_file() or target.suffix.lower() not in allowed:
            raise APIError(404, "NOT_FOUND", "资源不存在")
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        raw = target.read_bytes()
        if target.suffix.lower() == ".html":
            # Explicit inert configuration, consumed by the integration bootstrap; no globals.
            config = json.dumps(self.config.browser_config()).replace("<", "\\u003c")
            tag = f'<script type="application/json" id="asset-lab-config">{config}</script>'
            raw = raw.replace(b"</head>", tag.encode() + b"</head>", 1)
        if target.suffix.lower() in {".html", ".js", ".css", ".svg"}:
            mime += "; charset=utf-8"
        hashed = bool(re.search(r"[.-][0-9a-f]{12,}\.", target.name))
        cache = "public, max-age=31536000, immutable" if hashed and target.suffix != ".html" else "no-cache"
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
    for name in ("Host", "Content-Length", "Content-Type", "Origin", "X-CSRF-Token", "Idempotency-Key", "Cookie"):
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
    daemon_threads, allow_reuse_address = True, False

    def __init__(self, app):
        self.app = app
        super().__init__((app.config.host, app.config.port), Handler)
        if app.config.port == 0 and app.config.public_origin.endswith(":0"):
            object.__setattr__(app.config, "public_origin", app.config.public_origin[:-2] + f":{self.server_port}")


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
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        for key in ("ASSET_LAB_ALLOW_PAID_SUBMISSION", "ASSET_LAB_VIDEO_GENERATION"):
            if os.environ.get(key, "false").lower() not in {"false", "0", "no", "off", ""}:
                raise ConfigurationError(f"{key} cannot be enabled in this development release")
        config = Config(Path(args.data_dir), args.host, args.port, args.public_origin,
                        args.public_base_path, args.api_base)
        app = create_app(config)
        if args.check_config:
            print(json.dumps({"configurationValid": True, "modules": app.modules,
                              "customerReady": False, **config.browser_config()}))
            return 0
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
