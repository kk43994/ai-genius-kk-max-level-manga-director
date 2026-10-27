"""Runs after storage module is present; never copies or edits that module."""
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import secrets
import tempfile
import unittest

from backend.auth import ProviderService, AuthError
from backend.auth.secrets import AesGcmSecretCodec
from backend.auth.storage_adapter import StorageAuthRepository
from backend.providers.libtv_oauth import LibTVOAuth, OAuthConfig
from helpers import Clock, FakeHTTP, IdentityFixture, callback_for

try:
    from backend.storage import AccountRepository, SelectionRepository, Store
    from backend.sessions.service import SessionService
except ModuleNotFoundError:
    Store = None


@unittest.skipIf(Store is None, 'Storage module is delivered by session 3; run again after integration.')
class StorageBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock, self.http, self.verifier = Clock(), FakeHTTP(), IdentityFixture()
        self.key = secrets.token_bytes(32)
        self.data_dir = Path(self.tmp.name).resolve() / 'data'
        self.store = Store(self.data_dir, encryption_key=self.key, clock=self.clock)
        self.session = SessionService(self.store, public_origin='https://website.example').create()
        self.ctx = dict(asdict(self.session.context), csrfVerified=True)
        self.repo = StorageAuthRepository(self.store)
        self.codec = AesGcmSecretCodec({'test': self.key}, 'test')
        self.oauth = LibTVOAuth(OAuthConfig('https://website.example/api/v1/oauth/libtv/callback'), self.http)
        self.service = ProviderService(self.repo, self.codec, self.oauth, identity_verifier=self.verifier, clock=self.clock)

    def connect(self):
        attempt = self.service.begin_authorization(self.ctx)
        self.service.complete_authorization(self.ctx, callback_for(attempt))
        result = self.service.get_attempt(self.ctx, attempt['attemptId'])
        self.assertEqual('completed', result['status'], result)
        return self.service.get_account(self.ctx, result['providerAccountId'])

    def test_account_is_immediately_visible_to_selection_repository(self):
        account = self.connect()
        self.assertEqual(account['identity'], AccountRepository(self.store).get(self.ctx, account['id'])['identity'])
        selections = SelectionRepository(self.store)
        selections.replace_spaces(self.ctx, account['id'], [{'id': 'synthetic-personal', 'kind': 'personal', 'name': '合成个人空间', 'access': 'available'}])
        selected = selections.set(self.ctx, account['id'], 'synthetic-personal', expected_revision=0)
        self.assertEqual(account['id'], selected['providerAccountId'])
        with self.store.transaction(self.ctx) as tx:
            owner = selections.bind_ownership(tx, expected_revision=1)
            task = tx.create('tasks', {'ownership': owner, 'status': 'draft'}, record_id='task_synthetic')
        result = self.service.remove_account(self.ctx, account['id'], account['version'])
        self.assertEqual(['task_synthetic'], result['affectedTaskIds'])
        self.assertIsNone(selections.get(self.ctx)['providerAccountId'])
        self.assertEqual(owner, self.store.get(self.ctx, 'tasks', task['id'])['data']['ownership'])

    def test_callback_and_grant_survive_store_restart(self):
        attempt = self.service.begin_authorization(self.ctx)
        new_store = Store(self.data_dir, encryption_key=self.key, clock=self.clock)
        service = ProviderService(StorageAuthRepository(new_store), self.codec, self.oauth,
                                  identity_verifier=self.verifier, clock=self.clock)
        service.complete_authorization(self.ctx, callback_for(attempt))
        self.assertEqual('completed', service.get_attempt(self.ctx, attempt['attemptId'])['status'])
        for path in self.data_dir.glob('state.sqlite3*'):
            raw = path.read_bytes()
            self.assertNotIn(b'synthetic-access-1', raw)
            self.assertNotIn(b'synthetic-refresh-1', raw)
            self.assertNotIn(b'test-code', raw)

    def test_failed_atomic_commit_leaves_neither_account_nor_grant(self):
        class FailOnce(StorageAuthRepository):
            failed = False
            @contextmanager
            def transaction(self, ctx):
                with super().transaction(ctx) as state:
                    yield state
                    if state.get('accounts') and not self.failed:
                        self.failed = True
                        raise RuntimeError('synthetic interrupted commit')
        self.service.repository = FailOnce(self.store)
        attempt = self.service.begin_authorization(self.ctx)
        self.service.complete_authorization(self.ctx, callback_for(attempt))
        self.assertEqual('failed', self.service.get_attempt(self.ctx, attempt['attemptId'])['status'])
        self.assertEqual([], AccountRepository(self.store).list(self.ctx)['items'])
        self.assertEqual(2, len([c for c in self.http.calls if c[1].endswith('/revoke')]))

    def test_external_local_remove_cannot_leave_stale_usable_auth_copy(self):
        account = self.connect()
        AccountRepository(self.store).remove_local(self.ctx, account['id'], expected_version=account['version'])
        owner = {'tenantId': self.ctx['tenantId'], 'provider': 'libtv', 'providerAccountId': account['id'],
                 'providerSubject': account['identity']['subject']}
        with self.assertRaises(AuthError):
            self.service.account_client_for(self.ctx, owner)


if __name__ == '__main__':
    unittest.main()
