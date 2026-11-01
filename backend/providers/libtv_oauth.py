"""LibTV public OAuth metadata only; no CLI and no private website endpoints."""
import base64
import hashlib
import json
import logging
import re
import socket
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from backend.auth.errors import AuthError

RESOURCE = 'https://mcp.liblib.tv/mcp'
ISSUER = 'https://mcp.liblib.tv/'
ORIGIN = 'https://mcp.liblib.tv'
RESOURCE_METADATA = ORIGIN + '/.well-known/oauth-protected-resource/mcp'
SERVER_METADATA = ORIGIN + '/.well-known/oauth-authorization-server'
SCOPES = frozenset({'libtv:account:read', 'libtv:project:read', 'libtv:project:write',
                    'libtv:media:write', 'libtv:task:write', 'libtv:export:write'})


def official_url(value):
    if not isinstance(value, str):
        raise AuthError('PROVIDER_PROTOCOL_ERROR')
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise AuthError('PROVIDER_PROTOCOL_ERROR') from None
    if (parsed.scheme != 'https' or parsed.netloc != 'mcp.liblib.tv'
            or parsed.username or parsed.password or parsed.fragment or parsed.query
            or any(ord(c) < 33 for c in value)):
        raise AuthError('PROVIDER_PROTOCOL_ERROR')
    return value


def pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode().rstrip('=')


@dataclass(frozen=True)
class OAuthConfig:
    redirect_uri: str
    return_paths: tuple = ('/',)
    scopes: tuple = ('libtv:account:read',)
    client_name: str = '资产研究室 · 客户网页'
    allow_loopback_development: bool = False
    attempt_ttl_seconds: int = 600
    max_pending_attempts: int = 5
    application_type: str | None = None

    def __post_init__(self):
        p = urlsplit(self.redirect_uri)
        loopback = (self.allow_loopback_development and p.scheme == 'http'
                    and p.hostname in ('127.0.0.1', '::1', 'localhost'))
        if (not p.hostname or (p.scheme != 'https' and not loopback)
                or p.username or p.password or p.query or p.fragment
                or not p.path.endswith('/api/v1/oauth/libtv/callback')
                or '%' in p.path or '\\' in p.path or '//' in p.path or '/..' in p.path
                or any(ord(c) < 33 for c in self.redirect_uri)
                or not self.scopes or not set(self.scopes) <= SCOPES
                or 'libtv:account:read' not in self.scopes
                or not 60 <= self.attempt_ttl_seconds <= 900
                or not 1 <= self.max_pending_attempts <= 10
                or self.application_type not in (None, 'web', 'native')
                or (self.application_type == 'native' and not loopback)):
            raise AuthError('PROVIDER_UNCONFIGURED')
        for path in self.return_paths:
            if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
                    or urlsplit(path).query or urlsplit(path).fragment or '%' in path
                    or '\\' in path or any(ord(c) < 33 for c in path)):
                raise AuthError('PROVIDER_UNCONFIGURED')
        if '/' not in self.return_paths:
            raise AuthError('PROVIDER_UNCONFIGURED')


@dataclass(repr=False)
class ClientRegistration:
    client_id: str
    redirect_uri: str
    auth_method: str = 'none'
    client_secret: str | None = field(default=None, repr=False)
    secret_expires_at: int = 0

    def __repr__(self):
        return '<ClientRegistration credentials=redacted>'

    def secret_value(self):
        return dict(client_id=self.client_id, redirect_uri=self.redirect_uri,
                    auth_method=self.auth_method, client_secret=self.client_secret,
                    secret_expires_at=self.secret_expires_at)


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(repr=False)
class HTTPResult:
    status: int
    data: dict
    headers: dict = field(default_factory=dict)

    def __repr__(self):
        return f'<HTTPResult status={self.status} body=redacted>'


class OfficialHTTP:
    """Bounded requests; redirects cannot exfiltrate codes/tokens/client secrets."""
    def __init__(self, timeout=15, max_bytes=None, mcp_timeout=60):
        self.timeout = timeout
        self.mcp_timeout = mcp_timeout
        self.max_bytes = 1024 * 1024 if max_bytes is None else max_bytes
        self.mcp_max_bytes = 16 * 1024 * 1024 if max_bytes is None else max_bytes
        self._opener = build_opener(_NoRedirects())

    def request(self, method, url, *, data=None, headers=None):
        official_url(url)
        limit = self.mcp_max_bytes if url == RESOURCE else self.max_bytes
        try:
            req = Request(url, data=data, headers=headers or {}, method=method)
            try:
                response = self._opener.open(req, timeout=self.mcp_timeout if url == RESOURCE else self.timeout)
            except HTTPError as err:
                response = err
            with response:
                status, response_headers = response.status, dict(response.headers)
                if 300 <= status < 400:
                    raise AuthError('PROVIDER_PROTOCOL_ERROR')
                content_type = next((v for k, v in response_headers.items() if k.lower() == 'content-type'), '')
                if 'text/event-stream' in content_type:
                    body, used, event_data = None, 0, []
                    while used <= limit:
                        line = response.readline(limit - used + 1)
                        used += len(line)
                        if used > limit:
                            raise AuthError('PROVIDER_RESPONSE_TOO_LARGE')
                        if not line:
                            raise ValueError()
                        decoded = line.decode().rstrip('\r\n')
                        if decoded.startswith('data:'):
                            event_data.append(decoded[5:].lstrip())
                        elif not decoded and event_data:
                            message = json.loads('\n'.join(event_data))
                            event_data = []
                            if isinstance(message, dict) and ('result' in message or 'error' in message):
                                body = message
                                break
                    if body is None:
                        raise ValueError()
                    return HTTPResult(status, body, response_headers)
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise AuthError('PROVIDER_RESPONSE_TOO_LARGE')
            if not raw and status in (200, 202, 204):
                body = {}
            else:
                body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError()
            return HTTPResult(status, body, response_headers)
        except AuthError:
            raise
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            # Never log URLs, exception messages, request bodies or credentials.
            cause = getattr(exc, 'reason', exc)
            kind = 'timeout' if isinstance(cause, (TimeoutError, socket.timeout)) else 'transport'
            logging.getLogger(__name__).error('Official request failed: endpoint=%s kind=%s',
                                                'mcp' if url == RESOURCE else 'oauth', kind)
            raise AuthError('PROVIDER_UNAVAILABLE') from None
        except (ValueError, UnicodeError, RecursionError):
            raise AuthError('PROVIDER_PROTOCOL_ERROR') from None


class LibTVOAuth:
    def __init__(self, config, http=None):
        self.config = config
        self.http = http or OfficialHTTP()

    def discover(self):
        challenge = self.http.request('GET', RESOURCE, headers={'Accept': 'application/json'})
        authenticate = next((v for k, v in challenge.headers.items() if k.lower() == 'www-authenticate'), '')
        if challenge.status != 401 or f'resource_metadata="{RESOURCE_METADATA}"' not in authenticate:
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        resource = self.http.request('GET', RESOURCE_METADATA, headers={'Accept': 'application/json'})
        server = self.http.request('GET', SERVER_METADATA, headers={'Accept': 'application/json'})
        if resource.status != 200 or server.status != 200:
            raise AuthError('PROVIDER_UNAVAILABLE')
        rm, sm = resource.data, server.data
        if (not isinstance(rm.get('authorization_servers'), list)
                or any(not isinstance(sm.get(k), list) for k in ('response_types_supported',
                    'code_challenge_methods_supported', 'grant_types_supported',
                    'token_endpoint_auth_methods_supported', 'scopes_supported'))):
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        if (rm.get('resource') != RESOURCE or ISSUER not in rm.get('authorization_servers', [])
                or sm.get('issuer') != ISSUER or 'code' not in sm.get('response_types_supported', [])
                or 'S256' not in sm.get('code_challenge_methods_supported', [])
                or 'authorization_code' not in sm.get('grant_types_supported', [])
                or 'none' not in sm.get('token_endpoint_auth_methods_supported', [])):
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        if not set(self.config.scopes) <= set(sm.get('scopes_supported', [])):
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        # The resource-specific discovery document currently has an empty scope list.
        # Use the authorization server's advertised scope list; never invent scopes.
        for key in ('authorization_endpoint', 'token_endpoint'):
            official_url(sm.get(key))
        for key in ('registration_endpoint', 'revocation_endpoint'):
            if sm.get(key):
                official_url(sm[key])
        return sm

    def register(self, metadata):
        endpoint = metadata.get('registration_endpoint')
        if not endpoint:
            raise AuthError('PROVIDER_UNCONFIGURED')
        payload = {'client_name': self.config.client_name,
                   'redirect_uris': [self.config.redirect_uri],
                   'grant_types': ['authorization_code', 'refresh_token'],
                   'response_types': ['code'], 'token_endpoint_auth_method': 'none',
                   'scope': ' '.join(self.config.scopes)}
        if self.config.application_type:
            payload['application_type'] = self.config.application_type
        response = self.http.request('POST', endpoint, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        if response.status in (400, 401, 403):
            raise AuthError('PROVIDER_REGISTRATION_REJECTED')
        if response.status not in (200, 201):
            raise AuthError('PROVIDER_UNAVAILABLE')
        body = response.data
        if (not isinstance(body.get('client_id'), str) or not 1 <= len(body['client_id']) <= 4096
                or any(ord(c) < 33 for c in body['client_id'])
                or body.get('redirect_uris') != [self.config.redirect_uri]
                or body.get('token_endpoint_auth_method') != 'none'
                or body.get('client_secret')):
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        return ClientRegistration(body['client_id'], self.config.redirect_uri)

    def validate_registration(self, client, metadata):
        if (client.redirect_uri != self.config.redirect_uri or not client.client_id
                or client.auth_method not in metadata.get('token_endpoint_auth_methods_supported', [])
                or (client.auth_method != 'none' and not client.client_secret)
                or client.auth_method not in ('none', 'client_secret_basic', 'client_secret_post')):
            raise AuthError('PROVIDER_UNCONFIGURED')

    def authorization_url(self, metadata, client, state, verifier):
        self.validate_registration(client, metadata)
        return metadata['authorization_endpoint'] + '?' + urlencode({
            'response_type': 'code', 'client_id': client.client_id,
            'redirect_uri': client.redirect_uri, 'scope': ' '.join(self.config.scopes),
            'state': state, 'code_challenge': pkce_challenge(verifier),
            'code_challenge_method': 'S256', 'resource': RESOURCE})

    def _form(self, endpoint, client, payload):
        payload = dict(payload, client_id=client.client_id)
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
        if client.auth_method == 'client_secret_post':
            payload['client_secret'] = client.client_secret
        elif client.auth_method == 'client_secret_basic':
            # OAuth Basic values are form-encoded before joining with a colon.
            from urllib.parse import quote_plus
            raw = quote_plus(client.client_id) + ':' + quote_plus(client.client_secret)
            headers['Authorization'] = 'Basic ' + base64.b64encode(raw.encode()).decode()
        return self.http.request('POST', endpoint, data=urlencode(payload).encode(), headers=headers)

    def _tokens(self, response, now, previous=None):
        if response.status in (400, 401, 403):
            raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED')
        if response.status != 200:
            raise AuthError('PROVIDER_UNAVAILABLE')
        body = response.data
        access, refresh = body.get('access_token'), body.get('refresh_token')
        expires = body.get('expires_in')
        scope = body.get('scope', (previous or {}).get('scope', ' '.join(self.config.scopes)))
        if (not isinstance(access, str) or not access or len(access) > 32768
                or not re.fullmatch(r'[A-Za-z0-9._~+/\-]+=*', access)
                or str(body.get('token_type', '')).lower() != 'bearer'
                or isinstance(expires, bool) or not isinstance(expires, (int, float))
                or not 0 < expires <= 366 * 86400 or not isinstance(scope, str)
                or not set(self.config.scopes) <= set(scope.split())
                or (refresh is not None and (not isinstance(refresh, str) or not refresh or len(refresh) > 32768))):
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        # A token response (including an unsigned JWT sub) is not verified identity.
        return {'access_token': access, 'refresh_token': refresh or (previous or {}).get('refresh_token'),
                'expires_at': now + expires, 'scope': scope, 'token_type': 'Bearer'}

    def exchange(self, metadata, client, code, verifier, now):
        response = self._form(metadata['token_endpoint'], client, {
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': client.redirect_uri,
            'code_verifier': verifier, 'resource': RESOURCE})
        return self._tokens(response, now)

    def refresh(self, metadata, client, tokens, now):
        if not tokens.get('refresh_token') or 'refresh_token' not in metadata.get('grant_types_supported', []):
            raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED')
        response = self._form(metadata['token_endpoint'], client, {
            'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'], 'resource': RESOURCE})
        return self._tokens(response, now, tokens)

    def revoke(self, metadata, client, tokens):
        if not metadata.get('revocation_endpoint'):
            return 'unsupported'
        try:
            outcomes = []
            for key in ('refresh_token', 'access_token'):
                if tokens.get(key):
                    response = self._form(metadata['revocation_endpoint'], client,
                                          {'token': tokens[key], 'token_type_hint': key})
                    outcomes.append(response.status == 200)
            return 'confirmed' if outcomes and all(outcomes) else 'failed'
        except AuthError:
            return 'failed'
