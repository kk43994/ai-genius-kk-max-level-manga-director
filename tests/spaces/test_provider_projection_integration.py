"""Black-box module 2 -> SpaceService -> module 3 compatibility replay.

The account_user shape comes from module 2's sanitized fixture. Every identity,
space, membership, authorization response, key and token value is synthetic.
The injected transport has no real HTTP implementation.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from backend.spaces import SpaceError, SpaceService

try:
    from backend.auth import ProviderService
    from backend.auth.secrets import AesGcmSecretCodec
    from backend.auth.storage_adapter import StorageAuthRepository
    from backend.providers.libtv_oauth import HTTPResult, ISSUER, RESOURCE, RESOURCE_METADATA, LibTVOAuth, OAuthConfig
    from backend.sessions import SessionService
    from backend.storage import Store, SelectionRepository
except ModuleNotFoundError as error:
    if error.name not in {"backend.auth", "backend.providers", "backend.sessions", "backend.storage", "cryptography"}:
        raise
    ProviderService = None

FIXTURES = Path(__file__).parent / "fixtures"


class OfflineAccountHTTP:
    def __init__(self):
        self.payload = json.loads((FIXTURES / "libtv-account-user.synthetic.json").read_text())
        self.tool = json.loads((FIXTURES / "libtv-account-user-tool.public.json").read_text())["tool"]
        self.calls, self.token_requests = [], 0

    def request(self, method, url, *, data=None, headers=None):
        if url == RESOURCE and method == "POST":
            rpc = json.loads(data)
            self.calls.append(rpc)
            if rpc["method"] == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {},
                          "serverInfo": {"name": "synthetic-only", "version": "1"}}
            elif rpc["method"] == "notifications/initialized":
                return HTTPResult(202, {})
            elif rpc["method"] == "tools/list":
                result = {"tools": [deepcopy(self.tool)]}
            elif rpc["method"] == "tools/call" and rpc["params"] == {"name": "account_user", "arguments": {}}:
                result = {"structuredContent": deepcopy(self.payload)}
            else:
                raise AssertionError("Only account_user is allowed; no write or generation calls")
            return HTTPResult(200, {"jsonrpc": "2.0", "id": rpc["id"], "result": result})
        if method == "GET" and url == RESOURCE:
            return HTTPResult(401, {}, {"WWW-Authenticate": f'Bearer resource_metadata="{RESOURCE_METADATA}"'})
        if method == "GET" and url == RESOURCE_METADATA:
            return HTTPResult(200, {"resource": RESOURCE, "authorization_servers": [ISSUER], "scopes_supported": []})
        if method == "GET" and url == ISSUER + ".well-known/oauth-authorization-server":
            return HTTPResult(200, {"issuer": ISSUER, "authorization_endpoint": ISSUER + "authorize",
                "token_endpoint": ISSUER + "token", "registration_endpoint": ISSUER + "register",
                "revocation_endpoint": ISSUER + "revoke", "scopes_supported": ["libtv:account:read"],
                "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"], "code_challenge_methods_supported": ["S256"]})
        if method == "POST" and url == ISSUER + "register":
            return HTTPResult(201, {"client_id": "synthetic-client",
                                   "redirect_uris": json.loads(data)["redirect_uris"],
                                   "token_endpoint_auth_method": "none"})
        if method == "POST" and url == ISSUER + "token":
            self.token_requests += 1
            return HTTPResult(200, {"access_token": "synthetic-access-" + str(self.token_requests),
                                   "refresh_token": "synthetic-refresh-" + str(self.token_requests),
                                   "expires_in": 3600, "token_type": "Bearer", "scope": "libtv:account:read"})
        if method == "POST" and url == ISSUER + "revoke":
            return HTTPResult(200, {})
        raise AssertionError("No arbitrary URL or live network access is permitted")


@unittest.skipIf(ProviderService is None, "requires module 2 provider and module 3 persistence")
class ProviderProjectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asset-lab-provider-projection-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.now, key = 1793088000.0, bytes(range(32))
        self.store = Store(root / "data", encryption_key=key, release_root=root / "release", clock=lambda: self.now)
        self.sessions = SessionService(self.store, public_origin="https://example.invalid")
        self.ctx = dict(asdict(self.sessions.create().context), csrfVerified=True)
        self.http = OfflineAccountHTTP()
        oauth = LibTVOAuth(OAuthConfig("https://example.invalid/api/v1/oauth/libtv/callback"), self.http)
        self.providers = ProviderService(StorageAuthRepository(self.store), AesGcmSecretCodec({"test": key}, "test"),
                                         oauth, clock=lambda: self.now)
        self.selections = SelectionRepository(self.store)
        self.spaces = SpaceService(self.providers, self.selections,
                                  clock=lambda: datetime.fromtimestamp(self.now, timezone.utc))
        attempt = self.providers.begin_authorization(self.ctx)
        state = parse_qs(urlsplit(attempt["authorizationUrl"]).query)["state"][0]
        self.providers.complete_authorization(self.ctx, {"code": "synthetic-code", "state": state})
        result = self.providers.get_attempt(self.ctx, attempt["attemptId"])
        self.assertEqual(result["status"], "completed", result)
        self.account_id = result["providerAccountId"]

    def test_authoritative_identity_and_space_projection_share_one_login(self):
        profile = self.spaces.profile(self.ctx, self.account_id)
        self.assertEqual(profile["identity"]["subject"], self.http.payload["user"]["uuid"])
        self.assertEqual(profile["identity"]["displayName"], self.http.payload["user"]["nickname"])
        rows = self.spaces.list_spaces(self.ctx, self.account_id)["items"]
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["kind"] for r in rows}, {"personal", "team"})
        self.assertTrue(all(r["access"] == "available" for r in rows))
        self.assertEqual(len(self.providers.list_accounts(self.ctx)["items"]), 1)

    def test_space_selection_never_rebinds_stored_task_identity(self):
        rows = self.spaces.list_spaces(self.ctx, self.account_id)["items"]
        personal = next(r for r in rows if r["kind"] == "personal")
        team = next(r for r in rows if r["kind"] == "team")
        self.spaces.set_selection(self.ctx, providerAccountId=self.account_id, spaceId=personal["id"], expectedRevision=0)
        with self.store.transaction(self.ctx) as tx:
            owner = self.selections.bind_ownership(tx, expected_revision=1)
            task = tx.create("tasks", {"ownership": owner, "status": "draft"})
        self.spaces.set_selection(self.ctx, providerAccountId=self.account_id, spaceId=team["id"], expectedRevision=1)
        self.assertEqual(self.store.get(self.ctx, "tasks", task["id"])["data"]["ownership"], owner)
        self.assertEqual(owner["providerSubject"], self.http.payload["user"]["uuid"])
        self.assertEqual(self.spaces.get_selection(self.ctx)["spaceId"], team["id"])
        self.assertEqual(self.spaces.get_selection(self.ctx)["providerAccountId"], self.account_id)

    def test_membership_fields_cannot_become_balance_in_either_space(self):
        for account in self.http.payload["accounts"]["accounts"]:
            account["memberAccount"].update(points=999999, quota=888888, remaining=777777)
        for row in self.spaces.list_spaces(self.ctx, self.account_id)["items"]:
            quota = self.spaces.quota(self.ctx, self.account_id, row["id"])
            self.assertEqual(quota["state"], "unknown")
            self.assertIsNone(quota["remaining"])
            self.assertEqual(quota["buckets"], [])
            self.assertEqual(quota["providerAccountId"], self.account_id)
            self.assertEqual(quota["spaceId"], row["id"])
            self.assertEqual(quota["officialViewUrl"], "https://www.liblib.tv/")

    def test_expired_public_state_allows_bound_auth_refresh_then_read(self):
        self.now += 3601
        self.assertEqual(self.providers.get_account(self.ctx, self.account_id)["authorization"]["state"], "expired")
        self.assertEqual(len(self.spaces.list_spaces(self.ctx, self.account_id)["items"]), 2)
        self.assertEqual(self.http.token_requests, 2)
        self.assertEqual(self.providers.get_account(self.ctx, self.account_id)["authorization"]["state"], "connected")

    def test_mismatched_subject_after_refresh_is_rejected(self):
        self.now += 3601
        self.http.payload["user"]["uuid"] = "00000000-0000-4000-8000-000000000099"
        with self.assertRaises(SpaceError) as caught:
            self.spaces.list_spaces(self.ctx, self.account_id)
        self.assertEqual(caught.exception.code, "OWNERSHIP_MISMATCH")
        self.assertEqual(self.providers.get_account(self.ctx, self.account_id)["authorization"]["state"], "expired")

    def test_cross_tenant_lookup_rejected_before_account_read(self):
        other = dict(asdict(self.sessions.create().context), csrfVerified=True)
        count = len(self.http.calls)
        with self.assertRaises(SpaceError) as caught:
            self.spaces.list_spaces(other, self.account_id)
        self.assertEqual(caught.exception.code, "NOT_FOUND")
        self.assertEqual(len(self.http.calls), count)

    def test_valid_token_snapshot_with_wrong_subject_invalidates_space_access(self):
        self.spaces.list_spaces(self.ctx, self.account_id)
        original = self.providers.get_account(self.ctx, self.account_id)["identity"]["subject"]
        self.http.payload["user"]["uuid"] = "00000000-0000-4000-8000-000000000099"
        with self.assertRaises(SpaceError) as caught:
            self.spaces.list_spaces(self.ctx, self.account_id)
        self.assertEqual(caught.exception.code, "OWNERSHIP_MISMATCH")
        self.assertEqual(self.providers.get_account(self.ctx, self.account_id)["identity"]["subject"], original)
        cached = self.selections.list_spaces(self.ctx, self.account_id)["items"]
        self.assertTrue(cached)
        self.assertTrue(all(r["access"] == "unknown" for r in cached))

    def test_unknown_official_account_type_does_not_become_a_personal_space(self):
        self.http.payload["accounts"]["accounts"][0]["accountType"] = 99
        with self.assertRaises(SpaceError) as caught:
            self.spaces.list_spaces(self.ctx, self.account_id)
        self.assertEqual(caught.exception.code, "PROVIDER_CAPABILITY_UNAVAILABLE")
        self.assertEqual(self.selections.get(self.ctx)["revision"], 0)

    def test_only_account_read_tool_is_called(self):
        for row in self.spaces.list_spaces(self.ctx, self.account_id)["items"]:
            self.spaces.quota(self.ctx, self.account_id, row["id"])
        names = [r["params"]["name"] for r in self.http.calls if r["method"] == "tools/call"]
        self.assertTrue(names)
        self.assertEqual(set(names), {"account_user"})


if __name__ == "__main__":
    unittest.main()
