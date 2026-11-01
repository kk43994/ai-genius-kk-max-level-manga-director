"""Explicit asset migration with synthetic records; never invokes a provider."""
import copy
import unittest
import test_production as production_fixture
from backend.workflow import WorkflowError


class BindingTests(unittest.TestCase):
    setUp = production_fixture.ProductionTests.setUp
    finish = production_fixture.ProductionTests.finish
    begin = production_fixture.ProductionTests.begin
    def legacy(self, category='character'):
        plan = self.workflow.get_plan(self.ctx, self.project['id'])
        self.workflow.save_plan(self.ctx, self.project['id'], {
            'expectedVersion': plan['version'], 'stylePrompt': plan['stylePrompt'],
            'entities': [{'id': 'legacy_lin', 'category': category, 'name': '林舟',
                          'description': '已经制作的原始档案', 'origin': 'manual'}]})

    def link_body(self, job):
        plan = self.workflow.get_plan(self.ctx, self.project['id'])
        return dict(assetId='a_lin', stateId='base', entityId='legacy_lin',
            expectedPlanVersion=plan['version'], expectedReviewVersion=job['reviewVersion'],
            expectedEditVersion=job['editVersion'], expectedBindingVersion=job['bindingVersion'],
            expectedEntityVersion=plan['entities'][0]['version'], confirmApplicable=True)

    def test_matching_name_requires_explicit_selection_and_preserves_original(self):
        self.legacy(); job = self.finish()
        before = self.workflow.get_plan(self.ctx, self.project['id'])
        binding = job['bindings'][1]
        self.assertFalse(binding['saved']); self.assertFalse(binding['linked'])
        self.assertEqual(binding['legacyCandidates'][0]['entityId'], 'legacy_lin')
        linked = self.production.save_binding(self.ctx, job['id'], self.link_body(job))
        self.assertEqual(linked['bindings'][1]['entityId'], 'legacy_lin')
        self.assertTrue(linked['bindings'][1]['saved']); self.assertFalse(linked['bindings'][1]['changed'])
        self.assertEqual(self.workflow.get_plan(self.ctx, self.project['id']), before)
        candidate = self.production.candidate(self.ctx, job['id'])
        self.assertEqual(candidate['addedCount'], 5)
        self.assertEqual(len(self.provider.submissions), 1)

    def test_link_rejects_missing_confirmation_wrong_category_and_foreign_workspace(self):
        self.legacy(category='scene'); job = self.finish(); body = self.link_body(job)
        for patch in ({'confirmApplicable':False}, {}, {'expectedBindingVersion':9}):
            with self.assertRaises(WorkflowError):
                self.production.save_binding(self.ctx, job['id'], {**body, **patch})
        self.services.tasks._owner = lambda ctx, sel:{**self.owner, 'spaceId':'foreign'}
        with self.assertRaises(WorkflowError):self.production.save_binding(self.ctx, job['id'], body)

    def test_design_change_and_concurrent_link_require_reconfirmation(self):
        self.legacy(); job = self.finish(); body = self.link_body(job)
        self.production.save_binding(self.ctx, job['id'], body)
        with self.assertRaises(WorkflowError):self.production.save_binding(self.ctx, job['id'], body)
        result = copy.deepcopy(job['result']); result['assets'][0]['design'] = '改变后的服装设计'
        changed = self.production.save_review(self.ctx, job['id'], {
            'expectedVersion':0, 'expectedEditVersion':0, 'result':result})
        self.assertTrue(changed['bindings'][1]['changed'])
        with self.assertRaises(WorkflowError):self.production.candidate(self.ctx, job['id'])
        confirmed = self.production.save_binding(self.ctx, job['id'], self.link_body(changed))
        self.assertFalse(confirmed['bindings'][1]['changed'])
        history = self.workflow.get_project(self.ctx, self.project['id'])['productionLinkHistory']
        self.assertEqual(len(history), 2)

    def test_link_keeps_pending_image_bytes_ids_and_review_history(self):
        import io
        from PIL import Image
        self.legacy(); job=self.finish()
        raw=io.BytesIO();Image.new('RGB',(32,32),'blue').save(raw,format='PNG')
        spec=self.workflow.build_spec(self.ctx,{'projectId':self.project['id'],'entityId':'legacy_lin',
            'recipe':'mj_style','prompt':'合成历史候选','sourceRevisionIds':[],'settings':{}},self.owner)
        revision=self.workflow.record_output(self.ctx,{**spec,'id':'legacy-test-task','ownership':self.owner,'status':'downloading'},raw.getvalue())
        before=self.workflow.list_assets(self.ctx,self.project['id'])
        job=self.production.get(self.ctx,job['id'])
        self.assertEqual(job['bindings'][1]['legacyCandidates'][0]['pendingCount'],1)
        self.production.save_binding(self.ctx,job['id'],self.link_body(job))
        self.assertEqual(self.workflow.list_assets(self.ctx,self.project['id'])['items'],before['items'])
        content,_=self.workflow.content(self.ctx,revision['assetId'],revision['id'])
        self.assertEqual(content,raw.getvalue())

    def test_one_archive_cannot_be_both_master_and_state(self):
        self.legacy(); job = self.finish()
        updated = self.production.save_binding(self.ctx, job['id'], self.link_body(job))
        with self.assertRaises(WorkflowError):
            self.production.save_binding(self.ctx, job['id'],
                {**self.link_body(updated), 'stateId':'__character_master__'})
