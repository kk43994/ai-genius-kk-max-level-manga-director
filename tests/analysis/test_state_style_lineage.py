"""Same-person state variants preserve an explicit approved MJ source."""
import copy
import unittest
import test_production_coverage as coverage_fixture
from backend.workflow import WorkflowError


class StateStyleTests(unittest.TestCase):
    setUp = coverage_fixture.CoverageTests.setUp
    begin = coverage_fixture.CoverageTests.begin
    finish = coverage_fixture.CoverageTests.finish
    image = coverage_fixture.CoverageTests.image
    save_entities = coverage_fixture.CoverageTests.save_entities
    coverage = coverage_fixture.CoverageTests.coverage

    def setup_states(self):
        job = self.finish()
        result = copy.deepcopy(job['result'])
        variant = copy.deepcopy(result['assets'][0]['states'][0])
        variant.update(id='rain', name='雨中', description='同一人物外套被雨打湿')
        result['assets'][0]['states'].append(variant)
        job = self.production.save_review(self.ctx, job['id'], {'expectedVersion': 0,
            'expectedEditVersion': 0, 'result': result})
        plan = self.production.candidate(self.ctx, job['id'])
        self.workflow.save_plan(self.ctx, self.project['id'], {k: plan[k] for k in ('expectedVersion', 'stylePrompt', 'entities')})
        self.workflow.tasks = self.services.tasks
        self.base, self.rain = [b['entityId'] for b in job['bindings'] if b['assetId'] == 'a_lin']
        self.other = next(b['entityId'] for b in job['bindings'] if b['assetId'] == 'a_ning')
        self.style = self.image(self.base)
        self.workflow.confirm_art_direction(self.ctx, self.project['id'], {
            'revisionId': self.style['id'], 'sha256': self.style['sha256'], 'notes': '统一二维手绘',
            'expectedVersion': 0, 'confirmStyle': True})
        self.job = job

    def spec(self, entity=None):
        return {'projectId': self.project['id'], 'entityId': entity or self.rain,
                'recipe': 'image2_asset', 'prompt': '沿用人物身份，制作新状态',
                'sourceRevisionIds': [self.style['id']], 'settings': {}}

    def test_same_person_state_uses_original_mj_without_duplicate_style_generation(self):
        self.setup_states()
        asset = self.image(self.rain, 'image2_asset', [self.style['id']])
        self.assertEqual(asset['sourceRevisionIds'], [self.style['id']])
        self.assertNotEqual(asset['entityId'], self.style['entityId'])
        row = next(r for r in self.coverage()['entities'] if r['entityId'] == self.rain)
        self.assertTrue(row['ready']); self.assertTrue(row['stages']['style'])
        spec = self.workflow.build_spec(self.ctx, self.spec(), self.owner)
        validated = self.workflow.validate_task_inputs(self.ctx, {k:v for k,v in spec.items() if k != 'workflowSnapshot' and k not in ('repairOfRevisionId','refineSourceRevisionId')}, self.owner)
        self.assertEqual(validated['sources'][0]['revisionId'], self.style['id'])

    def test_other_character_owner_and_nano_cannot_use_the_shared_style_exception(self):
        self.setup_states()
        for body, owner in [(self.spec(self.other), self.owner),
                            (self.spec(), {**self.owner, 'spaceId': 'foreign'}),
                            ({**self.spec(), 'recipe': 'nano_refine'}, self.owner)]:
            with self.assertRaises(WorkflowError):
                self.workflow.build_spec(self.ctx, body, owner)

    def test_changed_state_definition_invalidates_shared_source_and_existing_result(self):
        self.setup_states()
        asset = self.image(self.rain, 'image2_asset', [self.style['id']])
        result = copy.deepcopy(self.job['result'])
        result['assets'][0]['states'][1]['description'] = '修改后的雨中造型'
        self.production.save_review(self.ctx, self.job['id'], {'expectedVersion': self.job['reviewVersion'],
            'expectedEditVersion': 0, 'result': result})
        with self.assertRaises(WorkflowError):
            self.workflow.build_spec(self.ctx, self.spec(), self.owner)
        revisions = [r for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] for r in a['revisions']]
        self.assertEqual(next(r for r in revisions if r['id'] == asset['id'])['status'], 'stale')
