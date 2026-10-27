import importlib.util
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
import json

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_release as release_tests
from deploy.preview import create_server
from deploy import release

class HttpReleaseTest(release_tests.ReleasesTest):
    # Do not rerun base unit methods; these tests add real HTTP assertions.
    def test_http_root_and_subpath_upgrade_rollback_and_invalid_manifest(self):
        for base in ['/', '/asset-lab/']:
            with self.subTest(base=base):
                self.base_path=base;self.origin='http://127.0.0.1'
                self.root=self.temp/('root-http' if base=='/' else 'subpath-http')
                tag='root' if base=='/' else 'sub'
                self.install(build=tag+'-a');first=self.current()
                server=create_server(self.root,public_base_path=base,channel='stable')
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                origin='http://127.0.0.1:'+str(server.server_port)
                def get(path):
                    with urlopen(origin+path) as r:return r.headers,r.read()
                try:
                    headers,html=get(base);self.assertEqual(headers['Cache-Control'],'no-store');self.assertIn(b'asset-lab-build',html)
                    headers,raw=get(base+'api/v1/version');self.assertEqual(json.loads(raw)['data']['buildId'],tag+'-a');self.assertIn('no-store',headers['Cache-Control'])
                    self.install('1.1.0',tag+'-b')
                    _,raw=get(base+'api/v1/releases/latest?channel=stable');self.assertEqual(json.loads(raw)['data']['buildId'],tag+'-b')
                    _,raw=get(base+'api/v1/version');self.assertEqual(json.loads(raw)['data']['buildId'],tag+'-a')
                    headers,_=get(base+'releases/'+first.name+'/build-info.mjs');self.assertIn('immutable',headers['Cache-Control'])
                    release.rollback(self.args());_,raw=get(base+'api/v1/releases/latest?channel=stable');self.assertEqual(json.loads(raw)['data']['buildId'],tag+'-a')
                    for path in [base+'releases/'+first.name+'/%2e%2e/release.json',base+'api/v1/not-present',base+'data/customer-sentinel.txt']:
                        with self.assertRaises(HTTPError) as caught:get(path)
                        caught.exception.close()
                    manifest=self.current()/'release.json';manifest.chmod(0o644);manifest.write_text('invalid')
                    with self.assertRaises(HTTPError) as err:get(base+'api/v1/releases/latest?channel=stable')
                    self.assertEqual(err.exception.code,503);self.assertIn('no-store',err.exception.headers['Cache-Control']);err.exception.close()
                finally:server.shutdown();server.server_close();thread.join()

# Retain only the added HTTP test in this subclass.
for name in tuple(vars(release_tests.ReleasesTest)):
    if name.startswith('test_'):
        setattr(HttpReleaseTest,name,None)

if __name__=='__main__':unittest.main()
