"""Official wire schemas, completely synthetic response values, no network calls."""
import copy
import json
from pathlib import Path
import secrets
import tempfile
import unittest

from backend.auth import ProviderService
from backend.auth.errors import AuthError
from backend.auth.secrets import AesGcmSecretCodec
from backend.providers.libtv_bound_tools import BoundMCPTools
from backend.providers.libtv_oauth import HTTPResult, LibTVOAuth, OAuthConfig, RESOURCE
from helpers import Clock, FakeHTTP, SqliteTestRepository, callback_for, context
import test_storage_bridge as storage_bridge

try:
    from backend.spaces.service import SpaceService
    from backend.storage import SelectionRepository
except ModuleNotFoundError:
    SpaceService = None

try:
    from backend.generation.types import AuthorizedMCP
except ModuleNotFoundError:
    AuthorizedMCP = None

FIXTURES = Path(__file__).parent / 'fixtures'


class OfficialAccountHTTP(FakeHTTP):
    def __init__(self):
        super().__init__()
        self.account = json.loads((FIXTURES / 'account-user.synthetic.json').read_text())
        self.tools = json.loads((FIXTURES / 'libtv-tools-public-2026-10-27.json').read_text())['tools']
        self.tool_calls = []
        self.before_read = None
        self.response = {'synthetic': True}

    def request(self, method, url, *, data=None, headers=None):
        if method != 'POST' or url != RESOURCE:
            return super().request(method, url, data=data, headers=headers)
        request = json.loads(data)
        rpc_method = request['method']
        if rpc_method == 'notifications/initialized':
            return HTTPResult(202, {})
        if rpc_method == 'initialize':
            result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}}
        elif rpc_method == 'tools/list':
            result = {'tools': copy.deepcopy(self.tools)}
        elif rpc_method == 'tools/call':
            self.tool_calls.append(copy.deepcopy(request['params']))
            if request['params']['name'] == 'account_user':
                if self.before_read:
                    self.before_read()
                result = {'structuredContent': copy.deepcopy(self.account)}
            else:
                result = {'structuredContent': copy.deepcopy(self.response)}
        else:
            raise AssertionError('Unexpected RPC')
        return HTTPResult(200, {'jsonrpc': '2.0', 'id': request['id'], 'result': result})


class OfficialAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock, self.http, self.ctx = Clock(), OfficialAccountHTTP(), context()
        self.repo = SqliteTestRepository(Path(self.tmp.name) / 'test.db')
        self.oauth = LibTVOAuth(OAuthConfig('https://website.example/api/v1/oauth/libtv/callback'), self.http)
        self.service = ProviderService(self.repo, AesGcmSecretCodec({'test': secrets.token_bytes(32)}, 'test'),
                                       self.oauth, clock=self.clock)

    def connect(self):
        attempt = self.service.begin_authorization(self.ctx)
        self.service.complete_authorization(self.ctx, callback_for(attempt))
        result = self.service.get_attempt(self.ctx, attempt['attemptId'])
        self.assertEqual('completed', result['status'], result)
        return self.service.get_account(self.ctx, result['providerAccountId'])

    def owner(self, account):
        return {'tenantId': self.ctx['tenantId'], 'provider': 'libtv',
                'providerAccountId': account['id'], 'providerSubject': account['identity']['subject'],
                'spaceId': '200001', 'spaceKind': 'personal'}

    def code(self, expected, function):
        with self.assertRaises(AuthError) as result:
            function()
        self.assertEqual(expected, result.exception.code)

    def test_default_callback_uses_user_uuid_not_numeric_account_or_user_id(self):
        account = self.connect()
        self.assertEqual(self.http.account['user']['uuid'], account['identity']['subject'])
        self.assertEqual('合成测试用户', account['identity']['displayName'])
        self.assertTrue(account['capabilities']['spaces'])
        self.assertFalse(account['capabilities']['quota'])
        self.assertEqual([{'name': 'account_user', 'arguments': {}}], self.http.tool_calls)

    def test_lists_both_personal_and_inactive_team_without_selecting_either(self):
        account = self.connect()
        self.http.account['accounts']['accounts'][1]['memberAccount']['effective'] = False
        client = self.service.account_client_for(self.ctx, self.owner(account))
        result = client.list_spaces()
        self.assertEqual(['200001', '200002'], [row['id'] for row in result['items']])
        self.assertEqual(['personal', 'team'], [row['kind'] for row in result['items']])
        self.assertEqual(['available', 'available'], [row['access'] for row in result['items']])
        self.assertNotIn('remaining', json.dumps(result))
        self.assertTrue(all(call == {'name': 'account_user', 'arguments': {}} for call in self.http.tool_calls))

    def test_changed_authoritative_subject_cannot_supply_spaces_for_old_account(self):
        account = self.connect()
        self.http.account['user']['uuid'] = 'different-synthetic-user'
        client = self.service.account_client_for(self.ctx, self.owner(account))
        self.code('PROVIDER_IDENTITY_MISMATCH', client.list_spaces)

    def test_unknown_type_and_incomplete_membership_never_create_default_space(self):
        account = self.connect()
        original = copy.deepcopy(self.http.account)
        client = self.service.account_client_for(self.ctx, self.owner(account))
        self.http.account['accounts']['accounts'][0]['accountType'] = 99
        self.code('PROVIDER_CAPABILITY_UNAVAILABLE', client.list_spaces)
        self.http.account = original
        del self.http.account['accounts']
        self.code('PROVIDER_PROTOCOL_ERROR', client.list_spaces)

    def test_duplicate_or_boolean_account_ids_fail_closed(self):
        account = self.connect()
        rows = self.http.account['accounts']['accounts']
        client = self.service.account_client_for(self.ctx, self.owner(account))
        rows[1]['accountId'] = rows[0]['accountId']
        self.code('PROVIDER_PROTOCOL_ERROR', client.list_spaces)
        rows[1]['accountId'] = True
        self.code('PROVIDER_PROTOCOL_ERROR', client.list_spaces)

    def test_personal_membership_owned_by_another_subject_is_rejected(self):
        account = self.connect()
        self.http.account['accounts']['accounts'][0]['ownerUuid'] = 'different-synthetic-user'
        client = self.service.account_client_for(self.ctx, self.owner(account))
        self.code('PROVIDER_IDENTITY_MISMATCH', client.list_spaces)

    def test_removal_during_remote_read_prevents_returning_late_spaces(self):
        account = self.connect()
        client = self.service.account_client_for(self.ctx, self.owner(account))
        self.http.before_read = lambda: self.service.remove_account(self.ctx, account['id'], account['version'])
        self.code('PROVIDER_AUTHORIZATION_REQUIRED', client.list_spaces)

    def test_read_only_grant_blocks_adapter_model_and_generation_before_factory(self):
        account = self.connect()
        called = []
        self.service.operation_adapter_factory = lambda **kw: called.append(kw)
        client = self.service.client_for(self.ctx, self.owner(account))
        for operation in (client.list_models, client.prepare, client.submit, client.lookup, client.download):
            self.code('PROVIDER_SCOPE_UNAVAILABLE', operation)
        self.assertEqual([], called)

    def test_transport_enforces_live_tool_scope_and_immutable_space(self):
        account = self.connect()
        owner = self.owner(account)
        transport = BoundMCPTools(self.service, self.ctx, owner)
        owner['spaceId'] = '200002'
        self.code('OWNERSHIP_MISMATCH', lambda: transport.call_tool('account_user', {}, space_id='200002'))
        self.code('PROVIDER_SCOPE_UNAVAILABLE', lambda: transport.call_tool('search_models', {'action': 'search'}, space_id='200001'))
        self.code('PROVIDER_SCOPE_UNAVAILABLE', lambda: transport.call_tool('generation_submit', {}, space_id='200001'))
        self.assertTrue(all(call['name'] == 'account_user' for call in self.http.tool_calls))

    def test_transport_does_not_trust_write_tool_claiming_account_read_scope(self):
        account = self.connect()
        account_tool = next(t for t in self.http.tools if t['name'] == 'account_user')
        # Keep the identity reader safe and add a distinct malicious tool declaration.
        unexpected = copy.deepcopy(account_tool)
        unexpected['name'] = 'unexpected_write'
        unexpected['annotations']['readOnlyHint'] = False
        self.http.tools.append(unexpected)
        transport = BoundMCPTools(self.service, self.ctx, self.owner(account))
        self.code('PROVIDER_SCOPE_UNAVAILABLE', lambda: transport.call_tool('unexpected_write', {}, space_id='200001'))
        self.assertNotIn('unexpected_write', [call['name'] for call in self.http.tool_calls])

    def test_adapter_gets_copy_of_owner_and_tool_interface_without_tokens(self):
        account = self.connect()
        seen = {}
        class Adapter:
            def quota(self): return {'state': 'unknown', 'remaining': None}
        def factory(**kwargs):
            seen.update(kwargs)
            return Adapter()
        self.service.operation_adapter_factory = factory
        client = self.service.client_for(self.ctx, self.owner(account))
        self.assertIsNone(client.quota()['remaining'])
        self.assertEqual({'ownership', 'tools'}, set(seen))
        self.assertNotIn('synthetic-access', repr(seen))
        seen['ownership']['spaceId'] = 'other'
        self.assertIsNone(client.quota()['remaining'])

    def test_adapter_rejects_nonmember_space_and_wrong_kind(self):
        account = self.connect()
        self.service.operation_adapter_factory = lambda **kw: self.fail('Factory must not receive mismatched ownership')
        for change in ({'spaceId': 'not-a-member'}, {'spaceKind': 'team'}):
            client = self.service.client_for(self.ctx, dict(self.owner(account), **change))
            self.code('OWNERSHIP_MISMATCH', client.quota)

    @unittest.skipIf(AuthorizedMCP is None, 'Generation module types are required for bind-port integration.')
    def test_bind_authorize_port_revalidates_permission_and_revocation(self):
        account = self.connect()
        captured = {}
        class BoundAdapter:
            def __init__(self, authorize): self.authorize = authorize
            def quota(self):
                port = self.authorize({'libtv:account:read'})
                captured['port'] = port
                self_result = port.call_tool('account_user', {})
                return {'state': 'unknown', 'remaining': None, 'readSucceeded': bool(self_result['structuredContent']['user'])}
        class Adapter:
            def bind(self, *, ownership, authorize):
                captured['authorize'] = authorize
                return BoundAdapter(authorize)
        self.service.operation_adapter = Adapter()
        client = self.service.client_for(self.ctx, self.owner(account))
        self.assertTrue(client.quota()['readSucceeded'])
        self.assertIsInstance(captured['port'], AuthorizedMCP)
        self.assertEqual(frozenset({'libtv:account:read'}), captured['port'].granted_scopes)
        self.code('PROVIDER_SCOPE_UNAVAILABLE', lambda: captured['authorize']({'libtv:task:write'}))
        captured['port'].ownership['spaceId'] = 'unrelated'
        self.assertIn('structuredContent', captured['port'].call_tool('account_user', {}))
        self.service.remove_account(self.ctx, account['id'], account['version'])
        self.code('PROVIDER_AUTHORIZATION_REQUIRED', lambda: captured['port'].call_tool('account_user', {}))


@unittest.skipIf(SpaceService is None or storage_bridge.Store is None,
                 'Modules 3 and 4 are required for actual Store/SpaceService integration.')
class SpaceProjectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        storage_bridge.StorageBridgeTests.setUp(self)
        self.http = OfficialAccountHTTP()
        self.oauth = LibTVOAuth(OAuthConfig('https://website.example/api/v1/oauth/libtv/callback'), self.http)
        self.service = ProviderService(self.repo, self.codec, self.oauth, clock=self.clock)

    def test_official_projection_supports_persisted_selection_and_unknown_quota(self):
        account = storage_bridge.StorageBridgeTests.connect(self)
        from datetime import datetime, timezone
        spaces = SpaceService(self.service, SelectionRepository(self.store),
                              clock=lambda: datetime.fromtimestamp(self.clock(), timezone.utc))
        result = spaces.list_spaces(self.ctx, account['id'])
        self.assertEqual(['personal', 'team'], [row['kind'] for row in result['items']])
        selected = spaces.set_selection(self.ctx, providerAccountId=account['id'],
                                        spaceId='200002', expectedRevision=0)
        self.assertEqual('200002', selected['spaceId'])
        quota = spaces.quota(self.ctx, account['id'], '200002')
        self.assertEqual('unknown', quota['state'])
        self.assertIsNone(quota['remaining'])
        self.assertEqual({'account_user'}, {call['name'] for call in self.http.tool_calls})


if __name__ == '__main__':
    unittest.main()
