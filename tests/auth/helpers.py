"""Isolated test repository. NOT a production storage substitute."""
import json
import sqlite3
from contextlib import contextmanager, closing
from urllib.parse import parse_qs, urlsplit

from backend.providers.libtv_identity import VerifiedIdentity
from backend.auth.errors import field
from backend.providers.libtv_oauth import HTTPResult, ISSUER, RESOURCE, RESOURCE_METADATA, SCOPES


class SqliteTestRepository:
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS auth_fixture (tenant TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            conn.commit()

    @contextmanager
    def transaction(self, ctx):
        tenant = field(ctx, 'tenantId')
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT payload FROM auth_fixture WHERE tenant=?', (tenant,)).fetchone()
            state = json.loads(row[0]) if row else {}
            yield state
            conn.execute('INSERT INTO auth_fixture VALUES(?,?) ON CONFLICT(tenant) DO UPDATE SET payload=excluded.payload',
                         (tenant, json.dumps(state)))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def context(tenant='tenant_a', session='session_a'):
    return {'tenantId': tenant, 'siteSessionId': session, 'csrfVerified': True, 'requestId': 'test_request'}


def callback_for(attempt, **extra):
    return {'state': parse_qs(urlsplit(attempt['authorizationUrl']).query)['state'][0], 'code': 'test-code', **extra}


class Clock:
    def __init__(self):
        self.now = 1793060000

    def __call__(self):
        return self.now


class IdentityFixture:
    available = True

    def __init__(self):
        self.subject = 'synthetic-person-a'
        self.before_verify = None

    def verify(self, tokens):
        if self.before_verify:
            self.before_verify()
        return VerifiedIdentity(self.subject, '合成账号')


class FakeHTTP:
    def __init__(self):
        self.calls = []
        self.override = {}
        self.token_counter = 0
        self.before_token = None
        self.metadata = {'issuer': ISSUER, 'authorization_endpoint': ISSUER + 'authorize',
            'token_endpoint': ISSUER + 'token', 'registration_endpoint': ISSUER + 'register',
            'revocation_endpoint': ISSUER + 'revoke', 'scopes_supported': sorted(SCOPES),
            'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic'],
            'code_challenge_methods_supported': ['S256']}

    def request(self, method, url, *, data=None, headers=None):
        self.calls.append((method, url, data, headers or {}))
        if url in self.override:
            value = self.override[url]
            if isinstance(value, Exception):
                raise value
            return value
        if url == RESOURCE:
            return HTTPResult(401, {}, {'WWW-Authenticate': f'Bearer resource_metadata="{RESOURCE_METADATA}"'})
        if 'oauth-protected-resource' in url:
            return HTTPResult(200, {'resource': RESOURCE, 'authorization_servers': [ISSUER], 'scopes_supported': []})
        if 'oauth-authorization-server' in url:
            return HTTPResult(200, dict(self.metadata))
        if url.endswith('/register'):
            payload = json.loads(data)
            return HTTPResult(201, {'client_id': 'synthetic-client', 'redirect_uris': payload['redirect_uris'],
                                    'token_endpoint_auth_method': 'none'})
        if url.endswith('/token'):
            if self.before_token:
                self.before_token()
            self.token_counter += 1
            return HTTPResult(200, {'access_token': f'synthetic-access-{self.token_counter}',
                'refresh_token': f'synthetic-refresh-{self.token_counter}',
                'expires_in': 3600, 'token_type': 'Bearer', 'scope': 'libtv:account:read'})
        if url.endswith('/revoke'):
            return HTTPResult(200, {})
        raise AssertionError('unexpected public endpoint')
