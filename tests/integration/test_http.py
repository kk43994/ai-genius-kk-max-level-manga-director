"""Real HTTP adapter tests with synthetic principals; no provider or customer data."""
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
import http.client
import io
import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import (APIError, Config, ConfigurationError, CustomerHTTPServer,
                         ROOT, Response, Router, Services, create_app)


class FixtureSessions:
    """Test-only identities. Never exported from the app or its run scripts."""
    def resolve_request(self, ctx):
        value = ctx.cookies.get("fixtureSession")
        if value in {"alpha", "beta"}:
            return {"tenantId": "tenant-" + value, "siteSessionId": "session-" + value}
        return None

    def verify_csrf(self, ctx, token):
        return token == "csrf-" + ctx.siteSessionId.removeprefix("session-")

    def readiness(self):
        return {"ready": True}


class FixtureSpaceProvider:
    """Only supplies synthetic adapter contracts, never official wire responses."""
    def __init__(self):
        self.scopes = []
        self.explicit_zero = False

    def get_account(self, ctx, account_id):
        if account_id != "pa-" + ctx.tenantId.removeprefix("tenant-"):
            raise APIError(404, "NOT_FOUND", "合成账号不存在")
        return {"id": account_id, "provider": "libtv", "tenantId": ctx.tenantId,
                "identity": {"issuer": "https://mcp.liblib.tv/", "subject": "subject-" + account_id,
                             "verified": True, "displayName": "合成身份"},
                "authorization": {"state": "connected"}, "removedAt": None}

    def account_client_for(self, ctx, owner):
        assert owner["spaceId"] is None
        return self.bound(ctx, owner, account_only=True)

    def client_for(self, ctx, owner):
        assert owner["spaceId"] in {"personal", "team"}
        return self.bound(ctx, owner, account_only=False)

    def bound(self, ctx, owner, account_only):
        account = self.get_account(ctx, owner["providerAccountId"])
        assert owner["tenantId"] == ctx.tenantId
        assert owner["providerSubject"] == account["identity"]["subject"]
        self.scopes.append(deepcopy(owner))
        provider = self
        class AccountReader:
            def identity(self):
                return deepcopy(account["identity"])
            def list_spaces(self):
                return {"items": [{"id": "personal", "kind": "personal", "name": "合成个人", "access": "available"},
                                  {"id": "team", "kind": "team", "name": "合成团队", "access": "available"}], "nextCursor": None}
        class SpaceReader(AccountReader):
            def quota(self, space_id):
                assert space_id == owner["spaceId"]
                if not provider.explicit_zero:
                    return {"planName": "合成套餐", "planCredits": 999}
                return {"providerAccountId": account["id"], "spaceId": space_id,
                        "state": "known", "remaining": 0, "unit": "credits", "buckets": [],
                        "source": "official", "observedAt": datetime.now(timezone.utc).isoformat()}
        return AccountReader() if account_only else SpaceReader()


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = ROOT.parent / "work/test-http"
        cls.parent.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.parent)
        self.addCleanup(self.temp.cleanup)
        self.temp_path = Path(self.temp.name)
        self.frontend = self.temp_path / "frontend"
        self.frontend.mkdir()
        (self.frontend / "style.css").write_text("body { color: black; }")
        self.servers = []
        self.addCleanup(self.stop_servers)
        self.app, self.origin = self.start()

    def stop_servers(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def start(self, base="/", api=None, fixtures=True, modules=(), providers=None):
        config = Config(self.temp_path / "data", port=0, public_base_path=base, api_base=api,
                        frontend_dir=self.frontend, max_request_bytes=512)
        services = Services(config)
        if fixtures:
            services.sessions = FixtureSessions()
        if providers is not None:
            services.providers = providers
        app = create_app(config, services=services, modules=modules)
        def write(ctx, params):
            self.mutations.append((ctx.tenantId, ctx.json))
            return {"tenantId": ctx.tenantId, "csrfVerified": ctx.csrfVerified}
        def owned(ctx, params):
            if params["id"] != ctx.tenantId:
                raise APIError(404, "NOT_FOUND", "项目不存在")
            return {"id": params["id"], "owner": ctx.tenantId}
        def crash(ctx, params):
            raise RuntimeError("secret-fixture-token must-never-be-returned")
        app.router.add("POST", "/api/v1/fixture-write", write)
        app.router.add("GET", "/api/v1/fixture-owned/{id}", owned)
        app.router.add("GET", "/api/v1/fixture-crash", crash)
        app.router.add("GET", "/api/v1/fixture-download", lambda ctx, p: Response(
            body=b"synthetic-data", headers={"Content-Type": "application/octet-stream",
                                           "Content-Disposition": 'attachment; filename="fixture.bin"'}))
        self.mutations = []
        server = CustomerHTTPServer(app)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return app, config.public_origin

    def request(self, path, method="GET", body=None, headers=None, origin=None, identity=None, csrf=True):
        origin = origin or self.origin
        port = int(origin.rsplit(":", 1)[1])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        headers = dict(headers or {})
        if identity:
            headers["Cookie"] = "fixtureSession=" + identity
            if method not in {"GET", "HEAD"}:
                headers.setdefault("Origin", origin)
                if csrf:
                    headers.setdefault("X-CSRF-Token", "csrf-" + identity)
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        raw = response.read()
        result = (response.status, dict(response.getheaders()), raw)
        conn.close()
        return result

    def json_request(self, path, **kwargs):
        status, headers, raw = self.request(path, **kwargs)
        return status, headers, json.loads(raw)

    def test_liveness_does_not_claim_customer_readiness(self):
        status, headers, body = self.json_request("/api/v1/health")
        self.assertEqual(status, 200)
        self.assertFalse(body["data"]["customerReady"])
        self.assertEqual(body["data"]["policy"], {"allowPaidSubmission": False, "videoGeneration": False})
        self.assertEqual(body["meta"]["requestId"], headers["X-Request-Id"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_missing_services_and_official_gates_are_not_ready(self):
        status, _, body = self.json_request("/api/v1/ready")
        self.assertEqual(status, 503)
        self.assertFalse(body["data"]["ready"])
        self.assertFalse(any(body["data"]["acceptance"].values()))
        self.assertEqual(body["data"]["checks"]["providers"]["reason"], "module_not_integrated")

    def test_missing_session_is_explicitly_not_implemented(self):
        status, _, body = self.json_request("/api/v1/session")
        self.assertEqual((status, body["error"]["code"]), (501, "NOT_IMPLEMENTED"))

    def test_private_routes_require_server_session(self):
        for path in ("/api/v1/projects", "/api/v1/fixture-download"):
            status, _, body = self.json_request(path, headers={"X-Tenant-Id": "tenant-alpha"})
            self.assertEqual((status, body["error"]["code"]), (401, "SESSION_REQUIRED"))

    def test_context_uses_session_not_client_tenant_header(self):
        status, _, body = self.json_request("/api/v1/fixture-owned/tenant-alpha?tenantId=tenant-beta",
                                          identity="alpha", headers={"X-Tenant-Id": "tenant-beta"})
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["owner"], "tenant-alpha")
        status, _, _ = self.json_request("/api/v1/fixture-owned/tenant-alpha", identity="beta")
        self.assertEqual(status, 404)

    def test_valid_csrf_and_origin_reach_handler(self):
        status, _, body = self.json_request("/api/v1/fixture-write", method="POST", identity="alpha", body={})
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["csrfVerified"])
        self.assertEqual(self.mutations, [("tenant-alpha", {})])

    def test_invalid_origin_and_csrf_cannot_mutate(self):
        cases = [({"Origin": "https://attacker.example"}, "ORIGIN_FAILED"),
                 ({"Origin": "null"}, "ORIGIN_FAILED"),
                 ({"X-CSRF-Token": "csrf-beta"}, "CSRF_FAILED"),
                 ({"X-CSRF-Token": ""}, "CSRF_FAILED")]
        for headers, code in cases:
            status, _, body = self.json_request("/api/v1/fixture-write", method="POST", identity="alpha",
                                               headers=headers, body={})
            self.assertEqual((status, body["error"]["code"]), (403, code))
        self.assertEqual(self.mutations, [])

    def test_body_cannot_select_tenant(self):
        status, _, body = self.json_request("/api/v1/fixture-write", method="POST", identity="alpha",
                                           body={"tenantId": "tenant-beta"})
        self.assertEqual((status, body["error"]["code"]), (422, "VALIDATION_FAILED"))
        self.assertFalse(self.mutations)

    def test_paid_submit_is_blocked_before_business_handler(self):
        route = next(r for r in self.app.router.routes if r.pattern == "/api/v1/tasks/{id}/submit")
        self.app.router.routes.remove(route)
        self.app.router.add("POST", "/api/v1/tasks/{id}/submit", lambda ctx, p: self.fail("must not submit"))
        status, _, body = self.json_request("/api/v1/tasks/synthetic-task/submit", method="POST", identity="alpha", body={})
        self.assertEqual((status, body["error"]["code"]), (403, "PAID_SUBMISSION_DISABLED"))

    def test_video_prepare_is_blocked_and_image_prepare_requires_idempotency(self):
        status, _, body = self.json_request("/api/v1/tasks/prepare", method="POST", identity="alpha", body={"recipe": "video"})
        self.assertEqual((status, body["error"]["code"]), (403, "VIDEO_GENERATION_DISABLED"))
        status, _, body = self.json_request("/api/v1/tasks/prepare", method="POST", identity="alpha", body={"recipe": "mj_style"})
        self.assertEqual((status, body["error"]["code"]), (422, "IDEMPOTENCY_KEY_REQUIRED"))
        status, _, body = self.json_request("/api/v1/tasks/prepare", method="POST", identity="alpha", body={},
                                           headers={"Idempotency-Key": "synthetic-1"})
        self.assertEqual((status, body["error"]["code"]), (501, "NOT_IMPLEMENTED"))

    def test_invalid_json_never_reaches_handler(self):
        for payload in (b'{', b'[]', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":"\xff"}'):
            status, _, body = self.json_request("/api/v1/fixture-write", method="POST", body=payload, identity="alpha",
                                               headers={"Content-Type": "application/json"})
            self.assertEqual((status, body["error"]["code"]), (400, "INVALID_JSON"))
        self.assertFalse(self.mutations)

    def test_size_and_media_type_limits(self):
        status, _, body = self.json_request("/api/v1/fixture-write", method="POST", identity="alpha", body=b"{}")
        self.assertEqual((status, body["error"]["code"]), (415, "UNSUPPORTED_MEDIA_TYPE"))
        status, _, body = self.json_request("/api/v1/fixture-write", method="POST", identity="alpha", body={"large": "x" * 600})
        self.assertEqual((status, body["error"]["code"]), (413, "REQUEST_TOO_LARGE"))

    def test_duplicate_sensitive_headers_rejected(self):
        port = int(self.origin.rsplit(":", 1)[1])
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.putrequest("POST", "/api/v1/fixture-write")
        conn.putheader("Content-Length", "0")
        conn.putheader("Content-Length", "2")
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read())["error"]["code"], "INVALID_REQUEST")
        conn.close()

    def test_ambiguous_query_and_untrusted_host_rejected(self):
        status, _, _ = self.json_request("/api/v1/oauth/libtv/callback?state=a&state=b")
        self.assertEqual(status, 400)
        status, _, body = self.json_request("/api/v1/health", headers={"Host": "attacker.example"})
        self.assertEqual((status, body["error"]["code"]), (400, "INVALID_HOST"))

    def test_unknown_route_method_and_legacy_are_explicit(self):
        for path, method, expected in (("/api/v1/missing", "GET", 404),
                                       ("/api/v1/health", "POST", 405),
                                       ("/api/v1/health", "OPTIONS", 405),
                                       ("/api/execution", "GET", 410)):
            status, headers, _ = self.request(path, method=method)
            self.assertEqual(status, expected)
            self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_oauth_codes_and_internal_errors_are_not_reflected_or_logged(self):
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            status, _, body = self.json_request("/api/v1/oauth/libtv/callback?code=synthetic-secret&state=synthetic-state")
        self.assertEqual(status, 501)
        self.assertNotIn("synthetic-secret", json.dumps(body) + captured.getvalue())
        with self.assertLogs("asset_lab.http", level="ERROR") as logs:
            status, _, raw = self.request("/api/v1/fixture-crash", identity="alpha")
        self.assertEqual(status, 500)
        self.assertNotIn("secret-fixture-token", raw.decode() + "".join(logs.output))

    def test_binary_and_head_have_correct_headers(self):
        status, headers, raw = self.request("/api/v1/fixture-download", identity="alpha")
        self.assertEqual((status, raw), (200, b"synthetic-data"))
        self.assertEqual(int(headers["Content-Length"]), len(raw))
        status, headers, raw = self.request("/api/v1/health", method="HEAD")
        self.assertEqual((status, raw), (200, b""))
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_blank_shell_exposes_no_existing_project_or_account(self):
        status, _, raw = self.request("/")
        self.assertEqual(status, 200)
        text = raw.decode()
        self.assertIn("暂无项目与已连接账号", text)
        self.assertIn("尚未就绪", text)
        self.assertNotIn("manifest.json", text)
        self.assertIn('href="/api/v1/ready"', text)
        self.assertNotIn("<script", text)

    def test_static_traversal_symlinks_and_private_paths_are_not_served(self):
        (self.temp_path / "private.html").write_text("private synthetic content")
        (self.frontend / "escape.html").symlink_to(self.temp_path / "private.html")
        for path in ("/../README.md", "/%2e%2e/backend/app.py", "/escape.html", "/backend/app.py",
                     "/.env", "/dashixiong-image-test/manifest.json"):
            status, _, raw = self.request(path)
            self.assertIn(status, {400, 404})
            self.assertNotIn(b"private synthetic content", raw)

    def test_subpath_has_isolated_resources_api_and_config(self):
        app, origin = self.start("/asset-lab/")
        self.assertEqual(self.request("/", origin=origin)[0], 404)
        self.assertEqual(self.request("/api/v1/health", origin=origin)[0], 404)
        self.assertEqual(self.request("/asset-lab/api/v1/health", origin=origin)[0], 200)
        status, headers, _ = self.request("/asset-lab", origin=origin)
        self.assertEqual((status, headers["Location"]), (308, "/asset-lab/"))
        status, _, raw = self.request("/asset-lab/", origin=origin)
        self.assertEqual(status, 200)
        self.assertIn(b'href="/asset-lab/api/v1/ready"', raw)
        self.assertEqual(self.request("/asset-lab/style.css", origin=origin)[0], 200)
        status, _, config = self.json_request("/asset-lab/app-config.json", origin=origin)
        self.assertEqual(config["apiBase"], "/asset-lab/api/v1")
        status, _, raw = self.request("/asset-lab/_app/config.js", origin=origin)
        self.assertIn(b"export const config", raw)
        status, headers, _ = self.request("/asset-lab/dashixiong-scene-studio/asset-lab.html", origin=origin)
        self.assertEqual((status, headers["Location"]), (308, "/asset-lab/asset-lab.html"))

    def test_explicit_api_base_and_customer_html_configuration(self):
        (self.frontend / "api-client.js").write_text("// fixture customer API client")
        (self.frontend / "asset-lab.html").write_text('<html><head></head><body>fixture customer shell</body></html>')
        app, origin = self.start("/asset-lab/", "/customer-api/v1")
        self.assertEqual(self.request("/customer-api/v1/health", origin=origin)[0], 200)
        self.assertEqual(self.request("/asset-lab/api/v1/health", origin=origin)[0], 410)
        status, _, raw = self.request("/asset-lab/", origin=origin)
        self.assertEqual(status, 200)
        self.assertIn(b'id="asset-lab-config"', raw)
        self.assertIn(b'"apiBase": "/customer-api/v1"', raw)

    def test_readiness_does_not_echo_provider_response(self):
        self.app.services.providers = types.SimpleNamespace(readiness=lambda: {"ready": False, "reason": "token=secret-url"})
        _, _, body = self.json_request("/api/v1/ready")
        self.assertEqual(body["data"]["checks"]["providers"]["reason"], "service_not_ready")
        self.assertNotIn("secret-url", json.dumps(body))

    def test_framework_neutral_response_does_not_double_wrap_envelope(self):
        self.app.router.add("GET", "/api/v1/foreign-response", lambda c, p: types.SimpleNamespace(
            status=200, body={"data": {"value": 1}, "meta": {"requestId": "module-id"}}, headers={}), public=True)
        status, headers, body = self.json_request("/api/v1/foreign-response")
        self.assertEqual((status, body["data"]), (200, {"value": 1}))
        self.assertEqual(body["meta"]["requestId"], headers["X-Request-Id"])

    def test_assembled_spaces_without_provider_returns_explicit_unavailable(self):
        app, origin = self.start(modules=(("spaces", "backend.spaces"),))
        status, _, body = self.json_request("/api/v1/provider-accounts/pa-alpha/spaces", identity="alpha", origin=origin)
        self.assertEqual((status, body["error"]["code"]), (503, "PROVIDER_CAPABILITY_UNAVAILABLE"))
        self.assertEqual(app.modules["spaces"], "loaded")

    def test_real_space_routes_on_subpath_use_account_scope_before_selection(self):
        provider = FixtureSpaceProvider()
        app, origin = self.start("/asset-lab/", modules=(("spaces", "backend.spaces"),), providers=provider)
        status, _, body = self.json_request("/asset-lab/api/v1/provider-accounts/pa-alpha/spaces", identity="alpha", origin=origin)
        self.assertEqual(status, 200)
        self.assertEqual([v["kind"] for v in body["data"]["items"]], ["personal", "team"])
        self.assertTrue(provider.scopes)
        self.assertTrue(all(o["spaceId"] is None for o in provider.scopes))
        status, _, body = self.json_request("/asset-lab/api/v1/provider-accounts/pa-alpha/spaces", identity="beta", origin=origin)
        self.assertEqual((status, body["error"]["code"]), (404, "NOT_FOUND"))

    def test_real_quota_routes_keep_unknown_and_explicit_zero_distinct(self):
        provider = FixtureSpaceProvider()
        app, origin = self.start(modules=(("spaces", "backend.spaces"),), providers=provider)
        path = "/api/v1/provider-accounts/pa-alpha/spaces/team/quota"
        status, _, body = self.json_request(path, identity="alpha", origin=origin)
        self.assertEqual((status, body["data"]["state"], body["data"]["remaining"]), (200, "unknown", None))
        provider.explicit_zero = True
        status, _, body = self.json_request(path, identity="alpha", origin=origin)
        self.assertEqual((status, body["data"]["state"], body["data"]["remaining"]), (200, "known", 0))
        self.assertTrue(all(o["tenantId"] == "tenant-alpha" and o["providerAccountId"] == "pa-alpha" for o in provider.scopes))
        self.assertTrue(any(o["spaceId"] == "team" for o in provider.scopes))

    def test_space_selection_without_storage_does_not_fake_persistence(self):
        provider = FixtureSpaceProvider()
        app, origin = self.start(modules=(("spaces", "backend.spaces"),), providers=provider)
        status, _, body = self.json_request("/api/v1/selection", method="PUT", identity="alpha", origin=origin,
                                           body={"providerAccountId": "pa-alpha", "spaceId": "personal", "expectedRevision": 0})
        self.assertEqual((status, body["error"]["code"]), (503, "PROVIDER_CAPABILITY_UNAVAILABLE"))


class ConfigurationTests(unittest.TestCase):
    def test_reserved_ports_and_release_data_are_rejected(self):
        for kwargs in ({"port": 8768}, {"port": 8870}, {"allowPaidSubmission": True}, {"videoGeneration": True},
                       {"public_origin": "http://example.com"}, {"public_base_path": "/../bad"},
                       {"api_base": "https://other.example/api"}):
            with self.assertRaises(ConfigurationError):
                Config(ROOT.parent / "work/test-data", **kwargs)
        for path in (ROOT / "data", Path("relative-data")):
            with self.assertRaises(ConfigurationError):
                Config(path)

    def test_duplicate_route_is_a_startup_error(self):
        router = Router()
        router.add("GET", "/api/v1/things/{id}", lambda ctx, p: {})
        with self.assertRaises(ValueError):
            router.add("GET", "/api/v1/things/{other}", lambda ctx, p: {})

    def test_missing_optional_module_differs_from_broken_dependency(self):
        config = Config(ROOT.parent / "work/test-data")
        with patch("backend.app.importlib.import_module", side_effect=ModuleNotFoundError(name="backend.absent")):
            app = create_app(config, modules=(("absent", "backend.absent"),))
            self.assertEqual(app.modules["absent"], "missing")
        with patch("backend.app.importlib.import_module", side_effect=ModuleNotFoundError(name="missing_dependency")):
            with self.assertRaises(ConfigurationError):
                create_app(config, modules=(("broken", "backend.broken"),))

    def test_module_factory_and_route_registration(self):
        config = Config(ROOT.parent / "work/test-data")
        fixture = types.SimpleNamespace(
            create_service=lambda services: {"marker": "fixture"},
            register_routes=lambda router, services: router.add("GET", "/api/v1/fixture-module", lambda c, p: services.fixture, public=True))
        with patch("backend.app.importlib.import_module", return_value=fixture):
            app = create_app(config, modules=(("fixture", "backend.fixture"),))
        self.assertEqual(app.services.fixture["marker"], "fixture")
        self.assertTrue(app.router.match("GET", "/api/v1/fixture-module")[0].public)


if __name__ == "__main__":
    unittest.main()
