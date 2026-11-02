"""Update controls retain the normal session/CSRF boundary and task guard."""
from types import SimpleNamespace
import threading
from unittest.mock import Mock

import test_http as fixture
from local_client.updater import register_update_routes


class DesktopUpdateHTTPTests(fixture.HTTPTests):
    def test_update_install_requires_session_csrf_and_no_active_tasks(self):
        updater = Mock()
        updater.snapshot.return_value = {'enabled': True, 'status': 'current'}
        updater.check.return_value = {'enabled': True, 'status': 'checking'}
        updater.install.return_value = {'status': 'installing'}
        tasks = [{'status': 'queued'}]
        self.app.services.tasks = SimpleNamespace(list=lambda *_args, **_kw: {'items': tasks, 'nextCursor': None})
        stopped = threading.Event()
        register_update_routes(self.app, updater, stopped.set)
        path = '/api/v1/local-runtime/update'
        self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request(path + '/check', method='POST', body={}, identity='alpha', csrf=False)[0], 403)
        updater.check.assert_not_called()
        self.assertEqual(self.request(path + '/check', method='POST', body={}, identity='alpha')[0], 200)
        self.assertEqual(self.request(path + '/install', method='POST', body={}, identity='alpha')[0], 409)
        updater.install.assert_not_called()
        self.assertFalse(stopped.is_set())
        tasks.clear()
        self.assertEqual(self.request(path + '/install', method='POST', body={}, identity='alpha')[0], 200)
        self.assertTrue(stopped.wait(1))
        updater.install.assert_called_once()


for name in tuple(vars(fixture.HTTPTests)):
    if name.startswith('test_'):
        setattr(DesktopUpdateHTTPTests, name, None)
