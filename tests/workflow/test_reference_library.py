import base64
from types import SimpleNamespace
import unittest
import test_workflow as fixture
from backend.workflow.reference_library import import_reference
from backend.workflow import WorkflowError


class ReferenceLibrary(unittest.TestCase):
    setUp=fixture.WorkflowTests.setUp
    asset=fixture.WorkflowTests.asset
    review=fixture.WorkflowTests.review
    output=fixture.WorkflowTests.output
    task=fixture.WorkflowTests.task

    def upload(self):
        self.workflow.tasks=SimpleNamespace(_selection=lambda ctx:{'revision':1},_owner=lambda ctx,s:self.owner)
        return import_reference(self.workflow,self.ctx,self.project_id,{'name':'合成构图参考',
            'contentBase64':base64.b64encode(fixture.png((80,30,120))).decode(),'expectedSelectionRevision':1})['revision']

    def test_import_is_separate_pending_and_does_not_change_production_plan(self):
        r=self.upload();self.assertEqual(r['stage'],'reference');self.assertEqual(r['review'],'pending')
        self.assertEqual(len(self.workflow.get_plan(self.ctx,self.project_id)['entities']),3)
        spec={'projectId':self.project_id,'entityId':'ent_character','recipe':'image25_style','prompt':'参考构图',
              'sourceRevisionIds':[r['id']],'settings':{}}
        with self.assertRaises(WorkflowError):self.workflow.build_spec(self.ctx,spec,self.owner)
        r=self.review(r)
        self.assertEqual(self.workflow.build_spec(self.ctx,spec,self.owner)['sourceRevisionIds'],[r['id']])
        with self.assertRaises(WorkflowError):self.workflow.build_spec(self.ctx,spec,{**self.owner,'spaceId':'other'})
        self.assertEqual(self.upload()['id'],r['id'])

    def test_supplemental_reference_cannot_replace_required_identity_source(self):
        imported=self.review(self.upload())
        spec={'projectId':self.project_id,'entityId':'ent_character','recipe':'image25_asset','prompt':'制作主图',
              'sourceRevisionIds':[imported['id']],'settings':{}}
        with self.assertRaises(WorkflowError):self.workflow.build_spec(self.ctx,spec,self.owner)
        style=self.review(self.output('mj_style'))
        spec['sourceRevisionIds']=[style['id'],imported['id']]
        checked=self.workflow.build_spec(self.ctx,spec,self.owner)
        task={**checked,'id':'task_with_supplemental','ownership':self.owner,'status':'downloading'}
        child=self.workflow.record_output(self.ctx,task,fixture.png())
        self.assertEqual(child['sourceRevisionIds'],[style['id'],imported['id']])
        self.review(imported,'changes_requested','此参考不再适用')
        child=self.workflow.get_revision(self.ctx,child['id'],require_approved=False)
        self.assertEqual(child['status'],'stale')

    def test_saving_plan_keeps_reference_image_active(self):
        r=self.upload();plan=self.workflow.get_plan(self.ctx,self.project_id)
        rows=[{k:v for k,v in e.items() if k!='sourceRevision'} for e in plan['entities']]
        self.workflow.save_plan(self.ctx,self.project_id,{'entities':rows,'stylePrompt':plan['stylePrompt'],'expectedVersion':plan['version']})
        self.assertTrue(self.asset(r)['active'])
