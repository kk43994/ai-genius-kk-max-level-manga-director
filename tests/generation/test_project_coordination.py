import copy
from contextlib import contextmanager
from threading import Event, Thread
from types import SimpleNamespace
import unittest

from backend.generation.errors import GenerationError
from backend.generation.live_reference import LiveReferenceRoute
from backend.generation.live_reference import same_reference_prompt
from backend.generation.project_coordination import project_mutation
from backend.generation.types import digest

OWNER={'tenantId':'test','providerAccountId':'account','spaceId':'space'}

class CoordinationTests(unittest.TestCase):
    def test_projected_image_references_require_same_text_and_exact_node_order(self):
        self.assertTrue(same_reference_prompt('A={{Image 1}} B={{Image 2}}','A={{Node one}} B={{Node two}}',['one','two']))
        for actual,nodes in [('A={{Image 2}} B={{Image 1}}',['one','two']),('A={{Image 3}} B={{Image 2}}',['one','two']),('changed={{Image 1}} B={{Image 2}}',['one','two']),('A={{Image 1}} B={{Image 2}}',['wrong','two'])]:
            self.assertFalse(same_reference_prompt(actual,'A={{Node one}} B={{Node two}}',nodes))

    def test_inspection_of_setup_without_generation_claim_never_submits(self):
        state={'steps':{'upload_hash':{'done':True,'result':{'nodeId':'reference','revisionId':'r'}},
               'reference_node':{'done':True,'result':{'projectId':'project','nodeId':'node'}}}}
        @contextmanager
        def edit(*args):yield state
        calls=[]
        def call(name,args):
            calls.append(name)
            self.assertEqual(name,'read_project')
            return {'projectId':'project','revision':{'token':'sha256-'+'a'*64},
                'nodes':[{'id':'node','type':'image','data':{'params':{'model':'model','prompt':'A={{Image 1}}','count':1,'imageList':[{'nodeId':'reference'}]}}}],
                'edges':[{'source':'reference','target':'node'}]}
        client=SimpleNamespace(_owner=OWNER,_call=call,a=SimpleNamespace(journal=SimpleNamespace(edit=edit)))
        record={'sources':[{'sha256':'hash'}],'spec':{'prompt':'A={{reference:r}}'},'prepared':{'modelKey':'model'},'params':{'count':1}}
        with self.assertRaises(GenerationError) as error:LiveReferenceRoute().recover_task(client,'local',record,{'projectId':'project','nodeId':'node'})
        self.assertEqual(error.exception.code,'REFERENCE_SETUP_STOPPED');self.assertEqual(calls,['read_project'])

    def test_same_project_serializes_and_other_project_does_not_wait(self):
        entered=Event(); done=Event()
        def worker():
            entered.set()
            with project_mutation(OWNER,'project'):done.set()
        with project_mutation(OWNER,'project'):
            with project_mutation(OWNER,'project'):pass
            thread=Thread(target=worker);thread.start();self.assertTrue(entered.wait(1))
            self.assertFalse(done.wait(.03))
            with project_mutation(OWNER,'another'):pass
        self.assertTrue(done.wait(1));thread.join()

    def test_recovery_uses_original_key_and_proves_unchanged_unrun_node(self):
        original={'node':'node','projectId':'project','idempotencyKey':'original-key',
                  'model':'model','prompt':'specific subject','params':{'count':1},
                  'leftEnsure':['reference'],'expectedRevision':'sha256-'+'a'*64,'run':True}
        for mode,expected in [('rejected','REFERENCE_PREFLIGHT_REJECTED'),('timeout','PROVIDER_UNAVAILABLE'),
                              ('changed','SOURCE_CHANGED'),('already-run','SOURCE_CHANGED')]:
            state={'originalReferenceRun':copy.deepcopy(original),'steps':{'generation':{'attempted':True,'hash':digest(original)}}}
            @contextmanager
            def edit(*args):yield state
            calls=[]
            def call(name,args):
                calls.append((name,copy.deepcopy(args)))
                if name=='update_node':
                    self.assertEqual(args,original)
                    raise GenerationError('PROVIDER_UNAVAILABLE' if mode=='timeout' else 'PROVIDER_SNAPSHOT_REVISION_MISMATCH')
                self.assertEqual(name,'read_project')
                data={'params':{'model':'model','prompt':'specific subject','count':1,'imageList':[{'nodeId':'reference'}]}}
                if mode=='changed':data['params']['prompt']='changed by someone'
                if mode=='already-run':data['taskInfo']={'taskId':'existing-task'}
                return {'projectId':'project','revision':{'token':'sha256-'+'b'*64},
                        'nodes':[{'id':'node','type':'image','data':data}],
                        'edges':[{'source':'reference','target':'node'}]}
            client=SimpleNamespace(_owner=OWNER,_call=call,a=SimpleNamespace(journal=SimpleNamespace(edit=edit),policy=SimpleNamespace(allow_external_writes=True)))
            with self.subTest(mode=mode),self.assertRaises(GenerationError) as error:
                LiveReferenceRoute().recover_task(client,'local',{}, {'projectId':'project','nodeId':'node'})
            self.assertEqual(error.exception.code,expected)
            self.assertEqual(len([c for c in calls if c[0]=='update_node']),1)
            self.assertEqual(state['originalReferenceRun'],original)
            self.assertEqual('generationRejection' in state,mode=='rejected')
