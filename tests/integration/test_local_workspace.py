"""Local handoff authorization, real HTTP cookies and preserved workspace data."""
from concurrent.futures import ThreadPoolExecutor
import unittest

from backend.storage import StorageError, TenantContext
from backend.storage.workspaces import WorkspaceRepository
from test_local_authorization import LocalAuthorizationTests


class LocalWorkspaceTests(unittest.TestCase):
    setUp=LocalAuthorizationTests.setUp
    start=LocalAuthorizationTests.start
    stop=LocalAuthorizationTests.stop
    request=LocalAuthorizationTests.request

    def prepare(self):
        self.source=self.app.services.sessions.bootstrap(self.cookie).context
        self.target=self.app.services.sessions.create().context
        self.source_project=self.app.services.workflow.create_project(self.source,{'name':'源项目保留'})
        self.target_project=self.app.services.workflow.create_project(self.target,{'name':'目标项目'})
        status,_,reply=self.request('/drafts/browser','PUT',{'expectedVersion':0,
            'content':{'workflow':{'text-model':'cvlm-5.5','review:fixture':{'note':'源草稿保留'}},'accountSelection':None}})
        self.assertEqual(status,200,reply)
        self.draft=reply['data']
        status,_,reply=self.request('/local-workspace-intents','POST',{'confirmLocalSwitch':True})
        self.assertEqual(status,200,reply)
        self.intent=reply['data']
        self.path='/local-workspace-intents/'+self.intent['id']

    def approve(self):
        self.intent=self.app.services.local_workspace.approve_from_local_operator(self.intent['id'],self.target_project['id'])

    def confirm(self):
        return self.request(self.path+'/confirm','POST',{'expectedVersion':self.intent['version'],'savedDraftVersion':self.draft['version']})

    def test_only_local_approval_unlocks_exact_browser_target(self):
        self.prepare()
        self.assertEqual(self.confirm()[0],409)
        self.assertEqual(self.request(self.path+'/approve','POST',{'projectId':self.target_project['id']})[0],404)
        self.assertEqual(self.request('/local-workspace-intents','POST',{'confirmLocalSwitch':True,'target':self.target.tenantId})[0],422)
        self.assertEqual(self.request('/local-workspace-intents','POST',{'confirmLocalSwitch':True},origin='https://other.example')[0],403)
        self.assertEqual(self.request('/local-workspace-intents','POST',{'confirmLocalSwitch':True},auth=False)[0],401)
        self.assertEqual(self.request(self.path)[2]['data']['status'],'pending')

    def test_switch_preserves_data_and_rotates_only_the_source_browser(self):
        self.prepare();self.approve()
        before=self.app.services.storage.get(self.source,'drafts','browser_drafts_v1')
        status,headers,reply=self.confirm()
        self.assertEqual(status,200,reply);self.assertTrue(reply['data']['sourceWorkspacePreserved'])
        self.assertIn('Path=/asset-lab/',headers['Set-Cookie']);self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertEqual(self.request('/projects')[0],401)
        self.cookie=headers['Set-Cookie'].split(';',1)[0]
        self.session=self.request('/session')[2]['data']
        self.assertEqual(self.session['tenant']['id'],self.target.tenantId)
        self.assertEqual([p['name'] for p in self.request('/projects')[2]['data']['items']],['目标项目'])
        self.assertEqual(self.request('/projects/'+self.source_project['id'])[0],404)
        self.assertEqual(self.app.services.storage.get(TenantContext(self.source.tenantId),'drafts','browser_drafts_v1'),before)
        self.assertEqual(self.app.services.workflow.get_project(TenantContext(self.source.tenantId),self.source_project['id'])['name'],'源项目保留')
        self.assertEqual(self.request('/provider-accounts')[2]['data']['items'],[])
        self.assertEqual(self.request(self.path)[0],404)

    def test_other_session_of_same_workspace_cannot_consume_approval(self):
        self.prepare();self.approve()
        with self.app.services.storage._system_transaction() as conn:
            row,token=self.app.services.sessions._insert(conn,self.source.tenantId,self.app.services.storage.clock())
        other=self.app.services.sessions._result(row,token)
        self.cookie=other.set_cookie.split(';',1)[0];self.session=other.data
        self.assertEqual(self.request(self.path)[0],404)
        self.assertEqual(self.confirm()[0],404)

    def test_cancel_and_expiry_do_not_grant_access(self):
        self.prepare()
        self.assertEqual(self.request(self.path+'/cancel','POST',{})[0],200)
        with self.assertRaises(StorageError):self.approve()
        status,_,reply=self.request('/local-workspace-intents','POST',{'confirmLocalSwitch':True})
        self.intent=reply['data'];self.path='/local-workspace-intents/'+self.intent['id'];self.approve()
        now=self.app.services.storage.clock();self.app.services.storage.clock=lambda:now+301
        self.assertEqual(self.confirm()[0],410)
        self.assertEqual(self.request('/session')[2]['data']['tenant']['id'],self.source.tenantId)

    def test_bound_owner_cannot_be_bypassed_by_local_handoff(self):
        self.prepare()
        with self.app.services.storage._system_transaction() as conn:
            WorkspaceRepository(self.app.services.storage).bind(conn,self.target.tenantId,'https://mcp.liblib.tv/','synthetic-owner',label='绑定工作区',authorization_attempt_id='synthetic_attempt')
        with self.assertRaises(StorageError) as result:self.approve()
        self.assertEqual(result.exception.code,'OWNER_RECOVERY_REQUIRED')

    def test_new_drafts_require_a_fresh_checkpoint_and_replay_is_single_use(self):
        self.prepare();self.approve()
        self.assertEqual(self.request('/drafts/browser','PUT',{'expectedVersion':1,
            'content':{'workflow':{'text-model':'aurora-3-prime'},'accountSelection':None}})[0],200)
        self.assertEqual(self.confirm()[0],409)
        self.draft['version']=2
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.confirm(),range(2)))
        self.assertEqual(sum(result[0]==200 for result in results),1)
        self.assertTrue(all(result[0] in (200,401,409) for result in results),results)

    def test_approval_does_not_survive_a_target_owner_binding(self):
        self.prepare();self.approve()
        with self.app.services.storage._system_transaction() as conn:
            WorkspaceRepository(self.app.services.storage).bind(conn,self.target.tenantId,'https://mcp.liblib.tv/','synthetic-owner',label='绑定工作区',authorization_attempt_id='synthetic_attempt')
        self.assertEqual(self.confirm()[0],409)
        self.assertEqual(self.request('/session')[2]['data']['tenant']['id'],self.source.tenantId)

    def test_public_service_has_no_handoff_routes(self):
        self.stop();self.start(local=False)
        self.assertEqual(self.request('/local-workspace-intents','POST',{'confirmLocalSwitch':True})[0],404)


if __name__=='__main__':unittest.main()
