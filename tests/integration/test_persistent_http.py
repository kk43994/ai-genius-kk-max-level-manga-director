"""Public HTTP session/storage assembly with temporary data and fresh test keys."""
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import unittest

from backend.app import Config, CustomerHTTPServer, ROOT, create_app

MODULES = (("storage", "backend.storage"), ("sessions", "backend.sessions"), ("spaces", "backend.spaces"))


class PersistentHTTPTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT.parent / "work/test-persistent-http"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / "private-key"
        fd = os.open(self.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(base64.b64encode(secrets.token_bytes(32)))
        self.servers = []
        self.addCleanup(self.close_servers)
        self.app, self.server = self.start()

    def start(self, base="/", port=0, data_name="data", public_origin=None):
        config = Config(self.root / data_name, port=port, public_base_path=base,
                        public_origin=public_origin, secret_key_file=self.key)
        app = create_app(config, modules=MODULES)
        app.router.add("GET", "/api/v1/fixture-projects/{id}", lambda ctx, params: {
            "id": app.services.storage.get(ctx, "projects", params["id"])["id"]})
        server = CustomerHTTPServer(app)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return app, server

    def stop(self, server):
        item = next(x for x in self.servers if x[0] is server)
        server.shutdown()
        server.server_close()
        item[1].join(timeout=2)
        self.servers.remove(item)

    def close_servers(self):
        for server, thread in list(self.servers):
            self.stop(server)

    def request(self, path, *, app=None, server=None, method="GET", cookie=None, csrf=None, body=None, origin=None):
        app, server = app or self.app, server or self.server
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        headers = {"Host": app.config.public_origin.split("://", 1)[1]}
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if method != "GET":
            headers["Origin"] = origin or app.config.public_origin
        if body is not None:
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), json.loads(response.read())
        conn.close()
        return result

    def bootstrap(self, **kwargs):
        app = kwargs.get("app", self.app)
        status, headers, body = self.request(app.config.api_base + "/session", **kwargs)
        self.assertEqual(status, 200)
        self.assertEqual(body["meta"]["requestId"], headers["X-Request-Id"])
        return headers["Set-Cookie"].split(";", 1)[0], body["data"], headers

    def test_session_bootstrap_and_refresh_restore_persistent_tenant(self):
        cookie, data, headers = self.bootstrap()
        _, restored, _ = self.bootstrap(cookie=cookie)
        self.assertEqual(data["tenant"], restored["tenant"])
        self.assertEqual(data["session"]["id"], restored["session"]["id"])
        self.assertEqual(data["csrfToken"], restored["csrfToken"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", headers["Set-Cookie"])
        self.assertFalse(any(data["features"].values()))

    def test_restarted_http_service_keeps_session_and_project(self):
        cookie, data, _ = self.bootstrap()
        context = self.app.services.sessions.bootstrap(cookie).context
        project = self.app.services.storage.create(context, "projects", {"name": "合成持久化项目"})
        port = self.server.server_port
        self.stop(self.server)
        self.app, self.server = self.start(port=port)
        _, restored, _ = self.bootstrap(cookie=cookie)
        self.assertEqual(restored["tenant"], data["tenant"])
        status, _, body = self.request("/api/v1/fixture-projects/" + project["id"], cookie=cookie)
        self.assertEqual((status, body["data"]["id"]), (200, project["id"]))

    def test_actual_tenants_cannot_read_each_others_persistent_object(self):
        a, one, _ = self.bootstrap()
        b, two, _ = self.bootstrap()
        self.assertNotEqual(one["tenant"], two["tenant"])
        context = self.app.services.sessions.bootstrap(a).context
        project = self.app.services.storage.create(context, "projects", {"name": "合成私有项目"})
        path = "/api/v1/fixture-projects/" + project["id"]
        status, _, body = self.request(path, cookie=b)
        self.assertEqual((status, body["error"]["code"]), (404, "NOT_FOUND"))

    def test_actual_csrf_logout_and_revoked_cookie_fail_closed(self):
        cookie, data, _ = self.bootstrap()
        path = "/api/v1/session/logout"
        status, _, body = self.request(path, method="POST", cookie=cookie, csrf="wrong", body={})
        self.assertEqual((status, body["error"]["code"]), (403, "CSRF_FAILED"))
        _, unchanged, _ = self.bootstrap(cookie=cookie)
        self.assertEqual(unchanged["tenant"], data["tenant"])
        status, headers, body = self.request(path, method="POST", cookie=cookie, csrf=data["csrfToken"], body={})
        self.assertEqual((status, body["data"]), (200, {"loggedOut": True}))
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        status, _, body = self.request("/api/v1/session", cookie=cookie)
        self.assertEqual((status, body["error"]["code"]), (401, "SESSION_REQUIRED"))

    def test_expired_cookie_does_not_silently_create_a_new_tenant(self):
        cookie, data, _ = self.bootstrap()
        now = self.app.services.storage.clock()
        self.app.services.storage.clock = lambda: now + 100 * 86400
        status, _, body = self.request("/api/v1/session", cookie=cookie)
        self.assertEqual((status, body["error"]["code"]), (401, "SESSION_REQUIRED"))
        with self.app.services.storage._system_transaction(write=False) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM tenants").fetchone()[0], 1)

    def test_subpath_cookie_is_scoped_and_local_instances_do_not_collide(self):
        root_cookie, _, _ = self.bootstrap()
        app, server = self.start("/asset-lab/", data_name="subpath-data")
        cookie, data, headers = self.bootstrap(app=app, server=server)
        self.assertIn("Path=/asset-lab/", headers["Set-Cookie"])
        self.assertNotEqual(root_cookie.split("=", 1)[0], cookie.split("=", 1)[0])
        _, restored, _ = self.bootstrap(app=app, server=server, cookie=cookie)
        self.assertEqual(restored["tenant"], data["tenant"])

    def test_https_subpath_cookie_uses_valid_secure_prefix(self):
        app, server = self.start("/asset-lab/", data_name="https-data", public_origin="https://example.invalid")
        cookie, data, headers = self.bootstrap(app=app, server=server)
        self.assertTrue(cookie.startswith("__Secure-"))
        self.assertIn("Secure", headers["Set-Cookie"])
        self.assertIn("Path=/asset-lab/", headers["Set-Cookie"])
        self.assertNotIn("Domain=", headers["Set-Cookie"])

    def test_readiness_confirms_storage_but_not_provider_or_full_customer_flow(self):
        status, _, body = self.request("/api/v1/ready")
        self.assertEqual(status, 503)
        self.assertTrue(body["data"]["checks"]["storage"]["ready"])
        self.assertTrue(body["data"]["checks"]["sessions"]["ready"])
        self.assertFalse(body["data"]["checks"]["providers"]["ready"])
        self.assertFalse(body["data"]["customerReady"])


if __name__ == "__main__":
    unittest.main()
