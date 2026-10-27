"""Runs once module 3 storage/sessions are installed alongside module 4.

Only synthetic identities/grants and temporary SQLite databases are used.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from backend.spaces import SpaceError, SpaceService
from backend.spaces.normalize import OFFICIAL_ISSUER

try:
    from backend.storage import Store, AccountRepository, SelectionRepository, VerifiedIdentity, StorageError
    from backend.sessions import SessionService
except ModuleNotFoundError as error:
    if error.name not in {"backend.storage", "backend.sessions", "cryptography"}:
        raise
    Store = None


class PersistedProvider:
    def __init__(self, accounts):
        self.accounts = accounts
        self.fail_reads = False

    def get_account(self, ctx, account_id):
        return self.accounts.get(ctx, account_id)

    def client_for(self, ctx, owner):
        assert owner["spaceId"]
        return self._bound(ctx, owner)

    def account_client_for(self, ctx, owner):
        assert owner["spaceId"] is None
        return self._bound(ctx, owner)

    def _bound(self, ctx, owner):
        account = self.accounts.get(ctx, owner["providerAccountId"])
        assert owner["tenantId"] == ctx.tenantId
        assert owner["providerSubject"] == account["identity"]["subject"]
        provider = self

        class Client:
            def identity(self):
                return deepcopy(account["identity"])

            def list_spaces(self):
                if provider.fail_reads:
                    raise TimeoutError("synthetic upstream failure")
                return {"items": [
                    {"id": "same-personal-id", "kind": "personal", "name": "合成个人空间", "access": "available"},
                    {"id": "same-team-id", "kind": "team", "name": "合成团队空间", "access": "available"},
                ], "nextCursor": None}
        return Client()


@unittest.skipIf(Store is None, "requires module 3 storage/sessions and its cryptography dependency")
class PersistentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="asset-lab-spaces-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = 1793088000.0
        self.key = bytes(range(32))
        self.store = Store(self.root / "data", encryption_key=self.key,
                           release_root=self.root / "release", clock=lambda: self.now)
        self.sessions = SessionService(self.store, public_origin="https://example.invalid")
        self.session_a, self.session_b = self.sessions.create(), self.sessions.create()
        self.ctx, self.other_ctx = self.session_a.context, self.session_b.context
        self.accounts = AccountRepository(self.store)
        self.selections = SelectionRepository(self.store)
        self.providers = PersistedProvider(self.accounts)
        self.service = SpaceService(self.providers, self.selections,
                                    clock=lambda: datetime.fromtimestamp(self.now, timezone.utc))
        self.a = self.add_account(self.ctx, "synthetic-subject-a")
        self.b = self.add_account(self.ctx, "synthetic-subject-b")
        self.c = self.add_account(self.other_ctx, "synthetic-subject-a")

    def add_account(self, ctx, subject):
        epoch_at_begin = self.accounts.authorization_epoch(ctx)
        return self.accounts.complete_authorization(ctx, VerifiedIdentity(OFFICIAL_ISSUER, subject),
            {"access_token": "synthetic-not-a-real-provider-token"}, minimum_read_verified=True,
            expected_authorization_epoch=epoch_at_begin)["id"]

    def test_restart_and_same_cookie_restore_the_persisted_selection(self):
        self.service.set_selection(self.ctx, providerAccountId=self.a, spaceId="same-team-id", expectedRevision=0)
        reopened = Store(self.root / "data", encryption_key=self.key,
                         release_root=self.root / "next-release", clock=lambda: self.now)
        resumed = SessionService(reopened, public_origin="https://example.invalid").bootstrap(self.session_a.set_cookie)
        self.assertEqual(resumed.context.tenantId, self.ctx.tenantId)
        self.assertEqual(resumed.data["selection"], {"providerAccountId": self.a, "spaceId": "same-team-id", "revision": 1})

    def test_task_owner_survives_account_and_space_switch_in_real_sqlite(self):
        self.service.set_selection(self.ctx, providerAccountId=self.a, spaceId="same-personal-id", expectedRevision=0)
        with self.store.transaction(self.ctx) as tx:
            owner = self.selections.bind_ownership(tx, expected_revision=1)
            task = tx.create("tasks", {"ownership": owner, "status": "draft"})
        self.service.set_selection(self.ctx, providerAccountId=self.b, spaceId="same-team-id", expectedRevision=1)
        saved = self.store.get(self.ctx, "tasks", task["id"])
        self.assertEqual(saved["data"]["ownership"], owner)
        self.assertEqual(self.selections.assert_ownership_available(self.ctx, owner)["id"], self.a)
        self.assertEqual(self.service.get_selection(self.ctx)["providerAccountId"], self.b)

    def test_same_space_id_and_same_provider_subject_do_not_share_tenant_state(self):
        self.service.set_selection(self.ctx, providerAccountId=self.a, spaceId="same-personal-id", expectedRevision=0)
        self.service.set_selection(self.other_ctx, providerAccountId=self.c, spaceId="same-team-id", expectedRevision=0)
        self.assertEqual(self.service.get_selection(self.ctx)["spaceId"], "same-personal-id")
        self.assertEqual(self.service.get_selection(self.other_ctx)["spaceId"], "same-team-id")
        with self.assertRaises(SpaceError) as error:
            self.service.list_spaces(self.other_ctx, self.a)
        self.assertEqual(error.exception.code, "NOT_FOUND")

    def test_failed_official_read_invalidates_space_before_new_task_binding(self):
        self.service.set_selection(self.ctx, providerAccountId=self.a, spaceId="same-personal-id", expectedRevision=0)
        self.providers.fail_reads = True
        with self.assertRaises(SpaceError):
            self.service.list_spaces(self.ctx, self.a)
        with self.store.transaction(self.ctx) as tx:
            with self.assertRaises(StorageError) as error:
                self.selections.bind_ownership(tx, expected_revision=1)
        self.assertEqual(error.exception.code, "SPACE_UNAVAILABLE")
        self.assertEqual(self.service.get_selection(self.ctx)["providerAccountId"], self.a)

    def test_remove_account_keeps_task_owner_but_prevents_further_reads(self):
        self.service.set_selection(self.ctx, providerAccountId=self.a, spaceId="same-personal-id", expectedRevision=0)
        with self.store.transaction(self.ctx) as tx:
            owner = self.selections.bind_ownership(tx, expected_revision=1)
            task = tx.create("tasks", {"ownership": owner, "status": "draft"})
        self.accounts.remove_local(self.ctx, self.a, expected_version=self.accounts.get(self.ctx, self.a)["version"])
        self.assertEqual(self.store.get(self.ctx, "tasks", task["id"])["data"]["ownership"], owner)
        with self.assertRaises(SpaceError) as error:
            self.service.list_spaces(self.ctx, self.a)
        self.assertEqual(error.exception.code, "NOT_FOUND")

    def test_persistent_cas_conflict_preserves_winning_selection(self):
        self.service.set_selection(self.ctx, providerAccountId=self.a, spaceId="same-personal-id", expectedRevision=0)
        with self.assertRaises(SpaceError) as error:
            self.service.set_selection(self.ctx, providerAccountId=self.b, spaceId="same-team-id", expectedRevision=0)
        self.assertEqual(error.exception.code, "SELECTION_CHANGED")
        self.assertEqual(self.service.get_selection(self.ctx)["providerAccountId"], self.a)


if __name__ == "__main__":
    unittest.main()
