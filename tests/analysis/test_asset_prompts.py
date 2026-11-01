"""Prompt generation uses one model call and preserves source/version boundaries."""
import copy
import json
import unittest
import test_analysis as fixtures
from backend.analysis.asset_prompts import PromptService, parse_prompt_result, instruction
from backend.workflow import WorkflowError
from backend.storage import StorageError


class PromptTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.AnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.__dict__.update({k:v for k,v in fixture.__dict__.items() if not k.startswith('_')})
        entity={'id':'ent_test','category':'scene','name':'测试地点','description':'剧本中的地点',
                'origin':'script','quote':self.script['text'].splitlines()[0],'scriptId':self.script['id'],'variant':''}
        self.plan=self.workflow.save_plan(self.ctx,self.project['id'],{'expectedVersion':self.workflow.get_plan(self.ctx,self.project['id'])['version'],'entities':[entity],'stylePrompt':''})
        self.ai=PromptService(self.services,self.provider,enabled=True,background=False)
        self.result={'sourceRevision':self.script['sourceRevision'],'entityId':'ent_test','assetName':'测试地点',
            'usable':True,'summary':'依据原文的场景资产，视觉选择待审核',
            'scriptFacts':[{'detail':'原文标题','evidence':{'startLine':1,'endLine':1,'quote':self.script['text'].splitlines()[0]}}],
            'creativeChoices':['测试画风'], 'uncertainties':[], 'variants':[], 'exclusions':['不添加无关人物'],
            'prompts':{k:'依据已列出的剧本事实制作这一资产。保持场景空间、时段和天气，使用空镜完整呈现环境结构。画面不添加人物、字幕、拼贴和多余情节。视觉设计作为待审核创作选择。' for k in ('style','asset','refine')}}
        self.provider.text=json.dumps(self.result)

    def begin(self,**overrides):
        return self.ai.start_entity(self.ctx,self.project['id'],'ent_test',{**self.body,**overrides})

    def test_single_pinned_call_durable_result_and_no_plan_mutation(self):
        before=self.workflow.get_plan(self.ctx,self.project['id'])
        job=self.begin(modelId='cvlm-5.5')
        self.assertEqual(job['totalCalls'],1)
        self.assertEqual(job['modelId'],'cvlm-5.5')
        self.ai.advance(self.ctx,job['id']);self.ai.advance(self.ctx,job['id'])
        done=self.ai.get(self.ctx,job['id'])
        self.assertEqual(done['status'],'ready');self.assertEqual(done['result'],self.result)
        self.assertEqual(len(self.provider.submissions),1)
        self.assertEqual(self.ai.list_project(self.ctx,self.project['id'])['items'],[done])
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project['id']),before)
        context=self.ai._get(self.ctx,job['id'])['data']['context']
        self.assertIn(self.script['text'].splitlines()[-1],instruction(self.script,context))
        # A plan revision invalidates application, not the saved original result.
        body={'entities':[{k:v for k,v in e.items() if k in ('id','category','name','description','origin','quote','scriptId','variant')} for e in before['entities']]};body.update(expectedVersion=before['version'],stylePrompt='新版风格')
        self.workflow.save_plan(self.ctx,self.project['id'],body)
        self.assertTrue(self.ai.get(self.ctx,job['id'])['stale'])

    def test_bad_quotes_or_wrong_entity_cannot_be_applied(self):
        job=self.begin();context=self.ai._get(self.ctx,job['id'])['data']['context']
        for change in ('quote','entity'):
            value=copy.deepcopy(self.result)
            if change=='quote':value['scriptFacts'][0]['evidence']['quote']='杜撰的原文'
            else:value['entityId']='other'
            with self.assertRaises(WorkflowError):parse_prompt_result(json.dumps(value),self.script,context)
        self.provider.text=json.dumps(value)
        self.ai.advance(self.ctx,job['id']);self.ai.advance(self.ctx,job['id'])
        self.assertEqual(self.ai.get(self.ctx,job['id'])['status'],'failed')

    def test_tenant_and_receipt_isolation(self):
        job=self.begin();self.provider.ambiguous=True;self.ai.advance(self.ctx,job['id'])
        self.ai.advance(self.ctx,job['id'])
        self.assertEqual(len(self.provider.submissions),1)
        self.assertEqual(self.ai.get(self.ctx,job['id'])['status'],'unknown_submission')
        for call in (lambda:self.ai.get(self.other,job['id']),lambda:self.ai.list_project(self.other,self.project['id'])):
            with self.assertRaises((WorkflowError,StorageError)):call()

    def test_old_generic_placeholder_can_still_validate_original_paid_receipt(self):
        spec={'projectId':self.project['id'],'entityId':'ent_test','recipe':'mj_style',
              'prompt':'测试地点\n请填写希望采用的视觉风格。\n生成完整的风格候选图。','sourceRevisionIds':[],'settings':{'count':4}}
        from backend.tasks.service import TaskService
        from backend.tasks.errors import TaskError
        with self.assertRaises(TaskError) as error:TaskService._assert_new_prompt(spec)
        self.assertEqual(error.exception.code,'PROMPT_REVIEW_REQUIRED')
        # Recovery checks source/ownership but does not trigger a new generation.
        self.workflow.build_spec(self.ctx,spec,self.owner)
