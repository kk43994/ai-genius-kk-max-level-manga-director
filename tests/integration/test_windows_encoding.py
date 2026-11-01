"""Exercise startup under non-UTF-8 Windows text defaults, without Windows APIs."""
from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from backend.app import Config, CustomerHTTPServer, create_app
from local_client.launch import provision
from manju_client.launch import configure_workbench


@contextmanager
def windows_text_default(encoding):
    original = Path.open

    def open_path(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
        if 'b' not in mode and encoding in (None, 'locale'):
            encoding = windows_encoding
        return original(path, mode, buffering, encoding, errors, newline)

    windows_encoding = encoding
    with patch.object(Path, 'open', open_path):
        yield


class WindowsEncodingTests(unittest.TestCase):
    def test_catalog_startup_http_and_restart_with_windows_defaults(self):
        for encoding in ('cp936', 'cp1252'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                key = provision(root / 'instance')
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', 0))
                    port = probe.getsockname()[1]
                config = Config(root / 'instance/data', port=port, public_base_path='/asset-lab/', secret_key_file=key, local_client=True, frontend_dir=Path(__file__).resolve().parents[2] / 'frontend')
                with windows_text_default(encoding):
                    app = create_app(config)
                    server = CustomerHTTPServer(app)
                    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
                    thread.start()
                    try:
                        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                        conn.request('GET', '/asset-lab/')
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertIn('资产实验室', response.read().decode('utf-8'))
                        conn.close()
                        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                        conn.request('GET', '/asset-lab/api/v1/session')
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        session = json.loads(response.read())['data']
                        self.assertFalse(session['features']['imageGeneration'])
                        self.assertFalse(session['features']['videoGeneration'])
                        conn.close()
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=2)
                    # Reopening an existing workspace must retain its key and schema.
                    self.assertEqual(provision(root / 'instance'), key)
                    create_app(config)

    def test_manju_inventory_with_non_ascii_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            public = root / 'public'
            public.mkdir()
            (public / 'studio-inventory.json').write_text(json.dumps({'files': {'中文说明.txt': 'test'}}, ensure_ascii=False), encoding='utf-8')
            key = provision(root / 'instance')
            config = Config(root / 'instance/data', port=18878, secret_key_file=key, local_client=True, frontend_dir=public)
            with windows_text_default('cp936'):
                app = create_app(config)
                configure_workbench(app)


if __name__ == '__main__':
    unittest.main()
