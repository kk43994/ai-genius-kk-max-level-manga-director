import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from backend.generation.live import personal_account, LiveImageClient
from backend.generation.errors import GenerationError
from backend.generation.types import RecipeBinding, GenerationPolicy
from backend.generation.contracts import ToolCatalog
from backend.app import Config, ConfigurationError
from types import SimpleNamespace

OWNER={'tenantId':'t','provider':'libtv','providerAccountId':'a','providerIssuer':'https://mcp.liblib.tv/',
       'providerSubject':'user', 'spaceId':'123', 'spaceKind':'personal'}
BODY={'user':{'uuid':'user','id':9},'activeAccountId':123,'accounts':{'accounts':[{'accountId':123,'accountType':1,'ownerUuid':'user'}]}}

class LiveTests(unittest.TestCase):
    def test_account_and_canvas_ids_are_not_compared(self):
        self.assertEqual(personal_account(BODY,OWNER)['id'],9)
    def test_no_fallback_to_other_active_billing_account(self):
        body=copy.deepcopy(BODY);body['activeAccountId']=124
        with self.assertRaises(GenerationError):personal_account(body,OWNER)
    def test_rejects_other_subject_team_and_other_owner(self):
        for patch in ({'providerSubject':'other'},{'spaceKind':'team'},{'spaceId':'other'}):
            with self.assertRaises(GenerationError):personal_account(BODY,{**OWNER,**patch})
        body=copy.deepcopy(BODY);body['accounts']['accounts'][0]['ownerUuid']='other'
        with self.assertRaises(GenerationError):personal_account(body,OWNER)
    def test_nested_model_contract_preserves_exact_count(self):
        a=SimpleNamespace(recipes={'mj_style':RecipeBinding('mj-v8.1')},policy=GenerationPolicy(),catalog=ToolCatalog.bundled())
        c=LiveImageClient(a,OWNER,None)
        c.get_model=lambda model:{'inputContract':{'model':'mj-v8.1','modality':'image','parameterSchemas':{'generate':{'type':'object','properties':{'count':{'enum':[4]},'ratio':{'enum':['16:9']}},'additionalProperties':False}}}}
        model,params,count,h=c._model({'recipe':'mj_style','prompt':'角色设计','settings':{'count':4}})
        self.assertEqual(count,4);self.assertEqual(params,{'count':4});self.assertEqual(len(h),64)
        for settings in ({'count':1},{'count':4,'ratio':'bad'},{'count':4,'imageList':['x']}):
            with self.assertRaises(GenerationError):c._model({'recipe':'mj_style','prompt':'角色设计','settings':settings})
    def test_paid_configuration_requires_explicit_loopback_local_mode(self):
        with TemporaryDirectory() as d:
            for kwargs in ({'allowPaidSubmission':True},{'allowPaidSubmission':True,'local_client':True,'host':'0.0.0.0','public_origin':'https://example.com'}, {'local_client':True,'videoGeneration':True}):
                with self.assertRaises(ConfigurationError):Config(Path(d).resolve(),**kwargs)
            c=Config(Path(d).resolve(),allowPaidSubmission=True,local_client=True)
            self.assertTrue(c.allowPaidSubmission);self.assertFalse(c.videoGeneration)
if __name__=='__main__':unittest.main()

class DurableResponseTests(unittest.TestCase):
    def make_client(self, response):
        class Bridge:
            def task_for_receipt(self, ownership, receipt): return 'local'
            def checkpoint(self, task, ownership, receipt): pass
        a=SimpleNamespace(bridge=Bridge())
        c=LiveImageClient(a,OWNER,None)
        c._record=lambda task:{'spec':{'projectId':'local-project'},'prepared':{'count':4}}
        c._project=lambda local:'project'
        c._observe=lambda *a:None
        c._call=lambda name,args:response if name=='task_status' else {'projectId':'project','nodeId':'image-node','node':{'type':'image'}}
        return c
    def response(self):
        return {'schema_version':1,'task_id':'task','result_kind':'media','owner':{'user_uuid':'user'},
                'outcome':'SUCCEEDED','readiness':'TERMINAL_READY',
                'artifacts':[{'kind':'image','node_key':'image-node','resource_id':'res'+str(i)} for i in range(4)]}
    def test_real_task_sot_shape_requires_owner_count_and_single_node(self):
        body=self.response();c=self.make_client(body)
        receipt={'projectId':'project','taskId':'task'}
        self.assertEqual(c.lookup(receipt),{'status':'completed','providerReceipt':{**receipt,'nodeId':'image-node'}})
        for mutate in (lambda b:b.update(task_id='other'),lambda b:b['owner'].update(user_uuid='other'),
                       lambda b:b['artifacts'].pop(),lambda b:b['artifacts'][0].update(node_key='another-node'),
                       lambda b:b.update(outcome='unknown')):
            body=self.response();mutate(body)
            with self.assertRaises(GenerationError):self.make_client(body).lookup(receipt)

class ReferenceGraphTests(unittest.TestCase):
    def test_reference_read_uses_project_revision_and_exact_original_input(self):
        from backend.generation.live_reference import LiveReferenceRoute
        route=LiveReferenceRoute()
        receipt={'projectId':'project','nodeId':'destination'}
        record={'prepared':{'modelKey':'lib-image-2'},'spec':{'prompt':'same character'},'params':{'count':1,'ratio':'16:9'}}
        body={'projectId':'project','revision':{'token':'sha256-'+'a'*64},
              'nodes':[{'id':'destination','type':'image','data':{'params':{'model':'lib-image-2','prompt':'same character',
                       'count':1,'settings':{'ratio':'16:9'},'imageList':[{'nodeId':'source'}]}}}],
              'edges':[{'source':'source','target':'destination'}]}
        client=SimpleNamespace(_call=lambda *a:body)
        self.assertEqual(route._snapshot(client,receipt,record,['source']),'sha256-'+'a'*64)
        for mutate in (lambda b:b['edges'][0].update(source='wrong'),
                       lambda b:b['nodes'][0]['data']['params']['imageList'][0].update(nodeId='wrong'),
                       lambda b:b['nodes'][0]['data'].update(taskInfo={'taskId':'already-run'}),
                       lambda b:b['nodes'][0]['data']['params'].update(prompt='changed')):
            bad=copy.deepcopy(body);mutate(bad)
            with self.assertRaises(GenerationError):route._snapshot(SimpleNamespace(_call=lambda *a:bad),receipt,record,['source'])
    def test_canvas_receipt_never_counts_as_generated_image(self):
        from backend.generation.live_reference import LiveReferenceRoute
        client=SimpleNamespace(_observe=lambda *a:None)
        with self.assertRaises(GenerationError) as cm:
            LiveReferenceRoute()._accepted(client,'local',{'projectId':'project','nodeId':'node'},{'task_id':'cop_canvas_only'})
        self.assertEqual(cm.exception.code,'SUBMISSION_UNKNOWN')

class UploadContractTests(unittest.TestCase):
    def test_long_signed_file_handle_is_not_stored_in_operation_result(self):
        from helpers import png
        from backend.generation.types import VerifiedReference
        import hashlib
        raw=png();sha=hashlib.sha256(raw).hexdigest()
        ref=VerifiedReference('revision',OWNER,raw,'image/png',sha,'style',True)
        calls=[];stored=[];sent=[];signed='signed.'+'A'*1100
        a=SimpleNamespace(bridge=SimpleNamespace(check=lambda *a:None),media=SimpleNamespace(put=lambda u,b:sent.append((u,b))))
        c=LiveImageClient(a,OWNER,None)
        c._claim=lambda *a:None;c._observe=lambda *a:None;c._authorize_scopes=lambda *a:None
        c._finish=lambda task,step,result:stored.append(result)
        def call(name,args):
            calls.append(name)
            if name=='upload_ticket':return {'uploadId':'upload','path':'upload-images/path','parts':[{'partNumber':1,'method':'PUT','url':'https://media.example/upload'}]}
            if name=='upload_complete':return {'file_ref':signed,'url':'https://media.example/image.png'}
            self.assertEqual(args['fileRef'],signed)
            return {'projectId':'project','status':'completed','nodeId':'source-node'}
        c._call=call
        result=c._upload('local','project',ref,'original-key','h'*64)
        self.assertEqual(result['nodeId'],'source-node')
        self.assertNotIn(signed,str(stored));self.assertEqual(len(sent),1)
        self.assertEqual(calls,['upload_ticket','upload_complete','upload_media'])
