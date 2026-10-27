"""Replay the audited module 2 identity contract using synthetic values only.

No authenticated capture, token file, real HTTP transport or upstream call is
used here. These tests run when the updated module 2 provider is installed.
"""
import json
from pathlib import Path
import unittest

from backend.spaces import normalize

try:
    from backend.auth.errors import AuthError
    from backend.providers import libtv_identity
    from backend.providers.libtv_oauth import HTTPResult, RESOURCE
    LIBTV_ACCOUNT_IDENTITY = getattr(libtv_identity, "LIBTV_ACCOUNT_IDENTITY", None)
    ReadOnlyMCPIdentityVerifier = libtv_identity.ReadOnlyMCPIdentityVerifier
except ModuleNotFoundError as error:
    if error.name not in {"backend.auth", "backend.providers", "cryptography"}:
        raise
    LIBTV_ACCOUNT_IDENTITY = None


class IdentityTransport:
    def __init__(self, payload, *, structured=True):
        self.payload, self.structured, self.calls = payload, structured, []

    def request(self, method, url, *, data=None, headers=None):
        if method != "POST" or url != RESOURCE:
            raise AssertionError("Only the injected offline MCP transport is permitted")
        rpc = json.loads(data)
        self.calls.append(rpc)
        if rpc["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {},
                      "serverInfo": {"name": "synthetic-libTV", "version": "1"}}
        elif rpc["method"] == "notifications/initialized":
            return HTTPResult(202, {})
        elif rpc["method"] == "tools/list":
            fixture = Path(__file__).parent / "fixtures" / "libtv-account-user-tool.public.json"
            result = {"tools": [json.loads(fixture.read_text())["tool"]]}
        elif rpc["method"] == "tools/call" and rpc["params"] == {"name": "account_user", "arguments": {}}:
            result = ({"structuredContent": self.payload} if self.structured else
                      {"content": [{"type": "text", "text": json.dumps(self.payload)}]})
        else:
            raise AssertionError("Unexpected operation; no write or generation tools are allowed")
        return HTTPResult(200, {"jsonrpc": "2.0", "id": rpc["id"], "result": result})


@unittest.skipIf(LIBTV_ACCOUNT_IDENTITY is None, "requires module 2 audited account_user identity contract")
class OfficialIdentityContractTests(unittest.TestCase):
    def verify(self, payload, **kwargs):
        transport = IdentityTransport(payload, **kwargs)
        verified = ReadOnlyMCPIdentityVerifier(transport, LIBTV_ACCOUNT_IDENTITY).verify(
            {"access_token": "synthetic-not-a-real-token"})
        public = normalize.identity({"issuer": verified.issuer, "subject": verified.subject,
                                     "displayName": verified.display_name,
                                     "verified": verified.minimal_read_verified})
        return public, transport.calls

    def test_audited_paths_are_uuid_and_nickname(self):
        self.assertEqual(LIBTV_ACCOUNT_IDENTITY.tool_name, "account_user")
        self.assertEqual(LIBTV_ACCOUNT_IDENTITY.subject_path, ("user", "uuid"))
        self.assertEqual(LIBTV_ACCOUNT_IDENTITY.display_name_path, ("user", "nickname"))

    def test_subject_and_display_name_are_accepted_by_space_identity_normalizer(self):
        public, calls = self.verify({"user": {"uuid": "synthetic-user-a", "nickname": "合成昵称"}})
        self.assertEqual(public["subject"], "synthetic-user-a")
        self.assertEqual(public["displayName"], "合成昵称")
        self.assertEqual([r["params"]["name"] for r in calls if r["method"] == "tools/call"], ["account_user"])

    def test_text_envelope_and_structured_envelope_have_same_projection(self):
        payload = {"user": {"uuid": "synthetic-user-a", "nickname": "合成昵称"}}
        self.assertEqual(self.verify(payload)[0], self.verify(payload, structured=False)[0])

    def test_changing_nickname_does_not_create_a_new_subject(self):
        first, _ = self.verify({"user": {"uuid": "synthetic-user-a", "nickname": "合成昵称一"}})
        second, _ = self.verify({"user": {"uuid": "synthetic-user-a", "nickname": "合成昵称二"}})
        self.assertEqual(first["subject"], second["subject"])
        self.assertNotEqual(first["displayName"], second["displayName"])

    def test_account_or_membership_values_never_replace_missing_user_uuid(self):
        for user in ({"nickname": "合成昵称"}, {"uuid": 123}, {"uuid": ""}):
            with self.subTest(user=user), self.assertRaises(AuthError):
                self.verify({"user": user, "activeAccount": {"accountId": "synthetic-team"},
                             "membership": {"credits": 5000}})


if __name__ == "__main__":
    unittest.main()
