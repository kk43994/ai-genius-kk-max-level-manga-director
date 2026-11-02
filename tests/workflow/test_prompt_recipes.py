"""Recipe status requires matching provenance and actual human choices."""
from types import SimpleNamespace
import unittest
import test_workflow as fixture
from backend.workflow.prompt_recipes import save, portable_prompt
from backend.workflow import WorkflowError

class PromptRecipeTests(unittest.TestCase):
    setUp=fixture.WorkflowTests.setUp
    task=fixture.WorkflowTests.task
    output=fixture.WorkflowTests.output
    review=fixture.WorkflowTests.review
    asset=fixture.WorkflowTests.asset

    def connect(self):
        self.workflow.tasks=SimpleNamespace(_selection=lambda ctx:{},_owner=lambda ctx,s:self.owner)

    def picture(self,model='synthetic-model'):
        task=self.task('mj_style');task['modelId']=model
        r=self.workflow.record_output(self.ctx,task,fixture.png())
        with self.repository.transaction(self.ctx,write=True) as tx:
            self.workflow._revision(tx,r['id'])['modelLabel']=model
        return self.review(r)

    def save(self,r,**extra):
        return save(self.workflow,self.ctx,self.project_id,{'revisionId':r['id'],'sha256':r['sha256'],
            'name':'合成规范','notes':'检查身份与构图','prompt':portable_prompt(r['prompt']),
            'expectedVersion':self.workflow.get_project(self.ctx,self.project_id).get('promptRecipeVersion',0),**extra})

    def test_selected_result_retains_source_and_edited_template_is_draft(self):
        self.connect();r=self.picture()
        recipe=self.save(r);self.assertEqual(recipe['status'],'single')
        self.assertEqual(recipe['sourceRevisionId'],r['id'])
        self.assertEqual(self.save(r,prompt='改写后需要重新试做')['status'],'draft')
        self.assertEqual(self.workflow.get_project(self.ctx,self.project_id)['promptRecipeVersion'],2)

    def test_repeated_requires_matching_model_and_reviewed_outputs(self):
        self.connect();first=self.picture();second=self.picture()
        self.assertEqual(self.save(second,evidenceRevisionIds=[first['id']])['status'],'repeated')
        other=self.picture('different-model')
        with self.assertRaises(WorkflowError):self.save(other,evidenceRevisionIds=[second['id']])

    def test_foreign_owner_pending_and_conflicting_version_are_rejected(self):
        self.connect();pending=self.output('mj_style')
        with self.assertRaises(WorkflowError):self.save(pending)
        approved=self.review(pending)
        with self.assertRaises(WorkflowError):self.save(approved,expectedVersion=90)
        self.owner={**self.owner,'spaceId':'foreign'}
        with self.assertRaises(WorkflowError):self.save(approved)
        self.assertEqual(self.workflow.get_project(self.ctx,self.project_id)['promptRecipes'],[])

    def test_portable_removes_concrete_subject_refs_and_project_standard(self):
        prompt='本次制作对象：合成角色。\n参考 {{reference:private-id}}\n[本剧美术规范 v1]\n私有美术标准\n[/本剧美术规范]\n风格引用'
        self.assertEqual(portable_prompt(prompt),'本次制作对象：{{主体}}。\n参考 {{参考图}}')
