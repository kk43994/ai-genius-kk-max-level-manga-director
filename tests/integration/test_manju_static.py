import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from backend.app import APIError, Config, create_app
from local_client.launch import provision
from manju_client.launch import configure_workbench

class ManjuStaticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.public=self.root/'public';self.public.mkdir()
        (self.public/'studio').mkdir()
        (self.public/'studio/actor.glb').write_bytes(b'glTF-test-content')
        (self.public/'studio/index.html').write_text('<html><script type="importmap">{"imports":{}}</script></html>')
        (self.public/'studio/private.json').write_text('{"private":true}')
        (self.root/'outside.json').write_text('{"private":true}')
        (self.public/'studio/outside.json').symlink_to(self.root/'outside.json')
        files=['studio/actor.glb','studio/index.html','studio/outside.json']
        (self.public/'studio-inventory.json').write_text(json.dumps({'files':{p:'test' for p in files}}))
        key=provision(self.root/'instance')
        self.app=create_app(Config(self.root/'instance/data',port=18878,public_base_path='/workbench/',
                                   secret_key_file=key,local_client=True,frontend_dir=self.public))
        configure_workbench(self.app)

    def request(self,path,method='GET'):
        return self.app.static(SimpleNamespace(path='/workbench/'+path,method=method))

    def test_bundled_model_can_be_read(self):
        response=self.request('studio/actor.glb')
        self.assertEqual(response.body,b'glTF-test-content')
        self.assertEqual(response.headers['Content-Type'],'model/gltf-binary')

    def test_import_map_has_hash_without_inline_script_permission(self):
        policy=self.request('studio/index.html').headers['Content-Security-Policy']
        self.assertIn("script-src 'self' 'sha256-",policy)
        self.assertNotIn("'unsafe-inline'",policy.split('script-src')[1].split(';')[0])

    def test_unlisted_json_and_symlinks_are_not_public(self):
        for path in ('studio/private.json','studio/outside.json','../outside.json'):
            with self.subTest(path=path), self.assertRaises(APIError) as result:
                self.request(path)
            self.assertEqual(result.exception.status,404)

    def test_static_modules_cannot_accept_writes(self):
        with self.assertRaises(APIError) as result:self.request('studio/actor.glb','POST')
        self.assertEqual(result.exception.status,405)

    def test_original_api_and_generation_guard_stay_intact(self):
        self.assertEqual(self.app.config.api_base,'/workbench/api/v1')
        self.assertEqual(self.app.config.local_client,True)
        self.assertEqual(self.app.build_info['product'],'manju-workbench')

if __name__=='__main__':unittest.main()
