"""Current-plan delivery, including missing states, immutable history and CAS."""
import copy
import base64
import io
import unittest
from unittest.mock import patch
from PIL import Image
import test_production as fixture
from backend.workflow import WorkflowError
from backend.workflow.production_coverage import shot_candidate


class CoverageTests(unittest.TestCase):
    setUp = fixture.ProductionTests.setUp
    finish = fixture.ProductionTests.finish
    begin = fixture.ProductionTests.begin

    def coverage(self):
        return self.workflow.list_assets(self.ctx, self.project['id'])['coverage']

    def save_entities(self, extra):
        plan = self.workflow.get_plan(self.ctx, self.project['id'])
        allowed = {'id', 'category', 'name', 'description', 'origin', 'quote', 'scriptId', 'variant'}
        rows = [{k: v for k, v in e.items() if k in allowed} for e in plan['entities']]
        self.workflow.save_plan(self.ctx, self.project['id'], {'expectedVersion': plan['version'],
            'stylePrompt': plan['stylePrompt'], 'entities': rows + extra})

    def image(self, entity, recipe='mj_style', refs=None):
        spec = self.workflow.build_spec(self.ctx, {'projectId': self.project['id'], 'entityId': entity,
            'recipe': recipe, 'prompt': '合成图片测试，不发起供应商调用',
            'sourceRevisionIds': refs or [], 'settings': {}}, self.owner)
        raw = io.BytesIO(); Image.new('RGB', (32, 32), 'orange').save(raw, format='PNG')
        task = {**spec, 'id': entity + recipe, 'ownership': self.owner, 'status': 'downloading'}
        revision = self.workflow.record_output(self.ctx, task, raw.getvalue())
        asset = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] if a['id'] == revision['assetId'])
        return self.workflow.review(self.ctx, asset['id'], {'revisionId': revision['id'],
            'sha256': revision['sha256'], 'decision': 'approved', 'note': '合成测试审核',
            'expectedVersion': asset['version']})['revision']

    def complete(self):
        job = self.finish()
        plan = self.production.candidate(self.ctx, job['id'])
        self.workflow.save_plan(self.ctx, self.project['id'], {k: plan[k] for k in ('expectedVersion', 'stylePrompt', 'entities')})
        self.workflow.tasks = self.services.tasks
        selected = {}
        for index, binding in enumerate(job['bindings']):
            style = self.image(binding['entityId'])
            if index == 0:
                self.workflow.confirm_art_direction(self.ctx, self.project['id'], {
                    'revisionId': style['id'], 'sha256': style['sha256'], 'notes': '统一二维手绘',
                    'expectedVersion': 0, 'confirmStyle': True})
            selected[binding['assetId']] = self.image(binding['entityId'], 'image2_asset', [style['id']])['id']
        result = copy.deepcopy(job['result'])
        for shot in result['shots']:
            for ref in shot['references']:
                ref['revisionId'] = selected[ref['assetId']]
        job = self.production.save_review(self.ctx, job['id'], {
            'expectedVersion': 0, 'expectedEditVersion': 0, 'result': result})
        for index, shot in enumerate(job['result']['shots'], 1):
            refs = [r['revisionId'] for r in shot['references']]
            candidate = shot_candidate(job['scriptId'], shot, refs, index)
            self.save_entities([candidate])
            self.image(candidate['id'], 'storyboard_image', refs)
        return job

    def test_uncreated_states_and_shots_are_counted_without_creating_archives(self):
        self.finish()
        before = self.workflow.get_plan(self.ctx, self.project['id'])
        coverage = self.coverage()
        self.assertEqual((coverage['ready'], coverage['total']), (0, 6))
        self.assertFalse(coverage['complete'])
        self.assertEqual(len([r for r in coverage['missing'] if r['category'] == 'shot']), 2)
        self.assertEqual(self.workflow.get_plan(self.ctx, self.project['id']), before)
        self.assertEqual(len(self.provider.submissions), 1)

    def test_complete_current_scope_excludes_unused_history_from_export_but_preserves_it(self):
        job = self.complete()
        self.assertTrue(self.coverage()['complete'])
        self.save_entities([{'id': 'unused', 'category': 'prop', 'name': '历史闲置道具', 'origin': 'manual'}])
        unused = self.image('unused')
        coverage = self.coverage()
        self.assertEqual((coverage['ready'], coverage['total']), (6, 6))
        self.assertFalse(any(r.get('stages', {}).get('refine') for r in coverage['entities']))
        _, manifest = self.workflow.export(self.ctx, self.project['id'])
        self.assertNotIn(unused['id'], [r['revisionId'] for r in manifest['assets']])
        version = self.workflow.get_project(self.ctx, self.project['id'])['version']
        bundle = self.workflow.archive(self.ctx, self.project['id'], {'expectedVersion': version})
        old_raw = self.workflow.bundle_content(self.ctx, self.project['id'], bundle['id'])
        result = copy.deepcopy(job['result']); result['shots'][0]['camera'] = '修改机位'
        self.production.save_review(self.ctx, job['id'], {'expectedVersion': job['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
        self.assertEqual(self.coverage()['ready'], 5)
        self.assertEqual(self.workflow.bundle_content(self.ctx, self.project['id'], bundle['id']), old_raw)
        self.assertTrue(self.workflow.content(self.ctx, unused['assetId'], unused['id'])[0])

    def test_new_script_and_invalid_review_cannot_inherit_completed_coverage(self):
        job = self.complete()
        result = copy.deepcopy(job['result']); result['shots'][0]['evidence'][0]['quote'] = '原文不存在'
        self.production.save_review(self.ctx, job['id'], {'expectedVersion': job['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
        self.assertFalse(self.coverage()['complete'])
        self.assertIn('待核对', self.coverage()['message'])
        self.workflow.import_script(self.ctx, self.project['id'], {'filename': '第二稿.txt',
            'contentBase64': base64.b64encode('第二稿\n林舟：修改后的故事。'.encode()).decode()})
        self.assertEqual(self.coverage()['total'], 0)
        self.assertIn('当前剧本', self.coverage()['message'])
        with self.assertRaises(WorkflowError): self.workflow.export(self.ctx, self.project['id'])

    def test_changed_design_is_missing_even_when_old_images_are_still_approved(self):
        job = self.complete()
        result = copy.deepcopy(job['result']); result['assets'][0]['design'] = '换成新版人物服装'
        self.production.save_review(self.ctx, job['id'], {'expectedVersion': job['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
        coverage = self.coverage()
        self.assertEqual(coverage['ready'], 3)
        self.assertTrue(any(r.get('assetId') == 'a_lin' for r in coverage['missing']))

    def test_archive_rejects_production_change_between_export_and_confirmation(self):
        job = self.complete()
        original = self.workflow.export
        def concurrent(ctx, project_id):
            exported = original(ctx, project_id)
            result = copy.deepcopy(job['result']); result['uncertainties'].append('新核对项')
            self.production.save_review(ctx, job['id'], {'expectedVersion': job['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
            return exported
        version = self.workflow.get_project(self.ctx, self.project['id'])['version']
        with patch.object(self.workflow, 'export', side_effect=concurrent), self.assertRaises(WorkflowError):
            self.workflow.archive(self.ctx, self.project['id'], {'expectedVersion': version})
        self.assertEqual(self.workflow.list_bundles(self.ctx, self.project['id'])['items'], [])

    def test_final_commit_checks_production_snapshot_in_same_storage_transaction(self):
        job = self.finish()
        with self.assertRaises(WorkflowError):
            with self.workflow.repository.transaction(self.ctx, write=True) as tx:
                self.workflow._coverage(tx, self.project['id'])
                result = copy.deepcopy(job['result']); result['uncertainties'].append('并发改动')
                self.production.save_review(self.ctx, job['id'], {'expectedVersion': 0, 'expectedEditVersion': 0, 'result': result})
