"""All shipped services on a real HTTP server; no network provider or paid calls."""
import base64
import http.client
import json
import secrets
import tempfile
import threading
import unittest
from pathlib import Path

from backend.app import Config, ConfigurationError, CustomerHTTPServer, ROOT, create_app
from backend.storage import SCHEMA_VERSION


class ComposedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent / "work")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / "secret.key"
        self.key.write_bytes(base64.b64encode(secrets.token_bytes(32))); self.key.chmod(0o600)
        self.servers = []
        self.addCleanup(self.close)
        self.start()

    def close(self):
        for server, thread in self.servers:
            server.shutdown(); server.server_close(); thread.join(2)
        self.servers.clear()

    def start(self, base='/asset-lab/', port=0, api=None):
        self.app = create_app(Config(self.root / 'data', port=port, public_base_path=base,
            api_base=api, secret_key_file=self.key))
        self.server = CustomerHTTPServer(self.app)
        thread = threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01),daemon=True)
        thread.start(); self.servers.append((self.server,thread))

    def request(self, path, method='GET', *, cookie=None, csrf=None, body=None, absolute=False, extra_headers=None):
        client=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        headers={}
        if cookie: headers['Cookie']=cookie
        if method!='GET': headers['Origin']=self.app.config.public_origin
        if csrf: headers['X-CSRF-Token']=csrf
        if cookie and hasattr(self,'browser_sessions') and cookie in self.browser_sessions:
            headers['X-Asset-Lab-Session']=self.browser_sessions[cookie]
        headers.update(extra_headers or {})
        if body is not None: headers['Content-Type']='application/json';body=json.dumps(body)
        client.request(method,path if absolute else self.app.config.api_base+path,body,headers)
        response=client.getresponse();status=response.status;headers=dict(response.getheaders());raw=response.read();client.close()
        result=json.loads(raw) if headers.get('Content-Type','').startswith('application/json') else raw
        if status==200 and path=='/session':
            if not hasattr(self,'browser_sessions'):self.browser_sessions={}
            self.browser_sessions[headers['Set-Cookie'].split(';',1)[0]]=result['data']['session']['id']
        return status,headers,result

    def session(self):
        status,headers,body=self.request('/session');self.assertEqual(status,200)
        return headers['Set-Cookie'].split(';',1)[0],body['data']

    def test_full_project_flow_and_schema(self):
        cookie,session=self.session();self.assertTrue(session['features']['persistentProjects'])
        status,_,created=self.request('/projects','POST',cookie=cookie,csrf=session['csrfToken'],body={'name':'合成集成项目','description':'人工验收用'})
        self.assertEqual(status,200); project=created['data']
        status,_,body=self.request('/projects/'+project['id'],cookie=cookie)
        self.assertEqual(status,200);self.assertEqual(body['data']['name'],'合成集成项目')
        other,_=self.session();self.assertEqual(self.request('/projects/'+project['id'],cookie=other)[0],404)
        self.assertEqual(self.app.services.storage.readiness()['dataSchemaVersion'],SCHEMA_VERSION)
        self.assertFalse(self.request('/ready')[2]['data']['customerReady'])

    def test_server_drafts_version_isolation_and_restart(self):
        cookie,session=self.session();content={'workflow':{'new-project':{'name':'尚未创建的项目','description':'刷新仍保留'},'review:synthetic':{'note':'人工审核备注'}},'accountSelection':None}
        self.assertEqual(self.request('/drafts/browser')[0],401)
        result=self.request('/drafts/browser','PUT',cookie=cookie,csrf=session['csrfToken'],body={'expectedVersion':0,'content':content})
        self.assertEqual(result[0],200);saved=result[2]['data'];self.assertTrue(saved['saved']);self.assertEqual(saved['savedDrafts'][0]['version'],1)
        self.assertEqual(self.request('/drafts/browser','PUT',cookie=cookie,csrf=session['csrfToken'],body={'expectedVersion':0,'content':content})[0],409)
        other,_=self.session();self.assertEqual(self.request('/drafts/browser',cookie=other)[2]['data']['version'],0)
        port=self.server.server_port;self.close();self.start(port=port)
        self.assertEqual(self.request('/drafts/browser',cookie=cookie)[2]['data']['content'],content)

    def test_drafts_do_not_accept_authorization_payload(self):
        cookie,session=self.session()
        content={'workflow':{},'accountSelection':{'providerAccountId':None,'spaceId':None,'token':'synthetic-forbidden'}}
        self.assertEqual(self.request('/drafts/browser','PUT',cookie=cookie,csrf=session['csrfToken'],body={'expectedVersion':0,'content':content})[0],422)
        self.assertEqual(self.request('/drafts/browser','PUT',cookie=cookie,body={'expectedVersion':0,'content':{}})[0],403)

    def test_account_list_and_task_list_are_real_empty_repositories(self):
        cookie,_=self.session()
        for path in ('/provider-accounts','/tasks','/projects'):
            status,_,body=self.request(path,cookie=cookie);self.assertEqual(status,200,path);self.assertEqual(body['data']['items'],[])

    def test_oauth_gate_and_callback_headers(self):
        cookie,session=self.session()
        status,_,body=self.request('/provider-accounts/authorize','POST',cookie=cookie,csrf=session['csrfToken'],body={'provider':'libtv','returnPath':'/asset-lab/'})
        self.assertEqual(status,503);self.assertEqual(body['error']['code'],'PROVIDER_UNCONFIGURED')
        status,headers,_=self.request('/oauth/libtv/callback?state=synthetic&code=synthetic')
        self.assertEqual(status,303);self.assertEqual(headers['Location'],'/asset-lab/?authorizationStatus=failed')
        self.assertEqual(headers['Referrer-Policy'],'no-referrer');self.assertIn("default-src 'none'",headers['Content-Security-Policy'])

    def test_single_bootstrap_and_module_assets(self):
        status,_,body=self.request('/asset-lab/',absolute=True);self.assertEqual(status,200)
        html=body.decode();self.assertEqual(html.count('src="_app/bootstrap.mjs"'),1);self.assertNotIn('src="shell/bootstrap.js"',html)
        self.assertIn('id="asset-lab-build"',html);self.assertIn('"dataSchemaVersion": 2',html)
        for path in ('_app/bootstrap.mjs','_app/drafts.mjs','_app/integration.css','accounts/accounts.css','updates/version-checker.mjs','workflow/controller.js'):
            status,_,_=self.request('/asset-lab/'+path,absolute=True);self.assertEqual(status,200,path)
        self.assertEqual(self.request('/api/v1/session',absolute=True)[0],404)

    def test_custom_api_mount_preserves_session_and_project_routes(self):
        self.close();self.start(api='/customer/api/v1')
        cookie,_=self.session();self.assertEqual(self.request('/projects',cookie=cookie)[0],200)
        self.assertIn('Path=/',self.request('/session',cookie=cookie)[1]['Set-Cookie'])
        self.assertNotIn('Path=/asset-lab/',self.request('/session',cookie=cookie)[1]['Set-Cookie'])
        self.assertEqual(self.request('/asset-lab/api/v1/session',absolute=True)[0],410)

    def test_unconfigured_version_fails_deliberately(self):
        status,_,body=self.request('/version');self.assertEqual(status,503);self.assertEqual(body['error']['code'],'RELEASE_UNAVAILABLE')

    def test_wrong_manifest_schema_cannot_initialize_or_migrate_data(self):
        manifest=json.loads((ROOT/'release-manifest.example.json').read_text())
        manifest.update(dataSchemaVersion=1,buildId='synthetic-schema-mismatch')
        manifest['integrity']['value']='0'*64
        path=self.root/'release.json';path.write_text(json.dumps(manifest))
        data=self.root/'must-not-initialize'
        with self.assertRaises(ConfigurationError):
            create_app(Config(data,port=0,public_base_path='/asset-lab/',secret_key_file=self.key,
                release_root=self.root/'runtime',running_manifest=path))
        self.assertFalse(data.exists())


if __name__=='__main__': unittest.main()
