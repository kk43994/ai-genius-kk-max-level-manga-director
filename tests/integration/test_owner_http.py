"""Owner callback/confirmation through the public HTTP adapter; official calls synthetic."""
from dataclasses import asdict
import importlib.util
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from backend.app import ROOT
from backend.auth import ProviderService
from backend.providers.libtv_oauth import LibTVOAuth, OAuthConfig
import test_composed_http as composed


spec=importlib.util.spec_from_file_location('offline_account_fixture',ROOT/'tests/spaces/test_provider_projection_integration.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class OwnerHTTPTests(unittest.TestCase):
    close=composed.ComposedHTTPTests.close
    start=composed.ComposedHTTPTests.start
    request=composed.ComposedHTTPTests.request
    session=composed.ComposedHTTPTests.session

    def setUp(self):
        composed.ComposedHTTPTests.setUp(self)
        prior=self.app.services.providers
        http=fixture.OfflineAccountHTTP()
        oauth=LibTVOAuth(OAuthConfig(self.app.config.public_origin+self.app.config.api_base+'/oauth/libtv/callback',
            return_paths=('/','/asset-lab/'),allow_loopback_development=True),http)
        self.app.services.providers=ProviderService(prior.repository,prior.codec,oauth,
            workspace_recovery=self.app.services.workspace_recovery)

    def authorize_owner(self,cookie,purpose,dirty=False):
        # Direct trusted server invocation sets up a synthetic OAuth attempt;
        # the deployed authorize route remains disabled and never contacts LibTV.
        session=self.app.services.sessions.bootstrap(cookie)
        context=dict(asdict(session.context),csrfVerified=True,
            headers={'Origin':self.app.config.public_origin,'X-CSRF-Token':session.data['csrfToken']})
        attempt=self.app.services.providers.begin_authorization(context,purpose=purpose,
            hasUnsavedChanges=dirty,returnPath='/asset-lab/')
        state=parse_qs(urlsplit(attempt['authorizationUrl']).query)['state'][0]
        response=self.request('/oauth/libtv/callback?'+urlencode({'state':state,'code':'synthetic-only'}),cookie=cookie)
        self.assertEqual(response[0],303)
        self.assertTrue(response[1]['Location'].startswith('/asset-lab/?'))
        self.assertEqual(response[1]['Referrer-Policy'],'no-referrer')
        return attempt,response

    def data_for(self,cookie):
        return self.request('/session',cookie=cookie)[2]['data']

    def test_bind_rotates_scoped_cookie_without_creating_a_creator_account(self):
        cookie,data=self.session()
        _,response=self.authorize_owner(cookie,'bind_owner')
        self.assertIn('workspaceStatus=bound',response[1]['Location'])
        new_cookie=response[1]['Set-Cookie'].split(';',1)[0]
        self.assertNotEqual(cookie,new_cookie);self.assertIn('Path=/asset-lab/',response[1]['Set-Cookie'])
        self.assertEqual(self.request('/projects',cookie=cookie)[0],401)
        rebound=self.data_for(new_cookie)
        self.assertEqual(rebound['tenant'],data['tenant']);self.assertTrue(rebound['workspace']['ownerBound'])
        self.assertEqual(self.request('/provider-accounts',cookie=new_cookie)[2]['data']['items'],[])

    def test_restore_confirmation_waits_for_server_drafts_and_preserves_both_workspaces(self):
        old_cookie,old_data=self.session()
        _,bound=self.authorize_owner(old_cookie,'bind_owner');old_cookie=bound[1]['Set-Cookie'].split(';',1)[0]
        old_data=self.data_for(old_cookie)
        status,_,project=self.request('/projects','POST',cookie=old_cookie,csrf=old_data['csrfToken'],body={'name':'原工作区合成项目'})
        self.assertEqual(status,200);project_id=project['data']['id']
        current_cookie,current_data=self.session()
        attempt,response=self.authorize_owner(current_cookie,'recover_workspace',dirty=True)
        self.assertIn('workspaceStatus=awaiting_confirmation',response[1]['Location']);self.assertNotIn('Set-Cookie',response[1])
        content={'workflow':{'new-project':{'name':'保留匿名工作区草稿'}},'accountSelection':None}
        saved=self.request('/drafts/browser','PUT',cookie=current_cookie,csrf=current_data['csrfToken'],body={'expectedVersion':0,'content':content})[2]['data']
        intent_id=attempt['workspaceIntent']['intentId']
        intent=self.request('/workspace-intents/'+intent_id,cookie=current_cookie)[2]['data']
        confirm={'action':'recover_preserve_current','workspaceId':old_data['tenant']['id'],
            'expectedVersion':intent['version'],'expectedContentRevision':intent['sourceWorkspace']['content']['revision'],
            'draftDisposition':'saved','savedDrafts':saved['savedDrafts']}
        status,headers,result=self.request('/workspace-intents/'+intent_id+'/confirm','POST',cookie=current_cookie,csrf=current_data['csrfToken'],body=confirm)
        self.assertEqual(status,200,result);self.assertTrue(result['data']['sourceWorkspacePreserved'])
        recovered=headers['Set-Cookie'].split(';',1)[0]
        self.assertIn('Path=/asset-lab/',headers['Set-Cookie']);self.assertEqual(self.data_for(recovered)['tenant'],old_data['tenant'])
        self.assertEqual(self.request('/projects/'+project_id,cookie=recovered)[0],200)
        self.assertEqual(self.request('/drafts/browser',cookie=recovered)[2]['data']['version'],0)
        self.assertEqual(self.request('/projects',cookie=current_cookie)[0],401)
