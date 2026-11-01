"""All shipped services on a real HTTP server; no network provider or paid calls."""
import base64
import http.client
import json
import secrets
import tempfile
import threading
import unittest
from pathlib import Path

from backend.app import Config, ConfigurationError, CustomerHTTPServer, ROOT, Response, create_app
from backend.storage import SCHEMA_VERSION


class ComposedHTTPTests(unittest.TestCase):
    def test_failed_job_is_successfully_read_as_data_not_transport_error(self):
        cookie,_=self.session()
        job={'id':'prd_synthetic','status':'failed','completedCalls':1,'canRepairProduction':True,
             'error':{'code':'ANALYSIS_RESULT_INVALID','message':'原文引用不一致'}}
        self.app.router.add('GET','/api/v1/fixture-failed-job',lambda c,p:Response(200,job))
        self.app.router.add('GET','/api/v1/fixture-request-error',lambda c,p:Response(422,{'error':job['error']}))
        status,_,body=self.request('/fixture-failed-job',cookie=cookie)
        self.assertEqual(status,200);self.assertEqual(body['data'],job);self.assertNotIn('error',body)
        status,_,body=self.request('/fixture-request-error',cookie=cookie)
        self.assertEqual(status,422);self.assertEqual(body['error'],job['error']);self.assertNotIn('data',body)

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

    def test_production_routes_require_csrf_scope_and_enabled_provider(self):
        cookie,session=self.session()
        status,_,response=self.request('/workflow/start','POST',cookie=cookie,csrf=session['csrfToken'],
            body={'text':'合成剧本，角色在书店说话。','idempotencyKey':'production-route-test'})
        self.assertEqual(status,200)
        project,script=response['data']['project'],response['data']['script']
        path=f"/projects/{project['id']}/scripts/{script['id']}/production"
        self.assertIsNone(self.request(path,cookie=cookie)[2]['data']['analysis'])
        self.assertEqual(self.request(path,'POST',cookie=cookie,body={})[0],403)
        self.assertEqual(self.request(path,'POST',cookie=cookie,csrf=session['csrfToken'],body={})[0],503)
        other,_=self.session()
        self.assertEqual(self.request(path,cookie=other)[0],404)
        self.assertEqual(self.request('/production-jobs/prd_unknown/edits','PUT',cookie=cookie,body={})[0],403)
        for operation in ('revalidate', 'repair'):
            self.assertEqual(self.request('/production-jobs/prd_unknown/'+operation,'POST',cookie=cookie,body={})[0],403)
        self.assertEqual(self.request('/production-jobs/prd_unknown',cookie=other)[0],404)

    def test_quickstart_http_csrf_restart_and_tenant_boundary(self):
        cookie, session = self.session()
        payload = {'text': '《HTTP 流程验证》\n角色：旅人\n场景：庭院\n道具：灯笼', 'idempotencyKey':'http-start-synthetic'}
        self.assertEqual(self.request('/workflow/start','POST',cookie=cookie,body=payload)[0],403)
        status, _, response = self.request('/workflow/start','POST',cookie=cookie,csrf=session['csrfToken'],body=payload)
        self.assertEqual(status,200,response)
        pid = response['data']['project']['id']
        sid = response['data']['script']['id']
        analysis_path = '/projects/'+pid+'/scripts/'+sid
        self.assertIsNone(self.request(analysis_path+'/analysis',cookie=cookie)[2]['data']['analysis'])
        self.assertEqual(self.request(analysis_path+'/analyze','POST',cookie=cookie,body={})[0],403)
        blocked=self.request(analysis_path+'/analyze','POST',cookie=cookie,csrf=session['csrfToken'],body={})
        self.assertEqual(blocked[0],503)
        self.assertEqual(blocked[2]['error']['code'],'ANALYSIS_UNAVAILABLE')
        caps=self.request('/workflow/capabilities',cookie=cookie)[2]['data']
        self.assertFalse(caps['localScriptExtraction'])
        self.assertTrue(response['data']['plan']['needsReview'])
        self.assertEqual(len(response['data']['plan']['entities']),0)
        port = self.server.server_port;self.close();self.start(port=port)
        status, _, repeated = self.request('/workflow/start','POST',cookie=cookie,csrf=session['csrfToken'],body=payload)
        self.assertEqual(status,200,repeated)
        self.assertEqual(repeated['data']['project']['id'],pid)
        self.assertTrue(repeated['data']['duplicate'])
        other, _ = self.session()
        self.assertEqual(self.request('/projects/'+pid,cookie=other)[0],404)
        self.assertEqual(self.request('/tasks',cookie=cookie)[2]['data']['items'],[])

    def test_quickstart_text_and_continuation_drafts_roundtrip(self):
        cookie, session = self.session()
        content = {'workflow':{'quick-start':{'text':'尚未提交的剧本','idempotencyKey':'draft-start'},'flow:synthetic':True},'accountSelection':None}
        status, _, body = self.request('/drafts/browser','PUT',cookie=cookie,csrf=session['csrfToken'],body={'expectedVersion':0,'content':content})
        self.assertEqual(status,200,body)
        port = self.server.server_port;self.close();self.start(port=port)
        self.assertEqual(self.request('/drafts/browser',cookie=cookie)[2]['data']['content'],content)

    def test_enabled_ai_without_selected_account_returns_actionable_error(self):
        self.app.services.analysis.enabled = True
        cookie, session = self.session()
        _, _, imported = self.request('/workflow/start','POST',cookie=cookie,csrf=session['csrfToken'],
            body={'text':'无账号的 AI 分析路由验收。','idempotencyKey':'no-account-analysis-import'})
        project, script = imported['data']['project'], imported['data']['script']
        path='/projects/'+project['id']+'/scripts/'+script['id']+'/analyze'
        status, _, error = self.request(path,'POST',cookie=cookie,csrf=session['csrfToken'],
            body={'idempotencyKey':'no-account-ai-request','confirmSpend':True,'expectedSelectionRevision':0})
        self.assertEqual(status,409,error)
        self.assertEqual(error['error']['code'],'SELECTION_REQUIRED')

    def test_ai_model_and_prompt_drafts_survive_restart_without_creating_tasks(self):
        cookie, session = self.session()
        content = {'workflow': {
            'text-model': 'cvlm-5.5',
            'analysis:scr_fixture:1:cvlm-5.5:first': 'analysis-original-request',
            'prompt:prj_fixture:ent_fixture:1:1:cvlm-5.5:1:first': 'prompt-original-request',
            'prompt-view:prj_fixture:ent_fixture': 'pmt_fixture',
            'prompt-backup:prj_fixture:ent_fixture:style': {'prompt': '此前手写的制作要求'},
            'compose:prj_fixture:ent_fixture:style': {'prompt': '已编辑的 AI 提示词', 'promptJobId': 'pmt_fixture'},
        }, 'accountSelection': None}
        status, _, body = self.request('/drafts/browser', 'PUT', cookie=cookie,
            csrf=session['csrfToken'], body={'expectedVersion': 0, 'content': content})
        self.assertEqual(status, 200, body)
        port = self.server.server_port; self.close(); self.start(port=port)
        self.assertEqual(self.request('/drafts/browser', cookie=cookie)[2]['data']['content'], content)
        self.assertEqual(self.request('/tasks', cookie=cookie)[2]['data']['items'], [])
        other, _ = self.session()
        self.assertEqual(self.request('/drafts/browser', cookie=other)[2]['data']['version'], 0)
        content['workflow']['accessToken'] = 'synthetic-forbidden'
        self.assertEqual(self.request('/drafts/browser', 'PUT', cookie=cookie,
            csrf=session['csrfToken'], body={'expectedVersion': 1, 'content': content})[0], 422)

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
