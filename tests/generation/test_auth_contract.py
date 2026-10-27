"""Optional exact committed auth code, synthetic service/transport only.

ASSET_LAB_AUTH_MODULE_ROOT supplies the read-only module-2 checkout. This does not
open its runtime configuration, token store or account files.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import backend
from helpers import Fixture

AUTH_ROOT = os.environ.get('ASSET_LAB_AUTH_MODULE_ROOT')
if AUTH_ROOT:
    backend.__path__.insert(0, str(Path(AUTH_ROOT) / 'backend'))
    from backend.auth.service import BoundProviderClient
    from backend.auth.errors import AuthError
    from backend.providers.libtv_oauth import HTTPResult


@unittest.skipUnless(AUTH_ROOT, 'Set ASSET_LAB_AUTH_MODULE_ROOT to frozen auth commit for adapter integration.')
class AuthPortTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'work' / 'generation-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.f = Fixture(self.tmp.name)
        self.revoked, self.space_checks = False, 0
        parent = self
        class HTTP:
            def request(http, method, url, *, data=None, headers=None):
                rpc = json.loads(data)
                if rpc['method'] == 'notifications/initialized':
                    return HTTPResult(202, {})
                if rpc['method'] == 'initialize':
                    result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}}
                elif rpc['method'] == 'tools/list':
                    result = {'tools': list(parent.f.adapter.catalog._tools.values())}
                elif rpc['method'] == 'tools/call':
                    result = parent.f.transport(rpc['params']['name'], rpc['params']['arguments'])
                else:
                    raise AssertionError('Unexpected protocol method')
                return HTTPResult(200, {'jsonrpc': '2.0', 'id': rpc['id'], 'result': result})
        class Service:
            operation_adapter_factory = None
            operation_adapter = self.f.adapter
            oauth = SimpleNamespace(http=HTTP())
            def _bundle_for(service, ctx, owner):
                if parent.revoked:
                    raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED')
                if owner != parent.f.owner:
                    raise AuthError('OWNERSHIP_MISMATCH')
                return {'tokens': {'access_token': 'synthetic-test-only', 'scope': ' '.join(parent.f.scopes)}}, {}
            def _assert_space(service, ctx, owner):
                service._bundle_for(ctx, owner)
                parent.space_checks += 1
        self.client = BoundProviderClient(Service(), {'tenantId': self.f.ctx.tenantId}, self.f.owner)
        for name in ['socket.create_connection', 'socket.getaddrinfo']:
            guard = patch(name, side_effect=AssertionError('LIVE NETWORK FORBIDDEN'))
            guard.start()
            self.addCleanup(guard.stop)

    def test_exact_bind_authorize_envelope_supports_prepare_and_submit(self):
        self.f.client = self.client
        self.f.prepare()
        self.f.confirm()
        result = self.f.submit()
        self.assertEqual(result['providerReceipt']['taskId'], 'provider_task')
        self.assertGreater(self.space_checks, 3)
        self.assertEqual(self.f.count('generation_submit'), 1)

    def test_official_outer_scope_gate_rejects_account_read_only(self):
        self.f.scopes = frozenset({'libtv:account:read'})
        with self.assertRaises(AuthError) as cm:
            self.client.list_models()
        self.assertEqual(cm.exception.code, 'PROVIDER_SCOPE_UNAVAILABLE')
        self.assertEqual(self.f.transport.calls, [])

    def test_revoked_original_authorization_blocks_bound_client(self):
        self.revoked = True
        with self.assertRaises(AuthError) as cm:
            self.client.list_models()
        self.assertEqual(cm.exception.code, 'PROVIDER_AUTHORIZATION_REQUIRED')
        self.assertEqual(self.f.transport.calls, [])


if __name__ == '__main__':
    unittest.main()
