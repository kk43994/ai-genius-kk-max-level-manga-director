"""Real storage/recovery integration; only official OAuth provider is synthetic."""
from dataclasses import asdict
from urllib.parse import parse_qs, urlsplit
import json
import unittest

from backend.auth.errors import AuthError
from backend.auth.routes import register_routes
from backend.auth.service import binding
from helpers import callback_for
import test_storage_bridge as storage_bridge

try:
    from backend.sessions import WorkspaceRecoveryService, SessionService
    from backend.storage.errors import StorageError
except ModuleNotFoundError:
    WorkspaceRecoveryService = None


@unittest.skipIf(WorkspaceRecoveryService is None, 'Session 3 owner recovery module required.')
class OwnerRecoveryTests(unittest.TestCase):
    def setUp(self):
        storage_bridge.StorageBridgeTests.setUp(self)
        self.sessions = SessionService(self.store, public_origin='https://website.example')
        self.recovery = WorkspaceRecoveryService(self.store, self.sessions)
        self.service.workspace_recovery = self.recovery
        self.ctx = self.ctx_for(self.session)

    def ctx_for(self, session):
        return dict(asdict(session.context), csrfVerified=True,
                    headers={'Origin': 'https://website.example', 'X-CSRF-Token': session.data['csrfToken']})

    def authorize(self, purpose, *, dirty=False):
        attempt = self.service.begin_authorization(self.ctx, purpose=purpose, hasUnsavedChanges=dirty)
        response = self.service.complete_authorization(self.ctx, callback_for(attempt))
        result = parse_qs(urlsplit(response['headers']['Location']).query)
        return attempt, response, result

    def accept_cookie(self, response):
        session = self.sessions.bootstrap(response['headers']['Set-Cookie'])
        self.ctx = self.ctx_for(session)
        return session

    def bind(self):
        attempt, response, result = self.authorize('bind_owner')
        self.assertEqual(['bound'], result['workspaceStatus'])
        return self.accept_cookie(response)

    def test_normal_add_does_not_bind_workspace_owner(self):
        account = storage_bridge.StorageBridgeTests.connect(self)
        self.assertFalse(self.recovery.repo.get(self.ctx)['ownerBound'])
        self.assertEqual('connected', account['authorization']['state'])

    def test_fresh_owner_proof_rotates_cookie_and_creates_no_generation_grant(self):
        old_ctx = dict(self.ctx)
        attempt, response, result = self.authorize('bind_owner')
        self.assertEqual(['bound'], result['workspaceStatus'])
        self.assertIn('Set-Cookie', response['headers'])
        self.assertNotIn('nonce', json.dumps(attempt))
        with self.assertRaises(StorageError):
            self.store.get(old_ctx, 'projects', 'not_existing')
        self.accept_cookie(response)
        self.assertTrue(self.recovery.repo.get(self.ctx)['ownerBound'])
        self.assertEqual([], self.service.list_accounts(self.ctx)['items'])
        self.assertEqual(2, len([c for c in self.http.calls if c[1].endswith('/revoke')]))

    def test_cookie_loss_recovery_returns_original_workspace_without_merging(self):
        self.store.create(self.ctx, 'projects', {'title': 'synthetic original'}, record_id='project_original')
        old_tenant = self.ctx['tenantId']
        self.bind()
        self.ctx = self.ctx_for(self.sessions.create())
        new_tenant = self.ctx['tenantId']
        _, response, result = self.authorize('recover_workspace')
        self.assertEqual(['recovered'], result['workspaceStatus'])
        self.accept_cookie(response)
        self.assertEqual(old_tenant, self.ctx['tenantId'])
        self.assertNotEqual(new_tenant, old_tenant)
        self.assertEqual('synthetic original', self.store.get(self.ctx, 'projects', 'project_original')['data']['title'])
        self.assertEqual([], self.service.list_accounts(self.ctx)['items'])

    def test_new_workspace_content_requires_confirmation_and_preservation(self):
        old_tenant = self.ctx['tenantId']
        self.bind()
        self.ctx = self.ctx_for(self.sessions.create())
        source_tenant = self.ctx['tenantId']
        self.store.create(self.ctx, 'projects', {'title': 'synthetic new draft'}, record_id='project_new')
        attempt, response, result = self.authorize('recover_workspace')
        self.assertEqual(['awaiting_confirmation'], result['workspaceStatus'])
        self.assertNotIn('Set-Cookie', response['headers'])
        intent = self.recovery.get_intent(self.ctx, attempt['workspaceIntent']['intentId'])
        self.assertEqual([old_tenant], [c['id'] for c in intent['candidates']])
        confirmed = self.recovery.confirm(self.ctx, intent['id'], action='recover_preserve_current',
            workspace_id=old_tenant, expected_version=intent['version'],
            expected_content_revision=intent['sourceWorkspace']['content']['revision'], draft_disposition='none')
        self.assertEqual('recovered', confirmed.data['status'])
        self.assertTrue(confirmed.data['sourceWorkspacePreserved'])
        self.ctx = self.ctx_for(confirmed.session)
        self.assertEqual(old_tenant, self.ctx['tenantId'])
        with self.store._system_transaction(write=False) as conn:
            row = conn.execute("SELECT tenant_id FROM records WHERE id='project_new'").fetchone()
            self.assertEqual(source_tenant, row[0])

    def test_wrong_user_cannot_recover_workspace(self):
        self.bind()
        self.ctx = self.ctx_for(self.sessions.create())
        self.verifier.subject = 'synthetic-other-owner'
        _, response, result = self.authorize('recover_workspace')
        self.assertEqual(['not_found'], result['workspaceStatus'])
        self.assertNotIn('Set-Cookie', response['headers'])
        self.assertFalse(self.recovery.repo.get(self.ctx)['ownerBound'])

    def test_cancel_consumes_both_oauth_and_owner_intent(self):
        attempt = self.service.begin_authorization(self.ctx, purpose='bind_owner', hasUnsavedChanges=False)
        self.service.cancel_authorization(self.ctx, attempt['attemptId'])
        self.assertEqual('cancelled', self.recovery.get_intent(self.ctx, attempt['workspaceIntent']['intentId'])['status'])
        with self.assertRaises(AuthError):
            self.service.complete_authorization(self.ctx, callback_for(attempt))
        self.assertFalse(self.recovery.repo.get(self.ctx)['ownerBound'])

    def test_tampered_private_owner_nonce_cannot_bind(self):
        attempt = self.service.begin_authorization(self.ctx, purpose='bind_owner', hasUnsavedChanges=False)
        with self.repo.transaction(self.ctx) as state:
            row = state['attempts'][attempt['attemptId']]
            aad = binding(self.ctx['tenantId'], 'attempt', row['id'])
            private = self.codec.open(row['private'], binding=aad)
            private['ownerIntent']['nonce'] = 'x' * 43
            row['private'] = self.codec.seal(private, binding=aad)
        response = self.service.complete_authorization(self.ctx, callback_for(attempt))
        self.assertEqual(['failed'], parse_qs(urlsplit(response['headers']['Location']).query)['workspaceStatus'])
        self.assertFalse(self.recovery.repo.get(self.ctx)['ownerBound'])
        self.assertNotIn('Set-Cookie', response['headers'])

    def test_owner_begin_requires_actual_csrf_headers_and_disallows_browser_identity(self):
        ctx = dict(self.ctx, headers={})
        with self.assertRaises(StorageError):
            self.service.begin_authorization(ctx, purpose='bind_owner')
        class Router:
            def add(self, method, path, handler):
                if method == 'POST' and path.endswith('/authorize'):
                    self.authorize = handler
        router = Router()
        register_routes(router, {'providers': self.service})
        bad = dict(self.ctx, json={'purpose': 'recover_workspace', 'subject': 'forged'})
        self.assertEqual(422, router.authorize(bad, {}).status)

    def test_changed_callback_purpose_cannot_turn_add_into_recovery(self):
        attempt = self.service.begin_authorization(self.ctx)
        self.service.complete_authorization(self.ctx, dict(callback_for(attempt), purpose='bind_owner', subject='forged'))
        self.assertFalse(self.recovery.repo.get(self.ctx)['ownerBound'])
        self.assertEqual(1, len(self.service.list_accounts(self.ctx)['items']))

    def test_unknown_unsaved_drafts_never_silently_rotate_workspace(self):
        attempt, response, result = self.authorize('bind_owner', dirty=None)
        self.assertEqual(['awaiting_confirmation'], result['workspaceStatus'])
        self.assertNotIn('Set-Cookie', response['headers'])
        self.assertFalse(self.recovery.repo.get(self.ctx)['ownerBound'])

    def test_failed_attempt_persistence_cancels_owner_intent(self):
        original = self.service.codec
        class FailingCodec:
            def open(self, *args, **kwargs): return original.open(*args, **kwargs)
            def seal(self, value, **kwargs):
                if 'ownerIntent' in value:
                    raise AuthError('SECRET_STORAGE_UNAVAILABLE')
                return original.seal(value, **kwargs)
        self.service.codec = FailingCodec()
        with self.assertRaises(AuthError):
            self.service.begin_authorization(self.ctx, purpose='bind_owner', hasUnsavedChanges=False)
        with self.store._system_transaction(write=False) as conn:
            rows = conn.execute('SELECT status FROM workspace_intents WHERE tenant_id=?', (self.ctx['tenantId'],)).fetchall()
        self.assertEqual(['cancelled'], [row[0] for row in rows])

    def test_revocation_outage_does_not_lose_rotated_session(self):
        def unavailable(*args): raise RuntimeError('synthetic transport outage')
        self.service.oauth.revoke = unavailable
        _, response, result = self.authorize('bind_owner')
        self.assertEqual(['bound'], result['workspaceStatus'])
        self.accept_cookie(response)
        self.assertTrue(self.recovery.repo.get(self.ctx)['ownerBound'])
        self.assertEqual([], self.service.list_accounts(self.ctx)['items'])


if __name__ == '__main__':
    unittest.main()
