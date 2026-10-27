import argparse
from copy import deepcopy
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from deploy import release
from backend.releases import ReleaseService, ReleaseUnavailable, register_routes
from backend.releases.manifest import manifest_valid

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/manifest.json').read_text())


class ReleasesTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='asset-lab-release-test-')).resolve()
        self.source = self.temp / 'source'; (self.source / 'public').mkdir(parents=True)
        (self.source / 'public/index.html').write_text('<!doctype html><html><head><title>Test</title></head><body>synthetic</body></html>')
        self.root, self.data = self.temp / 'releases-root', self.temp / 'persistent'
        self.data.mkdir(); (self.data / 'customer-sentinel.txt').write_text('customer work stays byte-identical')
        self.origin, self.base_path = 'https://kk666.best', '/asset-lab/'
        self.sentinel = release.digest_file(self.data / 'customer-sentinel.txt')

    def tearDown(self):
        for p in self.temp.rglob('*'):
            if p.is_dir() and not p.is_symlink(): p.chmod(0o755)
        shutil.rmtree(self.temp)

    def bundle(self, version='1.0.0', build='synthetic-a', schema=1, channel='stable', source=None):
        m = deepcopy(FIXTURE); m.update(version=version, buildId=build, dataSchemaVersion=schema, channel=channel, entryUrl=self.base_path)
        if channel == 'preview': m['minCompatibleClient'] = '0.0.0'
        source = source or self.source
        spec = {'schemaVersion':1, 'sourceDir':str(source), 'include':{'public':'public'},
                'buildCommand':[sys.executable,'-c',"from pathlib import Path; Path('public/built.txt').write_text('build output')"],
                'testCommand':[sys.executable,'-c',"from pathlib import Path; assert '<head>' in Path('public/index.html').read_text(); assert Path('public/built.txt').read_text() == 'build output'"],
                'release':m, 'origin':self.origin, 'basePath':self.base_path}
        specpath=self.temp/(build+'-spec.json');specpath.write_text(json.dumps(spec))
        output=self.temp/(build+'.tar.gz')
        result=release.build_bundle(specpath,output)
        return output,result['sha256']

    def args(self,bundle=None,digest=None,channel='stable',hooks=None):
        return argparse.Namespace(root=str(self.root),data_root=str(self.data),channel=channel,origin=self.origin,base_path=self.base_path,
                                  bundle=str(bundle),sha256=digest,allow_stable=True,hooks=str(hooks) if hooks else None)

    def install(self,*args,**kw):
        bundle,digest=self.bundle(*args,**kw)
        return release.install(self.args(bundle,digest,channel=kw.get('channel','stable')))

    def current(self): return release.pointer(self.root,'stable','current')

    def test_build_install_upgrade_rollback_preserves_data_and_old_assets(self):
        self.install();first=self.current(); self.install('1.1.0','synthetic-b');second=self.current()
        self.assertNotEqual(first,second)
        self.assertTrue((first/'public/index.html').is_file())
        self.assertEqual(release.pointer(self.root,'stable','previous'),first)
        self.assertEqual(first.stat().st_mode & 0o222,0)
        html=(second/'public/index.html').read_text();self.assertIn('/asset-lab/releases/1.1.0--synthetic-b/',html)
        self.assertIn('id="asset-lab-build"',html)
        release.rollback(self.args());self.assertEqual(self.current(),first)
        self.assertEqual(release.digest_file(self.data/'customer-sentinel.txt'),self.sentinel)
        self.assertEqual(len(list((self.root/'audit').glob('*.json'))),3)

    def test_bundle_checksum_failure_never_switches_current(self):
        self.install();first=self.current();bundle,digest=self.bundle('1.1.0','bad-digest')
        with self.assertRaisesRegex(ValueError,'SHA-256'): release.install(self.args(bundle,'0'*64))
        self.assertEqual(self.current(),first)

    def test_inventory_tamper_rejected_even_with_valid_transport_hash(self):
        bundle,digest=self.bundle();stage=self.temp/'altered';stage.mkdir();release.extract_bundle(bundle,digest,stage)
        (stage/'public/index.html').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'inventory mismatch'): release.verify_directory(stage,self.origin,self.base_path)

    def test_secret_runtime_and_symlink_inputs_refused(self):
        for name in ['.env','state.sqlite3','cookies.json','uploads/person.png']:
            p=self.source/'public'/name;p.parent.mkdir(exist_ok=True);p.write_text('synthetic')
            with self.assertRaisesRegex(ValueError,'Sensitive/runtime'): self.bundle(build='blocked-'+str(len(name)))
            p.unlink()
            if p.parent.name=='uploads':p.parent.rmdir()
        (self.source/'public/escape.js').symlink_to('/etc/hosts')
        with self.assertRaisesRegex(ValueError,'symlinks'):self.bundle(build='symlink')

    def test_private_key_content_is_refused_without_echoing_secret(self):
        (self.source/'public/accidental.txt').write_text('-----BEGIN PRIVATE KEY-----\nsynthetic-not-a-key')
        with self.assertRaisesRegex(ValueError,'Credential pattern'):self.bundle()

    def test_archive_traversal_links_and_duplicate_entries_rejected(self):
        for kind in ('traversal','symlink','duplicate'):
            p=self.temp/(kind+'.tar.gz')
            with tarfile.open(p,'w:gz') as tar:
                name='../escape' if kind=='traversal' else 'public/file'
                info=tarfile.TarInfo(name);info.size=1
                if kind=='symlink':info.type=tarfile.SYMTYPE;info.linkname='/etc/hosts';info.size=0
                tar.addfile(info,io.BytesIO(b'x'))
                if kind=='duplicate':tar.addfile(info,io.BytesIO(b'x'))
            stage=self.temp/(kind+'-stage');stage.mkdir()
            with self.assertRaises(ValueError):release.extract_bundle(p,release.digest_file(p),stage)
        self.assertFalse((self.temp/'escape').exists())

    def test_stable_gate_and_channel_mismatch(self):
        bundle,digest=self.bundle();args=self.args(bundle,digest);args.allow_stable=False
        with self.assertRaisesRegex(ValueError,'--allow-stable'):release.install(args)
        args.allow_stable=True;args.channel='preview'
        with self.assertRaisesRegex(ValueError,'channel mismatch'):release.install(args)

    def test_schema_change_is_refused_and_data_left_intact(self):
        self.install();first=self.current();bundle,digest=self.bundle('2.0.0','schema2',schema=2)
        with self.assertRaisesRegex(ValueError,'schema change'):release.install(self.args(bundle,digest))
        self.assertEqual(self.current(),first)
        self.assertEqual(release.digest_file(self.data/'customer-sentinel.txt'),self.sentinel)

    def test_failed_health_probe_restores_previous_pointer(self):
        self.install();old=self.current();bundle,digest=self.bundle('1.1.0','bad-health')
        hook=self.temp/'hooks.json';hook.write_text(json.dumps({'probeCommand':[sys.executable,'-c',"import os,sys; sys.exit(1 if os.environ['ASSET_LAB_RELEASE_DIR'].endswith('bad-health') else 0)"]}))
        with self.assertRaises(Exception):release.install(self.args(bundle,digest,hooks=hook))
        self.assertEqual(self.current(),old);self.assertFalse((self.root/'channels/stable/pending.json').exists())
        self.assertTrue(any(json.loads(x.read_text())['status']=='reverted' for x in (self.root/'audit').glob('*.json')))

    def test_lock_conflict_does_not_switch(self):
        self.install();old=self.current();bundle,digest=self.bundle('1.1.0','locked')
        with release.release_lock(self.root):
            with self.assertRaisesRegex(ValueError,'owns the lock'):release.install(self.args(bundle,digest))
        self.assertEqual(self.current(),old)

    def test_same_id_is_immutable_and_identical_retry_is_noop(self):
        bundle,digest=self.bundle();args=self.args(bundle,digest)
        release.install(args);self.assertEqual(release.install(args)['status'],'unchanged')
        stage=self.temp/'different';stage.mkdir();release.extract_bundle(bundle,digest,stage)
        m=json.loads((stage/'release.json').read_text());m['releaseNotes']=['different immutable identity'];(stage/'release.json').write_bytes(release.encoded(m))
        altered=self.temp/'different.tar.gz'
        with tarfile.open(altered,'w:gz') as tar:
            for p in stage.rglob('*'):tar.add(p,arcname=p.relative_to(stage).as_posix(),recursive=False)
        with self.assertRaisesRegex(ValueError,'Immutable'):release.install(self.args(altered,release.digest_file(altered)))

    def test_crash_journal_recovery_restores_old_and_previous(self):
        self.install();old=self.current();self.install('1.1.0','b');new=self.current()
        folder=self.root/'channels/stable'
        tx={'old':old.name,'new':new.name,'oldPrevious':None,'channel':'stable','operation':'install'}
        release.atomic_json(folder/'pending.json',tx)
        with self.assertRaisesRegex(ValueError,'Unfinished'):release.rollback(self.args())
        release.recover(self.args());self.assertEqual(self.current(),old)
        self.assertIsNone(release.pointer(self.root,'stable','previous'))

    def test_api_current_is_running_snapshot_latest_tracks_switch_and_bad_manifest(self):
        self.install();old=self.current()
        service=ReleaseService(release_root=self.root,running_manifest=old/'release.json',origin=self.origin,base_path=self.base_path)
        self.assertEqual(service.current()['version'],'1.0.0')
        self.install('1.1.0','new-api');self.assertEqual(service.latest()['version'],'1.1.0')
        self.assertEqual(service.current()['version'],'1.0.0')
        release.rollback(self.args());self.assertEqual(service.latest()['version'],'1.0.0')
        path=self.current()/'release.json';path.chmod(0o644);path.write_text('{bad')
        with self.assertRaises(ReleaseUnavailable):service.latest()

    def test_contract_router_envelopes_headers_and_unconfigured_failure(self):
        class Router:
            def __init__(self):self.routes={}
            def add(self,method,path,handler):self.routes[path]=handler
        self.install();service=ReleaseService(release_root=self.root,running_manifest=self.current()/'release.json',origin=self.origin,base_path=self.base_path)
        router=Router();register_routes(router,{'releases':service})
        response=router.routes['/api/v1/version']({'requestId':'test-request'}, {})
        self.assertEqual(response.status,200);self.assertEqual(response.body['meta']['apiVersion'],1);self.assertIn('no-store',response.headers['Cache-Control'])
        bad=router.routes['/api/v1/releases/latest']({'query':{'channel':'../escape'}},{});self.assertEqual(bad.status,422)
        router=Router();register_routes(router,{})
        self.assertEqual(router.routes['/api/v1/version']({},{}).status,503)

    def test_root_mount_build_and_api_validation(self):
        self.base_path='/';self.install();m=release.verify_directory(self.current(),self.origin,'/')
        manifest_valid(m,self.origin,'/');self.assertEqual(m['entryUrl'],'/')
        self.assertIn('<base href="/releases/',(self.current()/'public/index.html').read_text())

    def test_data_and_release_overlap_or_unknown_root_refused(self):
        with self.assertRaisesRegex(ValueError,'separate'):release.initialize(self.root,self.root/'data')
        self.root.mkdir();(self.root/'someone-else.txt').write_text('do not touch')
        with self.assertRaisesRegex(ValueError,'unmarked'):release.initialize(self.root,self.data)

    def test_build_and_test_failures_do_not_produce_artifact(self):
        self.bundle();p=self.temp/'synthetic-a-spec.json';s=json.loads(p.read_text());s['testCommand']=[sys.executable,'-c','raise SystemExit(9)'];p.write_text(json.dumps(s))
        with self.assertRaises(Exception):release.build_bundle(p,self.temp/'failed.tar.gz')
        self.assertFalse((self.temp/'failed.tar.gz').exists())

    def test_legitimate_session_code_modules_are_not_mistaken_for_runtime_credentials(self):
        for name in ['server/backend/sessions', 'server/backend/sessions/__init__.py', 'server/backend/auth/tokens.py']:
            release.safe_path(name)
        for name in ['server/backend/auth/tokens.json', 'server/backend/sessions/state.sqlite3', 'server/data/customer.json']:
            with self.assertRaises(ValueError): release.safe_path(name)

    def test_backend_activation_without_drain_hooks_refused(self):
        self.bundle();p=self.temp/'synthetic-a-spec.json';s=json.loads(p.read_text());s['include']['server']='server';(self.source/'server').mkdir();(self.source/'server/app.py').write_text('print("synthetic")');p.write_text(json.dumps(s))
        result=release.build_bundle(p,self.temp/'backend.tar.gz')
        with self.assertRaisesRegex(ValueError,'Backend release requires'):release.install(self.args(self.temp/'backend.tar.gz',result['sha256']))

if __name__ == '__main__':unittest.main()
