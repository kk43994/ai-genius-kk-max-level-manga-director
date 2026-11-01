"""Approved identity masters are required before screenplay state derivatives."""
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
        self.master, self.base, self.rain = [b['entityId'] for b in job['bindings'] if b['assetId'] == 'a_lin']
        self.other = next(b['entityId'] for b in job['bindings'] if b['assetId'] == 'a_ning')
        self.style = self.image(self.master)
        self.workflow.confirm_art_direction(self.ctx, self.project['id'], {
            'revisionId': self.style['id'], 'sha256': self.style['sha256'], 'notes': '统一二维手绘',
            'expectedVersion': 0, 'confirmStyle': True})
        self.master_image = self.image(self.master, 'image2_asset', [self.style['id']])
        self.job = job

    def spec(self, entity=None):
        return {'projectId': self.project['id'], 'entityId': entity or self.rain,
                'recipe': 'image2_asset', 'prompt': '沿用人物身份，制作新状态',
                'sourceRevisionIds': [self.master_image['id']], 'settings': {}}

    def test_same_person_state_uses_approved_master_without_duplicate_style_generation(self):
        self.setup_states()
        asset = self.image(self.rain, 'image2_asset', [self.master_image['id']])
        self.assertEqual(asset['sourceRevisionIds'], [self.master_image['id']])
        self.assertNotEqual(asset['entityId'], self.style['entityId'])
        row = next(r for r in self.coverage()['entities'] if r['entityId'] == self.rain)
        self.assertTrue(row['ready']); self.assertTrue(row['stages']['style'])
        spec = self.workflow.build_spec(self.ctx, self.spec(), self.owner)
        validated = self.workflow.validate_task_inputs(self.ctx, {k:v for k,v in spec.items() if k != 'workflowSnapshot' and k not in ('repairOfRevisionId','refineSourceRevisionId')}, self.owner)
        self.assertEqual(validated['sources'][0]['revisionId'], self.master_image['id'])

    def test_other_character_owner_and_nano_cannot_use_the_shared_style_exception(self):
        self.setup_states()
        for body, owner in [(self.spec(self.other), self.owner),
                            (self.spec(), {**self.owner, 'spaceId': 'foreign'}),
                            ({**self.spec(), 'recipe': 'nano_refine'}, self.owner)]:
            with self.assertRaises(WorkflowError):
                self.workflow.build_spec(self.ctx, body, owner)

    def test_image25_exploration_is_not_a_formal_state_and_keeps_master_lineage(self):
        self.setup_states()
        style = self.image(self.master, 'image25_style')
        self.assertEqual(style['stage'], 'style')
        self.workflow.confirm_art_direction(self.ctx, self.project['id'], {
            'revisionId':style['id'], 'sha256':style['sha256'], 'notes':'新版手绘方向',
            'expectedVersion':1, 'confirmStyle':True})
        master = self.image(self.master, 'image25_asset', [style['id']])
        child = self.image(self.rain, 'image25_asset', [master['id']])
        self.assertEqual(child['stage'], 'asset')
        self.assertEqual(child['sourceRevisionIds'], [master['id']])
        for body in ({**self.spec(), 'recipe':'image25_style', 'sourceRevisionIds':[]},
                     {**self.spec(), 'recipe':'image25_asset', 'sourceRevisionIds':[style['id']]}):
            with self.assertRaises(WorkflowError):
                self.workflow.build_spec(self.ctx, body, self.owner)

    def test_changed_state_definition_invalidates_shared_source_and_existing_result(self):
        self.setup_states()
        asset = self.image(self.rain, 'image2_asset', [self.master_image['id']])
        result = copy.deepcopy(self.job['result'])
        result['assets'][0]['states'][1]['description'] = '修改后的雨中造型'
        self.production.save_review(self.ctx, self.job['id'], {'expectedVersion': self.job['reviewVersion'],
            'expectedEditVersion': 0, 'result': result})
        with self.assertRaises(WorkflowError):
            self.workflow.build_spec(self.ctx, self.spec(), self.owner)
        revisions = [r for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] for r in a['revisions']]
        self.assertEqual(next(r for r in revisions if r['id'] == asset['id'])['status'], 'stale')

    def test_mj_and_sibling_state_cannot_skip_the_master(self):
        self.setup_states()
        for body in ({**self.spec(), 'sourceRevisionIds': [self.style['id']]},
                     {**self.spec(), 'recipe': 'mj_style', 'sourceRevisionIds': []}):
            with self.assertRaises(WorkflowError):
                self.workflow.build_spec(self.ctx, body, self.owner)
        sibling = self.image(self.base, 'image2_asset', [self.master_image['id']])
        with self.assertRaises(WorkflowError):
            self.workflow.build_spec(self.ctx, {**self.spec(), 'sourceRevisionIds': [sibling['id']]}, self.owner)

    def test_revoking_master_blocks_submission_and_invalidates_children(self):
        self.setup_states()
        child = self.image(self.rain, 'image2_asset', [self.master_image['id']])
        asset = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items']
                     if a['id'] == self.master_image['assetId'])
        self.workflow.review(self.ctx, asset['id'], {'revisionId': self.master_image['id'],
            'sha256': self.master_image['sha256'], 'decision': 'changes_requested',
            'note': '合成主图需要修改', 'expectedVersion': asset['version']})
        with self.assertRaises(WorkflowError):
            self.workflow.validate_task_inputs(self.ctx, self.spec(), self.owner)
        rows = self.workflow.list_assets(self.ctx, self.project['id'])['items']
        self.assertEqual(next(r for a in rows for r in a['revisions'] if r['id'] == child['id'])['status'], 'stale')

    def test_existing_state_mj_can_seed_master_without_rewriting_old_receipt(self):
        import io
        from PIL import Image
        self.setup_states()
        plan = self.workflow.get_plan(self.ctx, self.project['id'])
        entity = next(e for e in plan['entities'] if e['id'] == self.base)
        raw = io.BytesIO(); Image.new('RGB', (32, 32), 'purple').save(raw, format='PNG')
        # An immutable pre-upgrade MJ receipt, collected after upgrade.
        task = dict(id='pre-upgrade-style', projectId=self.project['id'], entityId=self.base,
            recipe='mj_style', prompt='历史基础形象', sourceRevisionIds=[], settings={}, ownership=self.owner,
            status='downloading', workflowSnapshot={'entityVersion':entity['version'],
            'styleVersion':plan['styleVersion'], 'sourceHashes':{}})
        old = self.workflow.record_output(self.ctx, task, raw.getvalue())
        library = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] if a['id']==old['assetId'])
        self.workflow.review(self.ctx, old['assetId'], {'revisionId':old['id'], 'sha256':old['sha256'],
            'decision':'approved', 'note':'合成迁移测试', 'expectedVersion':library['version']})
        body = {**self.spec(self.master), 'sourceRevisionIds':[old['id']]}
        self.assertEqual(self.workflow.build_spec(self.ctx, body, self.owner)['sourceRevisionIds'], [old['id']])
        self.assertEqual(self.workflow.content(self.ctx, old['assetId'], old['id'])[0], raw.getvalue())
        with self.assertRaises(WorkflowError):
            self.workflow.build_spec(self.ctx, {**body, 'entityId':self.rain}, self.owner)
