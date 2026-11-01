import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from backend.analysis.provider import LibTVAnalysisClient
from backend.auth.errors import AuthError
from backend.providers.libtv_identity import MCPReadSession


class ProviderContractTests(unittest.TestCase):
    def test_selected_model_and_persisted_number_are_in_actual_submission(self):
        client=object.__new__(LibTVAnalysisClient)
        client.catalog=SimpleNamespace(request=lambda name,args:None)
        seen=[];saved=[]
        def call(name,args):
            seen.append((name,copy.deepcopy(args)))
            return {'status':'accepted','projectId':'remote','task_id':'task-1','plan':{'nodeId':'node-1'}}
        client._call=call
        job={'id':'ana_stable','phase':'extract','modelId':'cvlm-5.5','displayNumber':7,'remoteProjectId':'remote','steps':{},'context':None}
        script={'text':'场景正文','sourceRevision':'sha'}
        client.submit(job,script,saved.append)
        args=seen[-1][1]
        self.assertEqual(args['model'],'cvlm-5.5')
        self.assertEqual(args['name'],'剧本分析 007')
        self.assertEqual(args['idempotencyKey'],'ana_stable-extract')
        self.assertEqual(saved[0]['steps']['extract']['arguments'],args)
        job.update(phase='review',draft={},rejectedSteps={'review':[{'rejectedBeforeSubmission':True}]})
        client.submit(job,script,saved.append)
        self.assertEqual(seen[-1][1]['name'],'剧本复核 007')
        self.assertEqual(seen[-1][1]['idempotencyKey'],'ana_stable-review-retry1')

    def test_only_exact_create_name_conflict_is_classified_as_rejected(self):
        client=MCPReadSession(None,'synthetic-test-token')
        for tool,message,expected in (
            ('create_node','Error executing tool create_node: NODE_NAME_CONFLICT: A node exists','PROVIDER_NODE_NAME_CONFLICT'),
            ('create_node','Upstream unknown after write','PROVIDER_PROTOCOL_ERROR'),
            ('task_status','Error executing tool create_node: NODE_NAME_CONFLICT: A node exists','PROVIDER_PROTOCOL_ERROR')):
            client._rpc=Mock(return_value={'isError':True,'content':[{'type':'text','text':message}]})
            with self.assertRaises(AuthError) as error:client.call_tool({'name':tool},{})
            self.assertEqual(error.exception.code,expected)
            self.assertNotIn('Upstream',error.exception.message)
