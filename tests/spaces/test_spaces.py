"""Synthetic contract tests. These do not certify real LibTV account formats."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import unittest

from backend.spaces import SpaceError, SpaceService, register_routes
from backend.spaces import normalize

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
TENANT_A = {"tenantId": "synthetic-tenant-a", "siteSessionId": "synthetic-session-a",
            "requestId": "request-a", "csrfVerified": True}
TENANT_B = {"tenantId": "synthetic-tenant-b", "siteSessionId": "synthetic-session-b",
            "requestId": "request-b", "csrfVerified": True}


def account(account_id, subject, tenant="synthetic-tenant-a"):
    return {"id": account_id, "tenantId": tenant, "provider": "libtv", "label": "合成账号",
            "identity": {"verified": True, "issuer": normalize.OFFICIAL_ISSUER,
                         "subject": subject, "displayName": "合成身份"},
            "authorization": {"state": "connected"}, "removedAt": None}


def known_quota(account_id="pa-a", space_id="personal", remaining=0):
    return {"providerAccountId": account_id, "spaceId": space_id, "state": "known",
            "remaining": remaining, "unit": "credits", "buckets": [], "planName": "合成套餐",
            "source": "official", "observedAt": normalize.iso(NOW), "expiresAt": None}


class ProviderFailure(Exception):
    def __init__(self, code, text="synthetic-secret-must-not-escape"):
        self.code = code
        super().__init__(text)


class BoundClient:
    def __init__(self, owner, provider):
        self.owner, self.provider = deepcopy(owner), provider

    def identity(self):
        self.provider.calls.append(("identity", deepcopy(self.owner)))
        if self.provider.identity_override is not None:
            return deepcopy(self.provider.identity_override)
        return deepcopy(self.provider.accounts[(self.owner["tenantId"], self.owner["providerAccountId"])]["identity"])

    def list_spaces(self):
        self.provider.calls.append(("list_spaces", deepcopy(self.owner)))
        if self.provider.spaces_error:
            raise self.provider.spaces_error
        return deepcopy(self.provider.space_payload)

    def quota(self, space_id):
        assert space_id == self.owner["spaceId"]
        self.provider.calls.append(("quota", deepcopy(self.owner)))
        if self.provider.quota_error:
            raise self.provider.quota_error
        if self.provider.quota_payload is not None:
            return deepcopy(self.provider.quota_payload)
        balances = {"pa-a": 0, "pa-b": 82, "pa-c": 37}
        return known_quota(self.owner["providerAccountId"], space_id, balances[self.owner["providerAccountId"]])

    def list_models(self, space_id):
        assert space_id == self.owner["spaceId"]
        self.provider.calls.append(("list_models", deepcopy(self.owner)))
        return {"items": [{"modelKey": "synthetic-model", "modelName": "合成图片模型",
                            "mediaType": "image", "token": "must-be-discarded"}], "nextCursor": None}


class Providers:
    def __init__(self):
        self.accounts = {(TENANT_A["tenantId"], "pa-a"): account("pa-a", "subject-a"),
                         (TENANT_A["tenantId"], "pa-b"): account("pa-b", "subject-b"),
                         (TENANT_B["tenantId"], "pa-c"): account("pa-c", "subject-a", TENANT_B["tenantId"])}
        self.calls, self.clients = [], []
        self.identity_override = None
        self.quota_payload = self.quota_error = self.spaces_error = None
        self.space_payload = {"items": [
            {"id": "personal", "kind": "personal", "name": "合成个人空间", "access": "available"},
            {"id": "team", "kind": "team", "name": "合成团队空间", "access": "available"},
        ], "nextCursor": None}

    def get_account(self, ctx, account_id):
        self.calls.append(("get_account", {"tenantId": ctx["tenantId"], "providerAccountId": account_id}))
        result = self.accounts.get((ctx["tenantId"], account_id))
        if result is None:
            raise ProviderFailure("NOT_FOUND")
        return deepcopy(result)

    def client_for(self, ctx, ownership):
        assert ownership["spaceId"]
        return self._bound(ctx, ownership)

    def account_client_for(self, ctx, ownership):
        assert ownership["spaceId"] is None
        return self._bound(ctx, ownership)

    def _bound(self, ctx, ownership):
        assert ownership["tenantId"] == ctx["tenantId"]
        assert ownership["providerAccountId"]
        assert ownership["providerSubject"]
        if self.accounts[(ctx["tenantId"], ownership["providerAccountId"])]["authorization"]["state"] == "expired":
            raise ProviderFailure("TOKEN_EXPIRED")
        client = BoundClient(ownership, self)
        self.clients.append(client)
        return client


class Selections:
    """Test-only CAS store. Production must use the persistent session store."""
    def __init__(self):
        self.rows, self.snapshots, self.lock = {}, {}, threading.Lock()

    def get(self, ctx):
        return deepcopy(self.rows.get(ctx["tenantId"], {"providerAccountId": None, "spaceId": None, "revision": 0}))

    def replace_spaces(self, ctx, account_id, spaces):
        self.snapshots[(ctx["tenantId"], account_id)] = deepcopy(spaces)

    def invalidate_spaces(self, ctx, account_id):
        for row in self.snapshots.get((ctx["tenantId"], account_id), []):
            row["access"] = "unknown"

    def set(self, ctx, account_id, space_id, *, expected_revision):
        with self.lock:
            key = ctx["tenantId"]
            old = self.rows.get(key, {"providerAccountId": None, "spaceId": None, "revision": 0})
            if old["revision"] != expected_revision:
                raise ProviderFailure("SELECTION_CHANGED")
            self.rows[key] = {"providerAccountId": account_id, "spaceId": space_id, "revision": expected_revision + 1}
            return deepcopy(self.rows[key])


class SpacesTests(unittest.TestCase):
    def setUp(self):
        self.providers, self.selections = Providers(), Selections()
        self.service = SpaceService(self.providers, self.selections, clock=lambda: NOW)

    def assert_code(self, code, action):
        with self.assertRaises(SpaceError) as error:
            action()
        self.assertEqual(error.exception.code, code)
        self.assertNotIn("synthetic-secret", str(error.exception))
        return error.exception

    def test_no_session_does_not_resolve_a_server_account(self):
        self.assert_code("SESSION_REQUIRED", lambda: self.service.list_spaces({}, "pa-a"))
        self.assertEqual(self.providers.calls, [])

    def test_missing_account_is_rejected_before_provider_access(self):
        for value in (None, "", "default\naccount", 123, True):
            self.assert_code("VALIDATION_FAILED", lambda: self.service.list_spaces(TENANT_A, value))
        self.assertEqual(self.providers.calls, [])

    def test_missing_account_reader_never_fabricates_a_default_space(self):
        self.providers.account_client_for = None
        self.assert_code("PROVIDER_CAPABILITY_UNAVAILABLE", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.assertEqual(self.providers.clients, [])

    def test_cross_tenant_account_returns_404_and_never_creates_client(self):
        error = self.assert_code("NOT_FOUND", lambda: self.service.list_spaces(TENANT_B, "pa-a"))
        self.assertEqual(error.status, 404)
        self.assertEqual(self.providers.clients, [])

    def test_buggy_provider_foreign_tenant_account_rejected(self):
        self.providers.accounts[(TENANT_A["tenantId"], "pa-a")]["tenantId"] = TENANT_B["tenantId"]
        self.assert_code("NOT_FOUND", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.assertEqual(self.providers.clients, [])

    def test_removed_and_expired_accounts_cannot_use_saved_results(self):
        record = self.providers.accounts[(TENANT_A["tenantId"], "pa-a")]
        record["authorization"]["state"] = "expired"
        self.assert_code("PROVIDER_AUTHORIZATION_REQUIRED", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))
        record["removedAt"] = normalize.iso(NOW)
        self.assert_code("NOT_FOUND", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))
        self.assertEqual(self.providers.clients, [])

    def test_cli_account_id_is_never_a_subject(self):
        record = self.providers.accounts[(TENANT_A["tenantId"], "pa-a")]
        record["identity"] = {"activeAccount": {"accountId": 42, "accountName": "团队"}}
        self.assert_code("PROVIDER_IDENTITY_UNVERIFIED", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.assertEqual(self.providers.clients, [])

    def test_unsigned_or_missing_identity_evidence_is_rejected(self):
        for key, value in (("verified", False), ("subject", None), ("issuer", "https://other.example/")):
            with self.subTest(key=key):
                self.providers.identity_override = {**account("pa-a", "subject-a")["identity"], key: value}
                self.assert_code("PROVIDER_IDENTITY_UNVERIFIED", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.assertFalse(any(name == "list_spaces" for name, _ in self.providers.calls))

    def test_new_phone_identity_cannot_replace_old_subject(self):
        self.providers.identity_override = account("pa-b", "subject-b")["identity"]
        self.assert_code("OWNERSHIP_MISMATCH", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))
        self.assertFalse(any(name == "list_spaces" for name, _ in self.providers.calls))

    def test_profile_whitelists_fields(self):
        self.providers.identity_override = {**account("pa-a", "subject-a")["identity"], "access_token": "must-be-discarded"}
        result = self.service.profile(TENANT_A, "pa-a")
        self.assertEqual(result["identity"]["subject"], "subject-a")
        self.assertNotIn("access_token", json.dumps(result))

    def test_spaces_distinguish_personal_team_without_switching_login(self):
        result = self.service.list_spaces(TENANT_A, "pa-a")
        self.assertEqual([s["kind"] for s in result["items"]], ["personal", "team"])
        self.assertEqual(len(self.providers.clients), 1)
        self.assertEqual(self.providers.clients[0].owner["providerSubject"], "subject-a")
        self.assertIsNone(self.providers.clients[0].owner["spaceId"])

    def test_raw_cli_response_is_not_reinterpreted_as_space_list(self):
        self.providers.space_payload = {"activeAccount": {"accountId": 12}, "accounts": []}
        self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.list_spaces(TENANT_A, "pa-a"))

    def test_empty_official_list_is_preserved_without_fake_personal_space(self):
        self.providers.space_payload = {"items": [], "nextCursor": None}
        self.assertEqual(self.service.list_spaces(TENANT_A, "pa-a")["items"], [])
        self.assert_code("NOT_FOUND", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_incomplete_space_list_is_an_error_not_silent_empty(self):
        self.providers.space_payload["nextCursor"] = "next-page"
        self.assert_code("PROVIDER_CAPABILITY_UNAVAILABLE", lambda: self.service.list_spaces(TENANT_A, "pa-a"))

    def test_duplicate_space_ids_are_rejected(self):
        self.providers.space_payload["items"].append(deepcopy(self.providers.space_payload["items"][0]))
        self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.list_spaces(TENANT_A, "pa-a"))

    def test_unknown_or_revoked_space_cannot_read_balance_or_be_selected(self):
        for state in ("unknown", "revoked"):
            self.providers.space_payload["items"][0]["access"] = state
            self.assert_code("SPACE_UNAVAILABLE", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))
            self.assert_code("SPACE_UNAVAILABLE", lambda: self.service.set_selection(TENANT_A,
                providerAccountId="pa-a", spaceId="personal", expectedRevision=0))
        self.assertFalse(any(name == "quota" for name, _ in self.providers.calls))
        self.assertEqual(self.selections.rows, {})

    def test_old_space_access_must_be_reverified(self):
        self.providers.space_payload["items"][0]["checkedAt"] = normalize.iso(NOW - timedelta(minutes=5))
        self.assert_code("SPACE_UNAVAILABLE", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_other_accounts_space_metadata_is_rejected(self):
        self.providers.space_payload["items"][0]["providerAccountId"] = "pa-b"
        self.assert_code("OWNERSHIP_MISMATCH", lambda: self.service.list_spaces(TENANT_A, "pa-a"))

    def test_official_zero_remains_a_known_zero(self):
        result = self.service.quota(TENANT_A, "pa-a", "personal")
        self.assertEqual((result["state"], result["remaining"]), ("known", 0))
        self.assertEqual(result["observedAt"], normalize.iso(NOW))

    def test_account_and_space_reads_are_bound_independently(self):
        a = self.service.quota(TENANT_A, "pa-a", "team")
        b = self.service.quota(TENANT_A, "pa-b", "team")
        c = self.service.quota(TENANT_B, "pa-c", "team")
        self.assertEqual([a["remaining"], b["remaining"], c["remaining"]], [0, 82, 37])
        owners = [owner for name, owner in self.providers.calls if name == "quota"]
        self.assertEqual([(o["tenantId"], o["providerAccountId"], o["providerSubject"], o["spaceId"]) for o in owners],
                         [(TENANT_A["tenantId"], "pa-a", "subject-a", "team"),
                          (TENANT_A["tenantId"], "pa-b", "subject-b", "team"),
                          (TENANT_B["tenantId"], "pa-c", "subject-a", "team")])

    def test_plan_allowance_is_not_spendable_balance(self):
        self.providers.quota_payload = {"planName": "合成套餐", "planCredits": 18000,
                                        "activeAccount": {"packagePoints": 20000}, "remaining": 15000}
        result = self.service.quota(TENANT_A, "pa-a", "personal")
        self.assertEqual(result["planName"], "合成套餐")
        self.assertEqual(result["state"], "unknown")
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["buckets"], [])
        self.assertEqual(result["officialViewUrl"], "https://www.liblib.tv/")

    def test_unsupported_quota_is_unknown_with_official_view_link(self):
        self.providers.quota_error = NotImplementedError("must-not-escape")
        result = self.service.quota(TENANT_A, "pa-a", "personal")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "provider_capability_unavailable")
        self.assertIsNone(result["remaining"])
        self.assertIsNone(result["observedAt"])

    def test_quota_network_failure_does_not_reuse_previous_accounts_balance(self):
        self.service.quota(TENANT_A, "pa-b", "personal")
        self.providers.quota_error = TimeoutError("synthetic-secret-must-not-escape")
        result = self.service.quota(TENANT_A, "pa-a", "personal")
        self.assertEqual(result["state"], "unavailable")
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["providerAccountId"], "pa-a")

    def test_expired_authorization_is_not_relabelled_unknown_quota(self):
        self.providers.quota_error = ProviderFailure("TOKEN_EXPIRED")
        self.assert_code("PROVIDER_AUTHORIZATION_REQUIRED", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_other_scope_quota_is_rejected_even_when_amount_is_valid(self):
        for key, value in (("tenantId", TENANT_B["tenantId"]), ("providerAccountId", "pa-b"), ("spaceId", "team")):
            self.providers.quota_payload = {**known_quota(), key: value}
            self.assert_code("OWNERSHIP_MISMATCH", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_non_numeric_negative_and_ambiguous_balances_rejected(self):
        for value in (True, -1, float("nan"), float("inf"), "100", 9007199254740992, 10**1000):
            with self.subTest(value=value):
                self.providers.quota_payload = known_quota(remaining=value)
                self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_known_balance_requires_source_scope_and_timestamp(self):
        for key in ("source", "providerAccountId", "spaceId", "observedAt"):
            self.providers.quota_payload = known_quota()
            del self.providers.quota_payload[key]
            self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_old_and_expired_balances_are_explicitly_stale(self):
        self.providers.quota_payload = {**known_quota(remaining=8), "observedAt": normalize.iso(NOW - timedelta(minutes=3))}
        result = self.service.quota(TENANT_A, "pa-a", "personal")
        self.assertEqual((result["state"], result["remaining"]), ("stale", 8))
        self.providers.quota_payload = {**known_quota(remaining=3), "expiresAt": normalize.iso(NOW)}
        self.assertEqual(self.service.quota(TENANT_A, "pa-a", "personal")["state"], "stale")

    def test_future_observation_is_rejected(self):
        self.providers.quota_payload = {**known_quota(), "observedAt": normalize.iso(NOW + timedelta(minutes=1))}
        self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))

    def test_different_quota_buckets_are_preserved_without_adding(self):
        self.providers.quota_payload = {**known_quota(), "remaining": None, "buckets": [
            {"id": "credits", "name": "合成积分", "remaining": 30, "unit": "credits"},
            {"id": "currency", "name": "合成金额", "remaining": 5, "unit": "CNY"}]}
        result = self.service.quota(TENANT_A, "pa-a", "personal")
        self.assertIsNone(result["remaining"])
        self.assertEqual([b["unit"] for b in result["buckets"]], ["credits", "CNY"])

    def test_only_whitelisted_quota_fields_are_public(self):
        self.providers.quota_payload = {**known_quota(), "token": "must-not-escape", "signedUrl": "https://secret.example"}
        raw = json.dumps(self.service.quota(TENANT_A, "pa-a", "personal"))
        self.assertNotIn("must-not-escape", raw)
        self.assertNotIn("secret.example", raw)

    def test_model_reads_do_not_enable_generation(self):
        result = self.service.list_models(TENANT_A, "pa-a", "team")
        self.assertFalse(result["generationEnabled"])
        self.assertFalse(result["items"][0]["generationEnabled"])
        self.assertNotIn("token", json.dumps(result))
        self.assertFalse(any(name in {"prepare", "submit", "run"} for name, _ in self.providers.calls))

    def test_selection_switch_changes_only_current_selection(self):
        historical_owner = {"tenantId": TENANT_A["tenantId"], "providerAccountId": "pa-a", "spaceId": "personal"}
        historical_task = {"id": "synthetic-task", "ownership": deepcopy(historical_owner)}
        self.service.set_selection(TENANT_A, providerAccountId="pa-a", spaceId="personal", expectedRevision=0)
        result = self.service.set_selection(TENANT_A, providerAccountId="pa-b", spaceId="team", expectedRevision=1)
        self.assertEqual(result, {"providerAccountId": "pa-b", "spaceId": "team", "revision": 2})
        self.assertEqual(historical_task["ownership"], historical_owner)

    def test_stale_selection_revision_does_not_overwrite(self):
        self.service.set_selection(TENANT_A, providerAccountId="pa-a", spaceId="personal", expectedRevision=0)
        self.assert_code("SELECTION_CHANGED", lambda: self.service.set_selection(TENANT_A,
            providerAccountId="pa-b", spaceId="team", expectedRevision=0))
        self.assertEqual(self.selections.rows[TENANT_A["tenantId"]]["providerAccountId"], "pa-a")

    def test_concurrent_selection_updates_have_one_winner(self):
        def update(account_id):
            try:
                self.service.set_selection(TENANT_A, providerAccountId=account_id, spaceId="personal", expectedRevision=0)
                return "saved"
            except SpaceError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(update, ["pa-a", "pa-b"]))
        self.assertCountEqual(result, ["saved", "SELECTION_CHANGED"])

    def test_clear_selection_without_any_provider_calls(self):
        result = self.service.set_selection(TENANT_A, providerAccountId=None, spaceId=None, expectedRevision=0)
        self.assertEqual(result["revision"], 1)
        self.assertEqual(self.providers.calls, [])

    def test_clear_account_cannot_keep_an_old_space(self):
        self.assert_code("VALIDATION_FAILED", lambda: self.service.set_selection(TENANT_A,
            providerAccountId=None, spaceId="personal", expectedRevision=0))
        self.assertEqual(self.selections.rows, {})

    def test_missing_persistent_store_is_not_a_fake_success(self):
        self.service.selections = None
        self.assert_code("PROVIDER_CAPABILITY_UNAVAILABLE", lambda: self.service.set_selection(TENANT_A,
            providerAccountId=None, spaceId=None, expectedRevision=0))

    def test_spaces_provider_errors_are_safe_and_do_not_fallback(self):
        self.providers.spaces_error = ProviderFailure("INTERNAL_ERROR")
        self.assert_code("PROVIDER_UNAVAILABLE", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.assertEqual(len(self.providers.clients), 1)

    def test_failure_invalidates_only_the_requested_accounts_space_snapshot(self):
        self.service.list_spaces(TENANT_A, "pa-a")
        self.service.list_spaces(TENANT_A, "pa-b")
        self.providers.spaces_error = TimeoutError("private")
        self.assert_code("PROVIDER_UNAVAILABLE", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.assertTrue(all(r["access"] == "unknown" for r in self.selections.snapshots[(TENANT_A["tenantId"], "pa-a")]))
        self.assertTrue(all(r["access"] == "available" for r in self.selections.snapshots[(TENANT_A["tenantId"], "pa-b")]))

    def test_old_space_observation_is_never_saved_as_current_access(self):
        self.providers.space_payload["items"][0]["checkedAt"] = normalize.iso(NOW - timedelta(hours=1))
        self.service.list_spaces(TENANT_A, "pa-a")
        self.assertEqual(self.selections.snapshots[(TENANT_A["tenantId"], "pa-a")][0]["access"], "unknown")

    def test_invalid_authorization_payload_becomes_a_safe_error(self):
        self.providers.accounts[(TENANT_A["tenantId"], "pa-a")]["authorization"] = None
        self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.list_spaces(TENANT_A, "pa-a"))

    def test_malformed_json_types_fail_with_controlled_errors(self):
        for value in ([], {}, None, True):
            self.providers.space_payload["items"][0]["kind"] = value
            self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.list_spaces(TENANT_A, "pa-a"))
        self.providers.space_payload["items"][0]["kind"] = "personal"
        for value in ([], {}, None, True):
            self.providers.quota_payload = {**known_quota(), "state": value}
            self.assert_code("PROVIDER_RESPONSE_INVALID", lambda: self.service.quota(TENANT_A, "pa-a", "personal"))


class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.routes = {}
        class Router:
            def add(inner, method, pattern, handler):
                self.routes[(method, pattern)] = handler
        self.router = Router()
        self.service = SpaceService(Providers(), Selections(), clock=lambda: NOW)
        register_routes(self.router, {"spaces": self.service})

    def test_requires_site_session_and_redacts_error(self):
        handler = self.routes[("GET", "/api/v1/provider-accounts/{id}/spaces")]
        result = handler({}, {"id": "pa-a"})
        self.assertEqual(result.status, 401)
        self.assertEqual(result.body["error"]["details"], {})
        self.assertEqual(result.headers["Cache-Control"], "no-store")

    def test_unwired_service_is_501(self):
        register_routes(self.router, {})
        result = self.routes[("GET", "/api/v1/provider-accounts/{id}/spaces")](TENANT_A, {"id": "pa-a"})
        self.assertEqual(result.status, 501)

    def test_csrf_is_required_for_selection(self):
        result = self.routes[("PUT", "/api/v1/selection")]({**TENANT_A, "csrfVerified": False}, {})
        self.assertEqual(result.status, 403)

    def test_selection_rejects_client_tenant_and_requires_explicit_space(self):
        for body in ({"providerAccountId": "pa-a", "expectedRevision": 0},
                     {"providerAccountId": "pa-a", "spaceId": None, "expectedRevision": 0, "tenantId": "other"}):
            result = self.routes[("PUT", "/api/v1/selection")]({**TENANT_A, "json": body}, {})
            self.assertEqual(result.status, 422)

    def test_success_envelope_and_attribute_context(self):
        class Context:
            tenantId = TENANT_A["tenantId"]
            requestId = "attribute-context"
        # Account providers receive context unchanged; use a wrapper accepting it.
        original = self.service.providers.get_account
        self.service.providers.get_account = lambda ctx, aid: original({"tenantId": ctx.tenantId}, aid)
        original_client = self.service.providers.client_for
        self.service.providers.client_for = lambda ctx, owner: original_client({"tenantId": ctx.tenantId}, owner)
        original_account_client = self.service.providers.account_client_for
        self.service.providers.account_client_for = lambda ctx, owner: original_account_client({"tenantId": ctx.tenantId}, owner)
        self.service.selections = None
        result = self.routes[("GET", "/api/v1/provider-accounts/{id}/spaces")](Context(), {"id": "pa-a"})
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body["meta"], {"requestId": "attribute-context", "apiVersion": 1})
        self.assertEqual(len(result.body["data"]["items"]), 2)


class OfficialPublicFormatTests(unittest.TestCase):
    """Actual anonymous captures, intentionally distinct from the above fakes."""
    def fixture(self, name):
        return json.loads((Path(__file__).parent / "fixtures" / (name + ".json")).read_text())

    def test_current_public_discovery_and_scope_are_account_read_only_evidence(self):
        protected = self.fixture("protected-resource")
        metadata = self.fixture("authorization-server")
        self.assertEqual(protected["status"], 200)
        self.assertEqual(protected["body"]["resource"], normalize.OFFICIAL_RESOURCE)
        self.assertEqual(metadata["body"]["issuer"], normalize.OFFICIAL_ISSUER)
        self.assertIn("libtv:account:read", metadata["body"]["scopes_supported"])
        self.assertIn("S256", metadata["body"]["code_challenge_methods_supported"])
        with self.assertRaises(SpaceError):
            normalize.identity(metadata["body"])
        with self.assertRaises(SpaceError):
            normalize.spaces(metadata["body"], NOW)
        unknown = normalize.quota(metadata["body"], "pa-a", "personal", NOW)
        self.assertEqual(unknown["state"], "unknown")
        self.assertIsNone(unknown["remaining"])

    def test_actual_mcp_401_is_not_success_or_zero_quota(self):
        result = self.fixture("unauthorized-mcp")
        self.assertEqual(result["status"], 401)
        self.assertIn("Bearer", result["headers"]["www-authenticate"])
        self.assertEqual(result["body"]["error"], "invalid_token")
        with self.assertRaises(SpaceError):
            normalize.identity(result["body"])
        with self.assertRaises(SpaceError):
            normalize.spaces(result["body"], NOW)
        with self.assertRaises(SpaceError):
            normalize.quota(result["body"], "pa-a", "personal", NOW)

    def test_service_docs_do_not_claim_balance_or_identity_support(self):
        docs = self.fixture("service-docs")
        self.assertEqual(docs["body"]["service"], "libtv-remote-mcp-gateway")
        self.assertEqual(docs["body"]["authorization"]["type"], "oauth2.1_authorization_code_pkce")
        self.assertNotIn("userinfo_endpoint", self.fixture("authorization-server")["body"])
        self.assertNotIn("balance", docs["body"]["endpoints"])


if __name__ == "__main__":
    unittest.main()
