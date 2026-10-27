"""Tenant-bound OAuth lifecycle, independent of HTTP framework and storage engine.

repository.transaction(ctx) yields a mutable, tenant-scoped dict and MUST provide
durable, serializable commit/rollback. No production in-memory fallback exists.
"""
import copy
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from .errors import AuthError, field, require_context
from backend.providers.libtv_oauth import ClientRegistration, ISSUER
from backend.providers.libtv_identity import UnavailableIdentityVerifier, VerifiedIdentity


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def binding(tenant, kind, identifier):
    return json.dumps(['libtv-auth-v1', tenant, kind, identifier], separators=(',', ':'))


def mutate_context(ctx):
    result = require_context(ctx)
    if field(ctx, 'csrfVerified') is not True:
        raise AuthError('CSRF_FAILED')
    return result


class ProviderService:
    def __init__(self, repository, secret_codec, oauth, *, identity_verifier=None,
                 registration=None, clock=time.time, on_account_removed=None):
        self.repository, self.codec, self.oauth = repository, secret_codec, oauth
        self.verifier = identity_verifier or UnavailableIdentityVerifier()
        self.registration = registration
        self.clock = clock
        self.on_account_removed = on_account_removed or getattr(repository, 'affected_task_ids', None)

    def readiness(self):
        # Registration acceptance alone does not verify a real customer identity.
        return {'configured': bool(self.verifier.available), 'customerReady': False,
                'reason': None if self.verifier.available else 'official_identity_read_unverified'}

    def _state(self, ctx, state):
        tenant, _ = require_context(ctx, allow_worker=True)
        if state and state.get('tenantId') != tenant:
            raise AuthError('NOT_FOUND')
        if not state:
            state.update({'tenantId': tenant, 'schemaVersion': 1, 'accounts': {}, 'attempts': {}})
        if state.get('schemaVersion') != 1:
            raise AuthError('PROVIDER_UNCONFIGURED')
        return state

    def _expire(self, state):
        now = self.clock()
        for attempt in state['attempts'].values():
            if attempt['status'] in ('pending', 'exchanging') and attempt['expiresAtEpoch'] <= now:
                attempt.update(status='expired', error='AUTHORIZATION_EXPIRED', private=None)
        terminal = sorted((a for a in state['attempts'].values() if a['status'] not in ('pending', 'exchanging')),
                          key=lambda a: a['expiresAtEpoch'], reverse=True)
        for index, attempt in enumerate(terminal):
            if index >= 200 or attempt['expiresAtEpoch'] < now - 86400:
                del state['attempts'][attempt['id']]

    def _account(self, state, account_id):
        account = state['accounts'].get(account_id)
        if account is None:
            raise AuthError('NOT_FOUND')
        return account

    def _public_account(self, account):
        state = account['authorizationState']
        if state == 'connected' and account['expiresAtEpoch'] <= self.clock():
            state = 'expired'
        return {'id': account['id'], 'provider': 'libtv', 'label': account['label'], 'version': account['version'],
                'identity': dict(account['identity']),
                'authorization': {'state': state,
                                  'expiresAt': utc(account['expiresAtEpoch']) if account['expiresAtEpoch'] else None,
                                  'lastVerifiedAt': account['lastVerifiedAt'], 'reason': account.get('reason')},
                'capabilities': {'authorize': True, 'spaces': False, 'quota': False},
                'removedAt': account['removedAt']}

    def list_accounts(self, ctx):
        require_context(ctx)
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            return {'items': [self._public_account(a) for a in state['accounts'].values()], 'nextCursor': None}

    def get_account(self, ctx, id):
        require_context(ctx)
        with self.repository.transaction(ctx) as raw:
            return self._public_account(self._account(self._state(ctx, raw), id))

    def _attempt_result(self, attempt):
        status = attempt['status']
        return {'status': 'pending' if status == 'exchanging' else status,
                'providerAccountId': attempt.get('providerAccountId'),
                'error': AuthError(attempt['error']).public() if attempt.get('error') else None}

    def get_attempt(self, ctx, id):
        require_context(ctx)
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            attempt = state['attempts'].get(id)
            if not attempt:
                raise AuthError('NOT_FOUND')
            return self._attempt_result(attempt)

    def _client(self, ctx, metadata):
        tenant, _ = require_context(ctx)
        if self.registration:
            self.oauth.validate_registration(self.registration, metadata)
            client = self.registration
        else:
            with self.repository.transaction(ctx) as raw:
                saved = self._state(ctx, raw).get('registration')
                private = self.codec.open(saved, binding=binding(tenant, 'client', 'registration')) if saved else None
            if private and private.get('redirect_uri') == self.oauth.config.redirect_uri:
                client = ClientRegistration(**private)
            else:
                client = self.oauth.register(metadata)
                sealed = self.codec.seal(client.secret_value(), binding=binding(tenant, 'client', 'registration'))
                with self.repository.transaction(ctx) as raw:
                    self._state(ctx, raw)['registration'] = sealed
            self.oauth.validate_registration(client, metadata)
        if client.secret_expires_at and client.secret_expires_at <= self.clock():
            raise AuthError('PROVIDER_UNCONFIGURED')
        return client

    def begin_authorization(self, ctx, providerAccountId=None, returnPath='/', expectedVersion=None):
        tenant, session = mutate_context(ctx)
        if returnPath not in self.oauth.config.return_paths:
            raise AuthError('VALIDATION_FAILED')
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            if sum(a['status'] in ('pending', 'exchanging') for a in state['attempts'].values()) >= self.oauth.config.max_pending_attempts:
                raise AuthError('AUTHORIZATION_BUSY')
            target_subject = None
            if providerAccountId is not None:
                account = self._account(state, providerAccountId)
                if type(expectedVersion) is not int or account['version'] != expectedVersion:
                    raise AuthError('VERSION_CONFLICT')
                target_subject = account['identity']['subject']
        metadata = self.oauth.discover()
        client = self._client(ctx, metadata)
        nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        attempt_id, now = 'oa_' + secrets.token_urlsafe(18), self.clock()
        expires = now + self.oauth.config.attempt_ttl_seconds
        sealed = self.codec.seal({'verifier': verifier, 'metadata': metadata, 'client': client.secret_value()},
                                 binding=binding(tenant, 'attempt', attempt_id))
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            if sum(a['status'] in ('pending', 'exchanging') for a in state['attempts'].values()) >= self.oauth.config.max_pending_attempts:
                raise AuthError('AUTHORIZATION_BUSY')
            if providerAccountId is not None and self._account(state, providerAccountId)['version'] != expectedVersion:
                raise AuthError('VERSION_CONFLICT')
            state['attempts'][attempt_id] = {'id': attempt_id, 'stateHash': digest(nonce),
                'sessionHash': digest(session), 'status': 'pending', 'error': None,
                'createdAt': utc(now), 'expiresAtEpoch': expires, 'returnPath': returnPath,
                'targetAccountId': providerAccountId, 'targetSubject': target_subject,
                'targetVersion': expectedVersion, 'providerAccountId': None, 'private': sealed,
                'accountVersions': {k: a['version'] for k, a in state['accounts'].items()}}
        return {'attemptId': attempt_id, 'authorizationUrl': self.oauth.authorization_url(metadata, client, nonce, verifier),
                'expiresAt': utc(expires)}

    def cancel_authorization(self, ctx, id):
        _, session = mutate_context(ctx)
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            attempt = state['attempts'].get(id)
            if not attempt or not hmac.compare_digest(attempt['sessionHash'], digest(session)):
                raise AuthError('NOT_FOUND')
            if attempt['status'] in ('pending', 'exchanging'):
                attempt.update(status='failed', error='AUTHORIZATION_CANCELLED', private=None)
            return self._attempt_result(attempt)

    def _callback(self, callback):
        if not isinstance(callback, dict):
            raise AuthError('AUTHORIZATION_STATE_INVALID')
        out = {}
        for key in ('state', 'code', 'error', 'iss'):
            value = callback.get(key)
            if isinstance(value, list):
                if len(value) != 1:
                    raise AuthError('AUTHORIZATION_STATE_INVALID')
                value = value[0]
            if value is not None and (not isinstance(value, str) or not value or len(value) > 8192
                                      or any(ord(c) < 32 for c in value)):
                raise AuthError('AUTHORIZATION_STATE_INVALID')
            out[key] = value
        if not out['state'] or len(out['state']) > 256 or bool(out['code']) == bool(out['error']):
            raise AuthError('AUTHORIZATION_STATE_INVALID')
        return out

    def _finish_failure(self, ctx, id, code):
        with self.repository.transaction(ctx) as raw:
            attempt = self._state(ctx, raw)['attempts'].get(id)
            if attempt and attempt['status'] == 'exchanging':
                attempt.update(status='failed', error=code, private=None)

    def _redirect(self, attempt):
        query = urlencode({'authorizationAttempt': attempt['id'],
                           'authorizationStatus': self._attempt_result(attempt)['status']})
        return {'status': 303, 'body': b'', 'headers': {'Location': attempt['returnPath'] + '?' + query,
                'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"}}

    def complete_authorization(self, ctx, callback):
        tenant, session = require_context(ctx)
        callback = self._callback(callback)
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            matches = [a for a in state['attempts'].values()
                       if hmac.compare_digest(a['stateHash'], digest(callback['state']))]
            if len(matches) != 1 or not hmac.compare_digest(matches[0]['sessionHash'], digest(session)):
                raise AuthError('AUTHORIZATION_STATE_INVALID')
            attempt = matches[0]
            if attempt['status'] != 'pending':
                # Replay never exchanges a code, including after restart/cancellation.
                raise AuthError('AUTHORIZATION_STATE_INVALID')
            attempt['status'] = 'exchanging'
            saved = copy.deepcopy(attempt)
        tokens, private, client = None, None, None
        try:
            if callback['iss'] and callback['iss'] != ISSUER:
                raise AuthError('AUTHORIZATION_STATE_INVALID')
            if callback['error']:
                raise AuthError('AUTHORIZATION_DENIED' if callback['error'] == 'access_denied' else 'AUTHORIZATION_FAILED')
            private = self.codec.open(saved['private'], binding=binding(tenant, 'attempt', saved['id']))
            if private['metadata'].get('authorization_response_iss_parameter_supported') and callback['iss'] != ISSUER:
                raise AuthError('AUTHORIZATION_STATE_INVALID')
            client = ClientRegistration(**private['client'])
            tokens = self.oauth.exchange(private['metadata'], client, callback['code'], private['verifier'], self.clock())
            identity = self.verifier.verify(tokens)
            if (not isinstance(identity, VerifiedIdentity) or identity.issuer != ISSUER
                    or not identity.minimal_read_verified or not isinstance(identity.subject, str)
                    or not identity.subject or len(identity.subject) > 512
                    or any(ord(c) < 32 for c in identity.subject)):
                raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
            if saved['targetSubject'] and identity.subject != saved['targetSubject']:
                raise AuthError('PROVIDER_IDENTITY_MISMATCH')
            with self.repository.transaction(ctx) as raw:
                state = self._state(ctx, raw)
                self._expire(state)
                attempt = state['attempts'][saved['id']]
                if attempt['status'] != 'exchanging':
                    raise AuthError('AUTHORIZATION_CANCELLED')
                if saved['targetAccountId']:
                    account = self._account(state, saved['targetAccountId'])
                    if account['version'] != saved['targetVersion']:
                        raise AuthError('VERSION_CONFLICT')
                else:
                    matches = [a for a in state['accounts'].values()
                               if a['identity']['issuer'] == identity.issuer and a['identity']['subject'] == identity.subject]
                    account = matches[0] if matches else None
                    if account and ((account['id'] in saved['accountVersions'] and
                                     saved['accountVersions'][account['id']] != account['version'])
                                    or (account['id'] not in saved['accountVersions'] and account['removedAt'])):
                        raise AuthError('VERSION_CONFLICT')
                account_id = account['id'] if account else 'pa_' + secrets.token_urlsafe(18)
                name = (identity.display_name or 'LibTV 账号')[:120]
                if not isinstance(name, str) or any(ord(c) < 32 for c in name):
                    raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
                bundle = {'tokens': tokens, 'client': private['client'], 'metadata': private['metadata']}
                account = {'id': account_id, 'version': (account['version'] if account else 0) + 1,
                    'label': name, 'identity': {'issuer': identity.issuer, 'subject': identity.subject,
                                               'displayName': name, 'verified': True},
                    'authorizationState': 'connected', 'expiresAtEpoch': tokens['expires_at'],
                    'lastVerifiedAt': utc(self.clock()), 'removedAt': None, 'reason': None,
                    'private': self.codec.seal(bundle, binding=binding(tenant, 'account', account_id)),
                    'refreshClaim': None}
                state['accounts'][account_id] = account
                attempt.update(status='completed', providerAccountId=account_id, private=None, error=None)
                saved = copy.deepcopy(attempt)
        except Exception as err:
            if tokens and private and client:
                self.oauth.revoke(private['metadata'], client, tokens)
            code = err.code if isinstance(err, AuthError) else 'AUTHORIZATION_FAILED'
            self._finish_failure(ctx, saved['id'], code)
            with self.repository.transaction(ctx) as raw:
                saved = copy.deepcopy(self._state(ctx, raw)['attempts'][saved['id']])
        return self._redirect(saved)

    def remove_account(self, ctx, id, expectedVersion):
        tenant, _ = mutate_context(ctx)
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            account = self._account(state, id)
            if type(expectedVersion) is not int or account['version'] != expectedVersion:
                raise AuthError('VERSION_CONFLICT')
            sealed = account['private']
            account.update(private=None, authorizationState='removed', removedAt=utc(self.clock()),
                           version=account['version'] + 1, refreshClaim=None, reason='removed_by_customer')
            for attempt in state['attempts'].values():
                if attempt['targetAccountId'] == id and attempt['status'] in ('pending', 'exchanging'):
                    attempt.update(status='failed', error='AUTHORIZATION_CANCELLED', private=None)
        # Local access is removed before any network call; history/ownership is untouched.
        remote = 'unsupported'
        if sealed:
            try:
                bundle = self.codec.open(sealed, binding=binding(tenant, 'account', id))
                remote = self.oauth.revoke(bundle['metadata'], ClientRegistration(**bundle['client']), bundle['tokens'])
            except AuthError:
                remote = 'failed'
        affected = self.on_account_removed(ctx, id) if self.on_account_removed else []
        return {'removed': True, 'remoteRevocation': remote, 'affectedTaskIds': affected}

    def _bundle_for(self, ctx, ownership, *, require_space=True):
        tenant, _ = require_context(ctx, allow_worker=True)
        if (not isinstance(ownership, dict) or ownership.get('tenantId') != tenant
                or ownership.get('provider') != 'libtv'
                or (require_space and (not isinstance(ownership.get('spaceId'), str) or not ownership['spaceId']))):
            raise AuthError('OWNERSHIP_MISMATCH')
        account_id = ownership.get('providerAccountId')
        with self.repository.transaction(ctx) as raw:
            account = self._account(self._state(ctx, raw), account_id)
            if ownership.get('providerSubject') != account['identity']['subject']:
                raise AuthError('OWNERSHIP_MISMATCH')
            if not account['private'] or account['authorizationState'] not in ('connected', 'expired'):
                raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED')
            bundle = self.codec.open(account['private'], binding=binding(tenant, 'account', account_id))
            if bundle['tokens']['expires_at'] > self.clock() + 30:
                return bundle, copy.deepcopy(account['identity'])
            if account.get('refreshClaim'):
                if account['refreshClaim']['expires'] > self.clock():
                    raise AuthError('AUTHORIZATION_IN_PROGRESS')
                # A crashed refresh may have rotated the token upstream. Never resend it.
                account.update(private=None, authorizationState='expired', reason='refresh_outcome_unknown',
                               refreshClaim=None, version=account['version'] + 1)
                stalled = True
            else:
                stalled = False
                claim = secrets.token_urlsafe(18)
                version = account['version']
                account['refreshClaim'] = {'id': claim, 'expires': self.clock() + 60}
        if stalled:
            raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED')
        tokens = None
        client = ClientRegistration(**bundle['client'])
        try:
            tokens = self.oauth.refresh(bundle['metadata'], client, bundle['tokens'], self.clock())
            identity = self.verifier.verify(tokens)
            if (not isinstance(identity, VerifiedIdentity) or identity.subject != ownership['providerSubject']
                    or identity.issuer != ISSUER or not identity.minimal_read_verified):
                raise AuthError('PROVIDER_IDENTITY_MISMATCH')
            with self.repository.transaction(ctx) as raw:
                account = self._account(self._state(ctx, raw), account_id)
                if account['version'] != version or (account.get('refreshClaim') or {}).get('id') != claim:
                    raise AuthError('VERSION_CONFLICT')
                bundle['tokens'] = tokens
                account.update(private=self.codec.seal(bundle, binding=binding(tenant, 'account', account_id)),
                               expiresAtEpoch=tokens['expires_at'], refreshClaim=None, authorizationState='connected',
                               lastVerifiedAt=utc(self.clock()), reason=None, version=version + 1)
                return bundle, copy.deepcopy(account['identity'])
        except Exception as err:
            if tokens:
                self.oauth.revoke(bundle['metadata'], client, tokens)
            with self.repository.transaction(ctx) as raw:
                account = self._account(self._state(ctx, raw), account_id)
                if account['version'] == version and (account.get('refreshClaim') or {}).get('id') == claim:
                    account.update(private=None, authorizationState='expired', refreshClaim=None,
                                   reason='reauthorization_required', version=version + 1)
            if isinstance(err, AuthError):
                raise err from None
            raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED') from None

    def client_for(self, ctx, ownership):
        # Every operation resolves the stored immutable owner, never the UI selection.
        self._bundle_for(ctx, ownership)
        return BoundProviderClient(self, ctx, ownership)

    def account_client_for(self, ctx, ownership):
        self._bundle_for(ctx, ownership, require_space=False)
        return BoundAccountClient(self, ctx, ownership)


class BoundAccountClient:
    """Only identity/space discovery before a space is selected. No generation API."""
    def __init__(self, service, ctx, ownership):
        self._service, self._ctx = service, copy.copy(ctx)
        self._owner = copy.deepcopy(ownership)

    def __repr__(self):
        return '<BoundAccountClient credentials=redacted>'

    def identity(self):
        _, identity = self._service._bundle_for(self._ctx, self._owner, require_space=False)
        return identity

    def list_spaces(self):
        self._service._bundle_for(self._ctx, self._owner, require_space=False)
        raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')


class BoundProviderClient:
    def __init__(self, service, ctx, ownership):
        self._service, self._ctx = service, copy.copy(ctx)
        self._owner = copy.deepcopy(ownership)

    def __repr__(self):
        return '<BoundProviderClient credentials=redacted>'

    def identity(self):
        _, identity = self._service._bundle_for(self._ctx, self._owner)
        return identity

    def _unavailable(self, *args, **kwargs):
        self._service._bundle_for(self._ctx, self._owner)
        raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')

    list_spaces = quota = list_models = prepare = submit = lookup = download = _unavailable
