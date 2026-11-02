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
from backend.providers.libtv_oauth import ClientRegistration, ISSUER, SCOPES
from backend.providers.libtv_identity import LIBTV_ACCOUNT_IDENTITY, ReadOnlyMCPIdentityVerifier, VerifiedIdentity
from backend.providers.libtv_account import LibTVAccountReader
from backend.providers.libtv_bound_tools import BoundMCPTools


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
                 registration=None, clock=time.time, on_account_removed=None, workspace_recovery=None,
                 account_reader=None, operation_adapter_factory=None, operation_adapter=None):
        if operation_adapter is not None and operation_adapter_factory is not None:
            raise AuthError('PROVIDER_UNCONFIGURED')
        self.repository, self.codec, self.oauth = repository, secret_codec, oauth
        self.verifier = identity_verifier or ReadOnlyMCPIdentityVerifier(oauth.http, LIBTV_ACCOUNT_IDENTITY)
        self.registration = registration
        self.clock = clock
        self.on_account_removed = on_account_removed or getattr(repository, 'affected_task_ids', None)
        self.workspace_recovery = workspace_recovery
        self.account_reader = account_reader or LibTVAccountReader(oauth.http, clock=clock)
        self.operation_adapter_factory = operation_adapter_factory
        self.operation_adapter = operation_adapter

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
                'capabilities': {'authorize': True, 'spaces': bool(self.account_reader.available), 'quota': False},
                'grantedScopes': list(account.get('grantedScopes', [])),
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
        result = {'status': 'pending' if status == 'exchanging' else status,
                  'providerAccountId': attempt.get('providerAccountId'),
                  'error': AuthError(attempt['error']).public() if attempt.get('error') else None}
        if attempt.get('workspaceIntentId'):
            result.update(intent=attempt['intent'], workspaceIntentId=attempt['workspaceIntentId'])
        return result

    def get_attempt(self, ctx, id):
        require_context(ctx)
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            attempt = state['attempts'].get(id)
            if not attempt:
                raise AuthError('NOT_FOUND')
            return self._attempt_result(attempt)

    def _oauth_profile(self, profile):
        if profile == 'account':
            return self.oauth
        if profile != 'creator':
            raise AuthError('VALIDATION_FAILED')
        from dataclasses import replace
        from ..providers.libtv_oauth import LibTVOAuth
        return LibTVOAuth(replace(self.oauth.config, scopes=('libtv:account:read', 'libtv:project:read',
            'libtv:project:write', 'libtv:media:write', 'libtv:task:write', 'libtv:export:write')), self.oauth.http)

    def _client(self, ctx, metadata, oauth=None, profile='account'):
        oauth = oauth or self.oauth
        registration_key = 'registration' if profile == 'account' else 'registration_creator'
        tenant, _ = require_context(ctx)
        if self.registration:
            oauth.validate_registration(self.registration, metadata)
            client = self.registration
        else:
            with self.repository.transaction(ctx) as raw:
                saved = self._state(ctx, raw).get(registration_key)
                private = self.codec.open(saved, binding=binding(tenant, 'client', registration_key)) if saved else None
            if private and private.get('redirect_uri') == oauth.config.redirect_uri:
                client = ClientRegistration(**private)
            else:
                client = oauth.register(metadata)
                sealed = self.codec.seal(client.secret_value(), binding=binding(tenant, 'client', registration_key))
                with self.repository.transaction(ctx) as raw:
                    self._state(ctx, raw)[registration_key] = sealed
            oauth.validate_registration(client, metadata)
        if client.secret_expires_at and client.secret_expires_at <= self.clock():
            raise AuthError('PROVIDER_UNCONFIGURED')
        return client

    def begin_authorization(self, ctx, providerAccountId=None, returnPath='/', expectedVersion=None,
                            intent='connect', purpose=None, hasUnsavedChanges=None, workspaceLabel='我的工作区',
                            authorizationProfile='account'):
        tenant, session = mutate_context(ctx)
        if returnPath not in self.oauth.config.return_paths:
            raise AuthError('VALIDATION_FAILED')
        if purpose is not None:
            purposes = {'provider_account': 'connect', 'bind_owner': 'bind_owner', 'recover_workspace': 'recover'}
            if purpose not in purposes or (intent != 'connect' and intent != purposes[purpose]):
                raise AuthError('VALIDATION_FAILED')
            intent = purposes[purpose]
        if (intent not in ('connect', 'bind_owner', 'recover')
                or (intent != 'connect' and (providerAccountId is not None or expectedVersion is not None))
                or (hasUnsavedChanges is not None and type(hasUnsavedChanges) is not bool)):
            raise AuthError('VALIDATION_FAILED')
        if intent != 'connect' and self.workspace_recovery is None:
            raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')
        if intent != 'connect' and authorizationProfile != 'account':
            raise AuthError('VALIDATION_FAILED')
        oauth = self._oauth_profile(authorizationProfile)
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
        metadata = oauth.discover()
        client = self._client(ctx, metadata, oauth, authorizationProfile)
        nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        attempt_id, now = 'oa_' + secrets.token_urlsafe(18), self.clock()
        expires = now + self.oauth.config.attempt_ttl_seconds
        owner_request = None
        if intent != 'connect':
            owner_request = self.workspace_recovery.begin(ctx,
                purpose='bind_owner' if intent == 'bind_owner' else 'recover_workspace',
                authorization_attempt_id=attempt_id, oauth_state_hash=digest(nonce),
                has_unsaved_changes=hasUnsavedChanges, workspace_label=workspaceLabel)
        try:
            private = {'verifier': verifier, 'metadata': metadata, 'client': client.secret_value(),
                       'authorizationProfile': authorizationProfile}
            if owner_request:
                private['ownerIntent'] = {'id': owner_request.intent_id, 'nonce': owner_request.nonce}
            sealed = self.codec.seal(private, binding=binding(tenant, 'attempt', attempt_id))
            authorization_url = oauth.authorization_url(metadata, client, nonce, verifier)
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
                    'intent': intent, 'workspaceIntentId': owner_request.intent_id if owner_request else None,
                    'accountVersions': {k: a['version'] for k, a in state['accounts'].items()}}
        except Exception:
            if owner_request:
                try:
                    self.workspace_recovery.cancel(ctx, owner_request.intent_id)
                except Exception:
                    pass  # TTL still bounds an orphan when storage itself is down.
            raise
        result = {'attemptId': attempt_id, 'authorizationUrl': authorization_url, 'expiresAt': utc(expires)}
        if owner_request:
            result.update(intent=intent, workspaceIntent=owner_request.public())
        return result

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
            owner_intent = attempt.get('workspaceIntentId') if attempt.get('error') == 'AUTHORIZATION_CANCELLED' else None
            result = self._attempt_result(attempt)
        if owner_intent and self.workspace_recovery is not None:
            self.workspace_recovery.cancel(ctx, owner_intent)
        return result

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

    def _complete_owner(self, ctx, saved, private, client, tokens, identity, code_exchanged_at, identity_verified_at):
        """Consume OAuth before the last old-session operation, which may rotate it.

        Workspace proof and generation-account authorization are separate. A
        successful identity proof never implicitly attaches a provider grant.
        """
        from backend.sessions.recovery import FreshOwnerProof
        with self.repository.transaction(ctx) as raw:
            state = self._state(ctx, raw)
            self._expire(state)
            attempt = state['attempts'][saved['id']]
            if attempt['status'] != 'exchanging':
                raise AuthError('AUTHORIZATION_CANCELLED')
            attempt.update(status='completed', providerAccountId=None, private=None, error=None)
            saved = copy.deepcopy(attempt)
        proof = FreshOwnerProof(authorization_attempt_id=saved['id'], oauth_state_hash=saved['stateHash'],
            site_session_id=field(ctx, 'siteSessionId'), issuer=identity.issuer, subject=identity.subject,
            code_exchanged_at=code_exchanged_at, identity_verified_at=identity_verified_at,
            grant_type='authorization_code', state_verified=True, pkce_verified=True,
            authoritative_identity_read=True)
        response = self._redirect(saved)
        workspace_status = 'failed'
        try:
            result = self.workspace_recovery.accept_verified_authorization(ctx,
                intent_id=private['ownerIntent']['id'], nonce=private['ownerIntent']['nonce'], proof=proof)
            workspace_status = result.data['status']
            if result.session is not None:
                response['headers']['Set-Cookie'] = result.session.set_cookie
        except Exception:
            # Never touch old ctx after the hook: it may have rotated the session.
            # Workspace status is separate from the already completed identity proof.
            workspace_status = 'failed'
        finally:
            try:
                self.oauth.revoke(private['metadata'], client, tokens)
            except Exception:
                pass  # A revocation outage must not discard a rotated session cookie.
        response['headers']['Location'] += '&' + urlencode({
            'workspaceIntent': private['ownerIntent']['id'], 'workspaceStatus': workspace_status})
        return response

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
            oauth = self._oauth_profile(private.get('authorizationProfile', 'account'))
            tokens = oauth.exchange(private['metadata'], client, callback['code'], private['verifier'], self.clock())
            code_exchanged_at = self.clock()
            identity = self.verifier.verify(tokens)
            identity_verified_at = self.clock()
            if (not isinstance(identity, VerifiedIdentity) or identity.issuer != ISSUER
                    or not identity.minimal_read_verified or not isinstance(identity.subject, str)
                    or not identity.subject or len(identity.subject) > 512
                    or any(ord(c) < 32 for c in identity.subject)):
                raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
            if saved['targetSubject'] and identity.subject != saved['targetSubject']:
                raise AuthError('PROVIDER_IDENTITY_MISMATCH')
            if saved.get('intent', 'connect') != 'connect':
                return self._complete_owner(ctx, saved, private, client, tokens, identity,
                                            code_exchanged_at, identity_verified_at)
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
                name = (identity.display_name or (account or {}).get('label') or 'LibTV 账号')[:120]
                if not isinstance(name, str) or any(ord(c) < 32 for c in name):
                    raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
                bundle = {'tokens': tokens, 'client': private['client'], 'metadata': private['metadata']}
                account = {'id': account_id, 'version': (account['version'] if account else 0) + 1,
                    'label': name, 'identity': {'issuer': identity.issuer, 'subject': identity.subject,
                                               'displayName': name, 'verified': True},
                    'authorizationState': 'connected', 'expiresAtEpoch': tokens['expires_at'],
                    'lastVerifiedAt': utc(self.clock()), 'removedAt': None, 'reason': None,
                    'grantedScopes': sorted(tokens.get('scope', '').split()),
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
                               grantedScopes=sorted(tokens.get('scope', '').split()),
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

    def _spaces_for(self, ctx, ownership):
        bundle, identity = self._bundle_for(ctx, ownership, require_space=False)
        result = self.account_reader.list_spaces(bundle['tokens'], expected_subject=identity['subject'])
        self._bundle_for(ctx, ownership, require_space=False)  # A concurrent removal wins over a late read.
        return result

    def _assert_space(self, ctx, ownership):
        self._bundle_for(ctx, ownership)
        spaces = self._spaces_for(ctx, ownership)['items']
        selected = next((row for row in spaces if row['id'] == ownership['spaceId']), None)
        if (selected is None or selected['access'] != 'available'
                or (ownership.get('spaceKind') is not None and selected['kind'] != ownership['spaceKind'])):
            raise AuthError('OWNERSHIP_MISMATCH')
        return selected

    def _assert_space_payload(self, ctx, ownership, payload):
        self._bundle_for(ctx, ownership)
        spaces = self.account_reader.spaces_from_payload(payload, expected_subject=ownership['providerSubject'])['items']
        selected = next((row for row in spaces if row['id'] == ownership['spaceId']), None)
        if selected is None or selected['access'] != 'available' or selected['kind'] != ownership['spaceKind']:
            raise AuthError('OWNERSHIP_MISMATCH')
        return selected


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
        return self._service._spaces_for(self._ctx, self._owner)


class BoundProviderClient:
    def __init__(self, service, ctx, ownership):
        self._service, self._ctx = service, copy.copy(ctx)
        self._owner = copy.deepcopy(ownership)
        self._tools = BoundMCPTools(service, ctx, ownership)

    def __repr__(self):
        return '<BoundProviderClient credentials=redacted>'

    def identity(self):
        _, identity = self._service._bundle_for(self._ctx, self._owner)
        return identity

    def list_spaces(self):
        self._service._bundle_for(self._ctx, self._owner)
        return self._service._spaces_for(self._ctx, self._owner)

    def _authorize(self, required_scopes):
        if (not isinstance(required_scopes, (set, frozenset, list, tuple))
                or not required_scopes or any(not isinstance(s, str) for s in required_scopes)
                or not set(required_scopes) <= SCOPES):
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        bundle, _ = self._service._bundle_for(self._ctx, self._owner)
        granted = frozenset(bundle['tokens'].get('scope', '').split())
        if not set(required_scopes) <= granted:
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        try:
            from backend.generation.types import AuthorizedMCP
        except ImportError:
            raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE') from None
        tools = self._tools
        def call_tool(name, arguments):
            # The generation contract accepts an MCP result envelope. The inner
            # dictionary has already passed the standard tool-result parser.
            result = tools.call_tool(name, arguments, space_id=self._owner['spaceId'])
            return {'structuredContent': result, 'isError': False}
        return AuthorizedMCP(ownership=copy.deepcopy(self._owner), granted_scopes=granted,
                             call_tool=call_tool)

    def _invoke(self, operation, *args, **kwargs):
        bundle, _ = self._service._bundle_for(self._ctx, self._owner)
        factory = self._service.operation_adapter_factory
        registered_adapter = self._service.operation_adapter
        if factory is None and registered_adapter is None:
            raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')
        scope = {'quota': 'libtv:account:read', 'list_models': 'libtv:project:read', 'get_model': 'libtv:project:read',
                 'search_assets':'libtv:project:read','get_asset':'libtv:project:read',
                 'prepare': 'libtv:project:read', 'submit': 'libtv:task:write',
                 'lookup': 'libtv:project:read', 'download': 'libtv:project:read'}[operation]
        if scope not in bundle['tokens'].get('scope', '').split():
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        self._service._assert_space(self._ctx, self._owner)
        if registered_adapter is not None:
            binder = getattr(registered_adapter, 'bind', None)
            if not callable(binder):
                raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')
            adapter = binder(ownership=copy.deepcopy(self._owner), authorize=self._authorize)
        else:
            adapter = factory(ownership=copy.deepcopy(self._owner),
                              tools=BoundMCPTools(self._service, self._ctx, self._owner))
        method = getattr(adapter, operation, None)
        if not callable(method):
            raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')
        result = method(*args, **kwargs)
        self._service._bundle_for(self._ctx, self._owner)
        return result

    def quota(self, *args, **kwargs): return self._invoke('quota', *args, **kwargs)
    def list_models(self, *args, **kwargs): return self._invoke('list_models', *args, **kwargs)
    def get_model(self, *args, **kwargs): return self._invoke('get_model', *args, **kwargs)
    def search_assets(self, *args, **kwargs): return self._invoke('search_assets', *args, **kwargs)
    def get_asset(self, *args, **kwargs): return self._invoke('get_asset', *args, **kwargs)
    def prepare(self, *args, **kwargs): return self._invoke('prepare', *args, **kwargs)
    def submit(self, *args, **kwargs): return self._invoke('submit', *args, **kwargs)
    def lookup(self, *args, **kwargs): return self._invoke('lookup', *args, **kwargs)
    def download(self, *args, **kwargs): return self._invoke('download', *args, **kwargs)
