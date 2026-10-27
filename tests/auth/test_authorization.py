import base64
import copy
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

from backend.auth import AuthError, ProviderService, ProviderWorkerContext
from backend.auth.routes import register_routes
from backend.auth.secrets import AesGcmSecretCodec
from backend.auth.service import binding
from backend.providers.libtv_identity import UnavailableIdentityVerifier, VerifiedIdentity
from backend.providers.libtv_oauth import (ClientRegistration, HTTPResult, ISSUER, RESOURCE,
                                         LibTVOAuth, OAuthConfig, pkce_challenge)
from helpers import Clock, FakeHTTP, IdentityFixture, SqliteTestRepository, callback_for, context


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        self.repo = SqliteTestRepository(self.path)
        self.codec = AesGcmSecretCodec({'test': secrets.token_bytes(32)}, 'test')
        self.clock, self.http, self.identity = Clock(), FakeHTTP(), IdentityFixture()
        self.oauth = LibTVOAuth(OAuthConfig('https://website.example/api/v1/oauth/libtv/callback'), self.http)
        self.service = self.new_service()
        self.ctx = context()

    def new_service(self):
        return ProviderService(SqliteTestRepository(self.path), self.codec, self.oauth,
                               identity_verifier=self.identity, clock=self.clock)

    def begin(self, **kwargs):
        return self.service.begin_authorization(self.ctx, **kwargs)

    def complete(self, attempt=None, **kwargs):
        attempt = attempt or self.begin()
        response = self.service.complete_authorization(self.ctx, callback_for(attempt, **kwargs))
        self.assertEqual(303, response['status'])
        return self.service.get_attempt(self.ctx, attempt['attemptId'])

    def connect(self):
        result = self.complete()
        self.assertEqual('completed', result['status'], result)
        return self.service.get_account(self.ctx, result['providerAccountId'])

    def owner(self, account):
        return {'tenantId': self.ctx['tenantId'], 'provider': 'libtv', 'providerAccountId': account['id'],
                'providerSubject': account['identity']['subject'], 'spaceId': 'synthetic-space'}

    def assertCode(self, code, operation):
        with self.assertRaises(AuthError) as caught:
            operation()
        self.assertEqual(code, caught.exception.code)

    def test_begin_uses_s256_resource_and_exact_registered_redirect(self):
        attempt = self.begin()
        query = parse_qs(urlsplit(attempt['authorizationUrl']).query)
        self.assertEqual(['S256'], query['code_challenge_method'])
        self.assertEqual([RESOURCE], query['resource'])
        self.assertEqual([self.oauth.config.redirect_uri], query['redirect_uri'])
        self.assertEqual(['libtv:account:read'], query['scope'])
        with self.repo.transaction(self.ctx) as state:
            row = state['attempts'][attempt['attemptId']]
            self.assertNotIn(query['state'][0], json.dumps(state))
            secret = self.codec.open(row['private'], binding=binding('tenant_a', 'attempt', row['id']))
            self.assertEqual(query['code_challenge'][0], pkce_challenge(secret['verifier']))
            self.assertGreaterEqual(len(secret['verifier']), 43)
            self.assertLessEqual(len(secret['verifier']), 128)

    def test_pkce_rfc7636_vector(self):
        self.assertEqual('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
            pkce_challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'))

    def test_callback_completes_after_server_restart_without_plaintext_secrets(self):
        attempt = self.begin()
        self.service = self.new_service()
        result = self.complete(attempt)
        self.assertEqual('completed', result['status'])
        public = json.dumps(self.service.list_accounts(self.ctx))
        on_disk = self.path.read_bytes()
        for value in ('synthetic-access-1', 'synthetic-refresh-1', 'test-code'):
            self.assertNotIn(value, public)
            self.assertNotIn(value.encode(), on_disk)
        token_request = next(c for c in self.http.calls if c[1].endswith('/token'))
        form = parse_qs(token_request[2].decode())
        self.assertEqual([RESOURCE], form['resource'])
        self.assertEqual([self.oauth.config.redirect_uri], form['redirect_uri'])
        self.assertIn('code_verifier', form)

    def test_replay_after_restart_never_exchanges_twice(self):
        attempt = self.begin()
        self.complete(attempt)
        self.service = self.new_service()
        self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.service.complete_authorization(self.ctx, callback_for(attempt)))
        self.assertEqual(1, self.http.token_counter)

    def test_foreign_tenant_cannot_consume_callback_or_read_attempt(self):
        attempt = self.begin()
        foreign = context('tenant_b', 'session_b')
        self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.service.complete_authorization(foreign, callback_for(attempt)))
        self.assertCode('NOT_FOUND', lambda: self.service.get_attempt(foreign, attempt['attemptId']))
        self.assertEqual('completed', self.complete(attempt)['status'])

    def test_same_tenant_wrong_session_does_not_consume_state(self):
        attempt = self.begin()
        self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.service.complete_authorization(context(session='session_other'), callback_for(attempt)))
        self.assertEqual('completed', self.complete(attempt)['status'])

    def test_missing_session_is_rejected(self):
        self.assertCode('SESSION_REQUIRED', lambda: self.service.begin_authorization({'tenantId': 'tenant_a'}))

    def test_mutation_requires_csrf_verified_by_http_adapter(self):
        self.assertCode('CSRF_FAILED', lambda: self.service.begin_authorization(dict(self.ctx, csrfVerified=False)))

    def test_duplicate_callback_fields_and_error_plus_code_rejected(self):
        attempt = self.begin()
        query = callback_for(attempt)
        for mutated in (dict(query, state=[query['state'], query['state']]), dict(query, error='access_denied'),
                        dict(query, code=['one', 'two']), dict(query, code='x\nsecret')):
            self.assertCode('AUTHORIZATION_STATE_INVALID', lambda q=mutated: self.service.complete_authorization(self.ctx, q))
        self.assertEqual(0, self.http.token_counter)

    def test_wrong_issuer_is_consumed_and_fails_without_token_exchange(self):
        attempt = self.begin()
        result = self.complete(attempt, iss='https://other.example/')
        self.assertEqual('AUTHORIZATION_STATE_INVALID', result['error']['code'])
        self.assertEqual(0, self.http.token_counter)

    def test_denied_consent_has_safe_error_and_no_token_call(self):
        attempt = self.begin()
        callback = callback_for(attempt)
        callback.pop('code')
        callback.update(error='access_denied', error_description='<script>secret</script>', error_uri='https://evil.invalid')
        response = self.service.complete_authorization(self.ctx, callback)
        result = self.service.get_attempt(self.ctx, attempt['attemptId'])
        self.assertEqual('AUTHORIZATION_DENIED', result['error']['code'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('state=', response['headers']['Location'])
        self.assertEqual(0, self.http.token_counter)

    def test_expired_attempt_cannot_exchange(self):
        attempt = self.begin()
        self.clock.now += 601
        result = self.service.get_attempt(self.ctx, attempt['attemptId'])
        self.assertEqual('expired', result['status'])
        self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.service.complete_authorization(self.ctx, callback_for(attempt)))
        self.assertEqual(0, self.http.token_counter)

    def test_cancel_is_idempotent_and_callback_fails(self):
        attempt = self.begin()
        result = self.service.cancel_authorization(self.ctx, attempt['attemptId'])
        self.assertEqual('AUTHORIZATION_CANCELLED', result['error']['code'])
        self.assertEqual(result, self.service.cancel_authorization(self.ctx, attempt['attemptId']))
        self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.service.complete_authorization(self.ctx, callback_for(attempt)))

    def test_reauthorization_wrong_identity_preserves_old_grant(self):
        account = self.connect()
        attempt = self.begin(providerAccountId=account['id'], expectedVersion=account['version'])
        self.identity.subject = 'synthetic-person-b'
        result = self.complete(attempt)
        self.assertEqual('PROVIDER_IDENTITY_MISMATCH', result['error']['code'])
        self.assertEqual(account, self.service.get_account(self.ctx, account['id']))
        self.assertEqual(2, len([c for c in self.http.calls if c[1].endswith('/revoke')]))

    def test_reauthorization_same_subject_retains_account_id(self):
        account = self.connect()
        result = self.complete(self.begin(providerAccountId=account['id'], expectedVersion=account['version']))
        self.assertEqual(account['id'], result['providerAccountId'])
        self.assertEqual(2, self.service.get_account(self.ctx, account['id'])['version'])

    def test_duplicate_identity_restores_tombstone_without_new_id(self):
        account = self.connect()
        self.service.remove_account(self.ctx, account['id'], account['version'])
        result = self.complete()
        self.assertEqual(account['id'], result['providerAccountId'])
        self.assertEqual(1, len(self.service.list_accounts(self.ctx)['items']))
        self.assertIsNone(self.service.get_account(self.ctx, account['id'])['removedAt'])

    def test_same_identity_in_two_tenants_is_not_shared(self):
        account_a = self.connect()
        self.ctx = context('tenant_b', 'session_b')
        account_b = self.connect()
        self.assertNotEqual(account_a['id'], account_b['id'])
        self.assertCode('NOT_FOUND', lambda: self.service.get_account(self.ctx, account_a['id']))

    def test_unverified_identity_never_marks_connected_and_revokes_grant(self):
        self.service.verifier = UnavailableIdentityVerifier()
        result = self.complete()
        self.assertEqual('PROVIDER_IDENTITY_UNAVAILABLE', result['error']['code'])
        self.assertEqual([], self.service.list_accounts(self.ctx)['items'])
        self.assertEqual(2, len([c for c in self.http.calls if c[1].endswith('/revoke')]))

    def test_invalid_jwt_subject_is_not_treated_as_identity(self):
        self.service.verifier = UnavailableIdentityVerifier()
        self.http.override[ISSUER + 'token'] = HTTPResult(200, {'access_token': 'header.eyJzdWIiOiJmYWtlIn0.signature',
            'token_type': 'Bearer', 'expires_in': 3600, 'id_token': 'unverified.jwt.token'})
        self.assertEqual('failed', self.complete()['status'])
        self.assertEqual([], self.service.list_accounts(self.ctx)['items'])

    def test_return_path_allowlist_blocks_open_redirects(self):
        for path in ('https://evil.example', '//evil.example', '/\\evil', '/?next=https://evil', '/%2f%2fevil'):
            self.assertCode('VALIDATION_FAILED', lambda p=path: self.begin(returnPath=p))

    def test_pending_limit(self):
        for _ in range(5):
            self.begin()
        self.assertCode('AUTHORIZATION_BUSY', self.begin)

    def test_token_timeout_fails_once_and_does_not_retry_on_callback(self):
        self.http.override[ISSUER + 'token'] = AuthError('PROVIDER_UNAVAILABLE')
        attempt = self.begin()
        self.assertEqual('PROVIDER_UNAVAILABLE', self.complete(attempt)['error']['code'])
        self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.service.complete_authorization(self.ctx, callback_for(attempt)))
        self.assertEqual(1, len([c for c in self.http.calls if c[1].endswith('/token')]))

    def test_concurrent_callback_only_one_token_exchange(self):
        attempt = self.begin()
        entered, resume = threading.Event(), threading.Event()
        self.http.before_token = lambda: (entered.set(), resume.wait(5))
        with ThreadPoolExecutor() as pool:
            future = pool.submit(self.service.complete_authorization, self.ctx, callback_for(attempt))
            self.assertTrue(entered.wait(3))
            self.assertCode('AUTHORIZATION_STATE_INVALID', lambda: self.new_service().complete_authorization(self.ctx, callback_for(attempt)))
            resume.set()
            self.assertEqual(303, future.result(5)['status'])
        self.assertEqual(1, self.http.token_counter)

    def test_cancel_during_exchange_cannot_commit_late_tokens(self):
        attempt = self.begin()
        entered, resume = threading.Event(), threading.Event()
        self.http.before_token = lambda: (entered.set(), resume.wait(5))
        with ThreadPoolExecutor() as pool:
            future = pool.submit(self.service.complete_authorization, self.ctx, callback_for(attempt))
            self.assertTrue(entered.wait(3))
            self.service.cancel_authorization(self.ctx, attempt['attemptId'])
            resume.set()
            future.result(5)
        self.assertEqual([], self.service.list_accounts(self.ctx)['items'])
        self.assertEqual('AUTHORIZATION_CANCELLED', self.service.get_attempt(self.ctx, attempt['attemptId'])['error']['code'])

    def test_remove_racing_untargeted_login_cannot_resurrect_account(self):
        account = self.connect()
        attempt = self.begin()
        self.service.remove_account(self.ctx, account['id'], account['version'])
        self.assertEqual('VERSION_CONFLICT', self.complete(attempt)['error']['code'])
        self.assertIsNotNone(self.service.get_account(self.ctx, account['id'])['removedAt'])

    def test_remove_revokes_but_retains_identity_and_stops_bound_client(self):
        account = self.connect()
        client = self.service.client_for(self.ctx, self.owner(account))
        self.http.override[ISSUER + 'revoke'] = AuthError('PROVIDER_UNAVAILABLE')
        result = self.service.remove_account(self.ctx, account['id'], account['version'])
        self.assertEqual('failed', result['remoteRevocation'])
        self.assertEqual('removed', self.service.get_account(self.ctx, account['id'])['authorization']['state'])
        self.assertCode('PROVIDER_AUTHORIZATION_REQUIRED', client.identity)

    def test_clients_validate_identity_tenant_and_space(self):
        account = self.connect()
        owner = self.owner(account)
        for value in (dict(owner, tenantId='tenant_b'), dict(owner, providerSubject='another'), dict(owner, spaceId=None)):
            self.assertCode('OWNERSHIP_MISMATCH', lambda v=value: self.service.client_for(self.ctx, v))

    def test_account_client_needs_no_space_and_exposes_no_generation(self):
        account = self.connect()
        owner = self.owner(account)
        owner.pop('spaceId')
        client = self.service.account_client_for(self.ctx, owner)
        self.assertEqual(account['identity'], client.identity())
        for name in ('submit', 'prepare', 'quota', 'download', 'list_models'):
            self.assertFalse(hasattr(client, name))
        self.assertCode('PROVIDER_CAPABILITY_UNAVAILABLE', client.list_spaces)

    def test_old_client_ignores_current_selection_and_caller_dict_mutation(self):
        account = self.connect()
        owner = self.owner(account)
        client = self.service.client_for(self.ctx, owner)
        owner['providerSubject'] = 'changed'
        self.ctx['selection'] = {'providerAccountId': 'other-account'}
        self.assertEqual(account['identity'], client.identity())

    def test_background_task_requires_typed_trusted_context_not_browser_dict(self):
        account = self.connect()
        worker = ProviderWorkerContext(self.ctx['tenantId'])
        self.assertEqual(account['identity'], self.service.client_for(worker, self.owner(account)).identity())
        self.assertCode('SESSION_REQUIRED', lambda: self.service.client_for({'tenantId': self.ctx['tenantId']}, self.owner(account)))
        self.assertCode('SESSION_REQUIRED', lambda: self.service.begin_authorization(worker))

    def test_refresh_rotation_saved_and_identity_rechecked(self):
        account = self.connect()
        self.clock.now += 3590
        self.service.client_for(self.ctx, self.owner(account))
        with self.repo.transaction(self.ctx) as state:
            saved = state['accounts'][account['id']]
            bundle = self.codec.open(saved['private'], binding=binding('tenant_a', 'account', account['id']))
            self.assertEqual('synthetic-refresh-2', bundle['tokens']['refresh_token'])
        self.assertEqual(2, self.http.token_counter)

    def test_refresh_wrong_identity_invalidates_account(self):
        account = self.connect()
        self.clock.now += 3590
        self.identity.subject = 'other-person'
        self.assertCode('PROVIDER_IDENTITY_MISMATCH', lambda: self.service.client_for(self.ctx, self.owner(account)))
        self.assertEqual('expired', self.service.get_account(self.ctx, account['id'])['authorization']['state'])

    def test_refresh_timeout_does_not_resend_rotatable_refresh_token(self):
        account = self.connect()
        self.clock.now += 3590
        self.http.override[ISSUER + 'token'] = AuthError('PROVIDER_UNAVAILABLE')
        self.assertCode('PROVIDER_UNAVAILABLE', lambda: self.service.client_for(self.ctx, self.owner(account)))
        self.assertCode('PROVIDER_AUTHORIZATION_REQUIRED', lambda: self.new_service().client_for(self.ctx, self.owner(account)))
        self.assertEqual(2, len([c for c in self.http.calls if c[1].endswith('/token')]))

    def test_crashed_refresh_lease_requires_reauthorization_without_replay(self):
        account = self.connect()
        self.clock.now += 3590
        with self.repo.transaction(self.ctx) as state:
            state['accounts'][account['id']]['refreshClaim'] = {'id': 'crashed', 'expires': self.clock.now - 1}
        self.assertCode('PROVIDER_AUTHORIZATION_REQUIRED', lambda: self.service.client_for(self.ctx, self.owner(account)))
        self.assertEqual(1, self.http.token_counter)

    def test_corrupt_ciphertext_fails_closed(self):
        attempt = self.begin()
        with self.repo.transaction(self.ctx) as state:
            state['attempts'][attempt['attemptId']]['private'] = 'corrupt'
        self.assertEqual('SECRET_STORAGE_UNAVAILABLE', self.complete(attempt)['error']['code'])
        self.assertEqual(0, self.http.token_counter)

    def test_ciphertext_cannot_move_across_tenant_or_record(self):
        encrypted = self.codec.seal({'access_token': 'secret'}, binding='tenant-a/attempt-a')
        for aad in ('tenant-b/attempt-a', 'tenant-a/attempt-b'):
            self.assertCode('SECRET_STORAGE_UNAVAILABLE', lambda a=aad: self.codec.open(encrypted, binding=a))

    def test_routes_preserve_envelope_and_reject_client_tenant(self):
        class Router:
            def __init__(self): self.routes = {}
            def add(self, method, path, handler): self.routes[method, path] = handler
        router = Router()
        register_routes(router, {'providers': self.service})
        handler = router.routes['POST', '/api/v1/provider-accounts/authorize']
        ctx = dict(self.ctx, json={'provider': 'libtv', 'tenantId': 'tenant_b'})
        response = handler(ctx, {})
        self.assertEqual(422, response.status)
        self.assertEqual('VALIDATION_FAILED', response.body['error']['code'])
        callback = router.routes['GET', '/api/v1/oauth/libtv/callback']
        result = callback(dict(self.ctx, query={'state': 'bad', 'code': 'secret'}), {})
        self.assertEqual(303, result.status)
        self.assertEqual('no-referrer', result.headers['Referrer-Policy'])
        self.assertNotIn('secret', result.headers['Location'])


if __name__ == '__main__':
    unittest.main()
