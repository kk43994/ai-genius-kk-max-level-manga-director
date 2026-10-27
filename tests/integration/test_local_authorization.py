"""Real local HTTP, persistent sessions and official-shaped offline OAuth/MCP."""
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from backend.app import Config, ConfigurationError, CustomerHTTPServer, create_app
from local_client.launch import provision
from tests.spaces.test_provider_projection_integration import OfflineAccountHTTP


class LocalAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.key = provision(self.root / "instance")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.fake = OfflineAccountHTTP()
        self.server = None
        self.start()
        self.addCleanup(self.stop)
        status, headers, value = self.request("/session")
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.session = value["data"]

    def start(self, local=True):
        config = Config(self.root / "instance/data", port=self.port, public_base_path="/asset-lab/",
                        secret_key_file=self.key, local_client=local)
        with patch("backend.providers.libtv_oauth.OfficialHTTP", return_value=self.fake):
            self.app = create_app(config)
        self.server = CustomerHTTPServer(self.app)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.server = None

    def request(self, path, method="GET", body=None, *, auth=True, origin=None):
        headers = {}
        if auth and hasattr(self, "cookie"):
            headers.update(Cookie=self.cookie)
            headers["X-CSRF-Token"] = self.session["csrfToken"]
            headers["X-Asset-Lab-Session"] = self.session["session"]["id"]
        if method != "GET":
            headers["Origin"] = origin or self.origin
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        try:
            connection.request(method, "/asset-lab/api/v1" + path,
                               json.dumps(body).encode() if body is not None else None, headers)
            response = connection.getresponse()
            raw = response.read()
            value = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
            return response.status, dict(response.getheaders()), value
        finally:
            connection.close()

    def begin(self):
        status, _, value = self.request("/provider-accounts/authorize", "POST", {"provider": "libtv", "returnPath": "/asset-lab/"})
        self.assertEqual(status, 200, value)
        attempt = value["data"]
        query = parse_qs(urlsplit(attempt["authorizationUrl"]).query)
        self.assertEqual(query["redirect_uri"], [self.origin + "/asset-lab/api/v1/oauth/libtv/callback"])
        self.assertEqual(query["scope"], ["libtv:account:read"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        return attempt, query["state"][0]

    def complete(self):
        attempt, state = self.begin()
        status, headers, _ = self.request("/oauth/libtv/callback?" + urlencode({"code": "synthetic-code", "state": state}))
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/asset-lab/api/v1/oauth/libtv/return")
        status, _, value = self.request("/authorization-attempts/" + attempt["attemptId"])
        self.assertEqual(value["data"]["status"], "completed", value)
        return value["data"]["providerAccountId"]

    def test_connect_button_flow_reads_identity_then_personal_and_team(self):
        self.assertTrue(self.session["features"]["providerAuthorization"])
        self.assertFalse(self.session["features"]["imageGeneration"])
        _, _, readiness = self.request("/ready")
        self.assertEqual(readiness["data"]["checks"]["providers"],
                         {"ready": True, "reason": "local_readonly_oauth_enabled"})
        account = self.complete()
        _, _, value = self.request("/provider-accounts/" + account)
        self.assertTrue(value["data"]["identity"]["verified"])
        self.assertEqual(value["data"]["authorization"]["state"], "connected")
        _, _, value = self.request("/provider-accounts/" + account + "/spaces")
        self.assertEqual({x["kind"] for x in value["data"]["items"]}, {"personal", "team"})
        self.assertEqual({r["params"]["name"] for r in self.fake.calls if r["method"] == "tools/call"}, {"account_user"})

    def test_account_and_session_survive_service_restart(self):
        account = self.complete()
        cookie, session = self.cookie, self.session
        self.stop(); self.start()
        self.cookie, self.session = cookie, session
        status, _, value = self.request("/provider-accounts/" + account)
        self.assertEqual(status, 200)
        self.assertEqual(value["data"]["authorization"]["state"], "connected")

    def test_replayed_callback_never_exchanges_twice(self):
        attempt, state = self.begin()
        callback = "/oauth/libtv/callback?" + urlencode({"code": "synthetic-code", "state": state})
        self.request(callback); self.request(callback)
        self.assertEqual(self.fake.token_requests, 1)

    def test_cancel_keeps_no_connected_account(self):
        attempt, state = self.begin()
        self.request("/oauth/libtv/callback?" + urlencode({"error": "access_denied", "state": state}))
        _, _, value = self.request("/authorization-attempts/" + attempt["attemptId"])
        self.assertEqual(value["data"]["status"], "failed")
        _, _, value = self.request("/provider-accounts")
        self.assertFalse(any(x["authorization"]["state"] == "connected" for x in value["data"]["items"]))

    def test_other_browser_cannot_finish_original_attempt(self):
        attempt, state = self.begin()
        self.request("/oauth/libtv/callback?" + urlencode({"code": "synthetic-code", "state": state}), auth=False)
        self.assertEqual(self.fake.token_requests, 0)
        _, _, value = self.request("/authorization-attempts/" + attempt["attemptId"])
        self.assertEqual(value["data"]["status"], "pending")

    def test_local_flag_does_not_open_public_client_or_owner_recovery(self):
        for origin, host, port in [("https://example.com", "127.0.0.1", 18874),
                                   (self.origin, "0.0.0.0", self.port), ("http://127.0.0.1:0", "127.0.0.1", 0)]:
            with self.assertRaises(ConfigurationError):
                Config(self.root / "data", host=host, port=port, public_origin=origin, local_client=True)
        status, _, value = self.request("/provider-accounts/authorize", "POST", {"provider": "libtv", "purpose": "bind_owner"})
        self.assertEqual(status, 503)

    def test_csrf_and_cross_origin_calls_are_rejected(self):
        status, _, _ = self.request("/provider-accounts/authorize", "POST", {"provider": "libtv"}, origin="https://example.com")
        self.assertEqual(status, 403)
        status, _, _ = self.request("/provider-accounts/authorize", "POST", {"provider": "libtv"}, auth=False)
        self.assertEqual(status, 401)

    def test_website_gate_stays_closed(self):
        self.stop(); self.start(local=False)
        status, _, _ = self.request("/provider-accounts/authorize", "POST", {"provider": "libtv"})
        self.assertEqual(status, 503)

    def test_existing_workspace_key_is_not_replaced(self):
        original = self.key.read_bytes()
        self.assertEqual(provision(self.root / "instance").read_bytes(), original)
        self.key.unlink()
        with self.assertRaises(ValueError):
            provision(self.root / "instance")
