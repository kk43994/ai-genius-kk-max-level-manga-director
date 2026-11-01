import io
import json
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs

from backend.auth.errors import AuthError
from backend.providers.libtv_identity import (IdentityReadContract, MCPReadSession, ReadOnlyMCPIdentityVerifier)
from backend.providers.libtv_oauth import (ClientRegistration, HTTPResult, ISSUER, RESOURCE,
    RESOURCE_METADATA, LibTVOAuth, OAuthConfig, OfficialHTTP, _NoRedirects)
from helpers import FakeHTTP


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeHTTP()
        self.config = OAuthConfig('https://website.example/asset-lab/api/v1/oauth/libtv/callback', return_paths=('/', '/asset-lab/'))
        self.oauth = LibTVOAuth(self.config, self.http)

    def code(self, expected, function):
        with self.assertRaises(AuthError) as result:
            function()
        self.assertEqual(expected, result.exception.code)

    def test_loopback_requires_explicit_developer_option(self):
        self.code('PROVIDER_UNCONFIGURED', lambda: OAuthConfig('http://127.0.0.1:18872/api/v1/oauth/libtv/callback'))
        value = OAuthConfig('http://127.0.0.1:18872/api/v1/oauth/libtv/callback', allow_loopback_development=True)
        self.assertTrue(value.allow_loopback_development)
        self.code('PROVIDER_UNCONFIGURED', lambda: OAuthConfig('http://website.example/api/v1/oauth/libtv/callback', allow_loopback_development=True))

    def test_configuration_rejects_redirect_credentials_query_fragment_traversal(self):
        for uri in ('https://user:pass@website.example/api/v1/oauth/libtv/callback',
                    'https://website.example/api/v1/oauth/libtv/callback?next=other',
                    'https://website.example/api/v1/oauth/libtv/callback#fragment',
                    'https://website.example/../api/v1/oauth/libtv/callback'):
            self.code('PROVIDER_UNCONFIGURED', lambda u=uri: OAuthConfig(u))

    def test_discovery_rejects_foreign_issuer_and_untrusted_token_endpoint(self):
        for key, value in (('issuer', 'https://evil.invalid/'), ('token_endpoint', 'https://evil.invalid/token'),
                           ('authorization_endpoint', 'http://mcp.liblib.tv/authorize'),
                           ('token_endpoint', 'https://mcp.liblib.tv@evil.invalid/token')):
            saved = self.http.metadata[key]
            self.http.metadata[key] = value
            self.code('PROVIDER_PROTOCOL_ERROR', self.oauth.discover)
            self.http.metadata[key] = saved

    def test_discovery_rejects_missing_pkce_or_non_list_metadata(self):
        for key, value in (('code_challenge_methods_supported', ['plain']), ('scopes_supported', None),
                           ('grant_types_supported', 'authorization_code')):
            saved = self.http.metadata[key]
            self.http.metadata[key] = value
            self.code('PROVIDER_PROTOCOL_ERROR', self.oauth.discover)
            self.http.metadata[key] = saved

    def test_discovery_uses_challenge_resource_and_advertised_read_scope(self):
        self.assertEqual(ISSUER, self.oauth.discover()['issuer'])
        self.assertEqual(RESOURCE, self.http.calls[0][1])
        self.assertEqual(RESOURCE_METADATA, self.http.calls[1][1])
        self.http.metadata['scopes_supported'] = ['libtv:task:write']
        self.code('PROVIDER_SCOPE_UNAVAILABLE', self.oauth.discover)

    def test_wrong_resource_metadata_challenge_is_not_followed(self):
        self.http.override[RESOURCE] = HTTPResult(401, {}, {'WWW-Authenticate': 'Bearer resource_metadata="http://127.0.0.1/admin"'})
        self.code('PROVIDER_PROTOCOL_ERROR', self.oauth.discover)
        self.assertEqual(1, len(self.http.calls))

    def test_dcr_rejection_is_sanitized_and_not_loopback_fallback(self):
        metadata = self.oauth.discover()
        self.http.override[ISSUER + 'register'] = HTTPResult(400, {'error': 'invalid_redirect_uri', 'error_description': 'secret upstream body'})
        self.code('PROVIDER_REGISTRATION_REJECTED', lambda: self.oauth.register(metadata))
        self.assertNotIn('secret', AuthError('PROVIDER_REGISTRATION_REJECTED').message)
        self.assertEqual([self.config.redirect_uri], json.loads(self.http.calls[-1][2])['redirect_uris'])

    def test_dcr_response_must_match_exact_redirect_and_none_auth(self):
        metadata = self.oauth.discover()
        for body in ({'client_id': 'x', 'redirect_uris': ['https://other.example/'], 'token_endpoint_auth_method': 'none'},
                     {'client_id': 'x', 'redirect_uris': [self.config.redirect_uri], 'token_endpoint_auth_method': 'client_secret_post'},
                     {'client_id': 'x', 'redirect_uris': [self.config.redirect_uri], 'token_endpoint_auth_method': 'none', 'client_secret': 'secret'}):
            self.http.override[ISSUER + 'register'] = HTTPResult(201, body)
            self.code('PROVIDER_PROTOCOL_ERROR', lambda: self.oauth.register(metadata))

    def test_preregistered_confidential_client_does_not_need_dcr(self):
        metadata = self.oauth.discover()
        client = ClientRegistration('synthetic:id', self.config.redirect_uri, 'client_secret_basic', 'synthetic:secret')
        self.oauth.validate_registration(client, metadata)
        self.oauth.exchange(metadata, client, 'code', 'verifier', 1)
        call = self.http.calls[-1]
        self.assertTrue(call[3]['Authorization'].startswith('Basic '))
        self.assertNotIn('client_secret', parse_qs(call[2].decode()))
        self.assertNotIn('synthetic', repr(client))

    def test_bad_token_responses_fail_closed(self):
        good = {'access_token': 'synthetic-token', 'expires_in': 3600, 'token_type': 'Bearer'}
        for changed in ({'access_token': 'bad\r\nHeader: secret'}, {'access_token': '非ASCII'},
                        {'token_type': 'MAC'}, {'expires_in': None}, {'expires_in': True},
                        {'expires_in': float('nan')}, {'scope': 'libtv:project:write'}, {'refresh_token': 1}):
            self.code('PROVIDER_PROTOCOL_ERROR', lambda c=changed: self.oauth._tokens(HTTPResult(200, dict(good, **c)), 1))

    def test_refresh_preserves_old_refresh_if_not_rotated(self):
        value = self.oauth._tokens(HTTPResult(200, {'access_token': 'new', 'token_type': 'Bearer', 'expires_in': 10}),
                                   1, {'refresh_token': 'old'})
        self.assertEqual('old', value['refresh_token'])

    def test_no_public_endpoint_accepts_redirects_or_alternate_hosts(self):
        http = OfficialHTTP()
        self.assertIsNone(_NoRedirects().redirect_request(None, None, 302, '', {}, 'https://evil.invalid'))
        for url in ('http://mcp.liblib.tv/token', 'https://evil.invalid/token', 'https://mcp.liblib.tv:443/token',
                    'https://mcp.liblib.tv/token?secret=1', 'https://['):
            self.code('PROVIDER_PROTOCOL_ERROR', lambda u=url: http.request('GET', u))

    def test_http_timeout_and_oversized_response_are_redacted(self):
        class Opener:
            def open(self, *a, **kw): raise URLError('a secret signed URL')
        http = OfficialHTTP()
        http._opener = Opener()
        self.code('PROVIDER_UNAVAILABLE', lambda: http.request('GET', RESOURCE))
        class Response(io.BytesIO):
            status = 200
            headers = {'Content-Type': 'application/json'}
        class Large:
            def open(self, *a, **kw): return Response(b'x' * 101)
        http = OfficialHTTP(max_bytes=100)
        http._opener = Large()
        self.code('PROVIDER_RESPONSE_TOO_LARGE', lambda: http.request('GET', RESOURCE))

    def test_large_canvas_response_does_not_expand_oauth_metadata_limit(self):
        payload=json.dumps({'result':{'project':'x'*(1200*1024)}}).encode()
        class Response(io.BytesIO):
            status=200
            headers={'Content-Type':'application/json'}
        class Opener:
            def open(self,*args,**kwargs):return Response(payload)
        http=OfficialHTTP();http._opener=Opener()
        self.assertEqual(http.mcp_max_bytes,16*1024*1024)
        self.assertEqual(len(http.request('POST',RESOURCE).data['result']['project']),1200*1024)
        self.code('PROVIDER_RESPONSE_TOO_LARGE',lambda:http.request('GET','https://mcp.liblib.tv/token'))

    def test_sse_returns_first_response_without_waiting_for_connection_eof(self):
        class Response(io.BytesIO):
            status = 200
            headers = {'content-type': 'text/event-stream'}
            def read(self, *args): raise AssertionError('SSE must not wait for EOF')
        class Opener:
            def open(self, *a, **kw):
                return Response(b': keepalive\n\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n')
        http = OfficialHTTP()
        http._opener = Opener()
        self.assertEqual({'ok': True}, http.request('POST', RESOURCE).data['result'])


class MCPFixture:
    def __init__(self):
        self.methods = []
        self.annotations = {'readOnlyHint': True, 'destructiveHint': False}
        self.schema = {'type': 'object', 'properties': {}}
        self.subject = 'synthetic-person'

    def request(self, method, url, *, data=None, headers=None):
        assert url == RESOURCE
        assert headers['Authorization'] == 'Bearer synthetic-token'
        request = json.loads(data)
        self.methods.append(request['method'])
        if request['method'] == 'notifications/initialized':
            return HTTPResult(202, {})
        if request['method'] == 'initialize':
            result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}}
        elif request['method'] == 'tools/list':
            result = {'tools': [{'name': 'synthetic_identity_read', 'annotations': self.annotations, 'inputSchema': self.schema}]}
        elif request['method'] == 'tools/call':
            result = {'structuredContent': {'user': {'subject': self.subject, 'name': '合成账号'}}}
        else:
            raise AssertionError('Unexpected RPC')
        return HTTPResult(200, {'jsonrpc': '2.0', 'id': request['id'], 'result': result}, {'Mcp-Session-Id': 'synthetic-session'})


class MCPIdentityTests(unittest.TestCase):
    def setUp(self):
        self.http = MCPFixture()
        self.contract = IdentityReadContract('synthetic_identity_read', ('user', 'subject'), ('user', 'name'), 'test-fixture-only')

    def test_only_explicitly_audited_read_tool_can_supply_subject(self):
        verifier = ReadOnlyMCPIdentityVerifier(self.http, self.contract)
        identity = verifier.verify({'access_token': 'synthetic-token'})
        self.assertEqual('synthetic-person', identity.subject)
        self.assertEqual(['initialize', 'notifications/initialized', 'tools/list', 'tools/call'], self.http.methods)

    def test_missing_readonly_hint_blocks_tool_call(self):
        for annotations in ({}, {'readOnlyHint': True}, {'readOnlyHint': False, 'destructiveHint': False}):
            self.http.annotations = annotations
            self.http.methods = []
            with self.assertRaises(AuthError):
                ReadOnlyMCPIdentityVerifier(self.http, self.contract).verify({'access_token': 'synthetic-token'})
            self.assertNotIn('tools/call', self.http.methods)

    def test_tool_requiring_account_or_space_arguments_is_not_guessed(self):
        self.http.schema['required'] = ['spaceId']
        with self.assertRaises(AuthError):
            ReadOnlyMCPIdentityVerifier(self.http, self.contract).verify({'access_token': 'synthetic-token'})
        self.assertNotIn('tools/call', self.http.methods)

    def test_empty_subject_is_never_replaced_with_a_display_name(self):
        self.http.subject = ''
        with self.assertRaises(AuthError):
            ReadOnlyMCPIdentityVerifier(self.http, self.contract).verify({'access_token': 'synthetic-token'})


if __name__ == '__main__':
    unittest.main()
