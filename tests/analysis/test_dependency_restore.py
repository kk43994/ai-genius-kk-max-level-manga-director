"""Reselecting exact original sources restores validity, never human approval."""
import copy
import unittest
from unittest.mock import patch

import test_production_coverage as fixture
from backend.workflow import WorkflowError


class DependencyRestoreTests(unittest.TestCase):
    setUp = fixture.CoverageTests.setUp
    begin = fixture.CoverageTests.begin
    finish = fixture.CoverageTests.finish
    image = fixture.CoverageTests.image
    save_entities = fixture.CoverageTests.save_entities
    coverage = fixture.CoverageTests.coverage
    complete = fixture.CoverageTests.complete

    def revisions(self):
        return {r['id']: r for a in self.workflow.list_assets(self.ctx, self.project['id'])['items']
                for r in a['revisions']}

    def select(self, revision, decision='approved'):
        asset = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items']
                     if a['id'] == revision['assetId'])
        return self.workflow.review(self.ctx, asset['id'], {
            'revisionId': revision['id'], 'sha256': revision['sha256'], 'decision': decision,
            'note': '合成依赖恢复测试', 'expectedVersion': asset['version']})

    def replace_style(self):
        self.job = self.complete()
        before = self.revisions()
        direction = self.workflow.get_project(self.ctx, self.project['id'])['artDirection']
        self.original = before[direction['revisionId']]
        self.image(self.original['entityId'], 'image25_style')
        self.assertFalse(self.coverage()['complete'])
        self.assertTrue(all(r['status'] == 'stale' for r in self.revisions().values()
                            if r['stage'] in ('asset', 'storyboard')))
        return before

    def test_reselect_original_restores_existing_asset_and_storyboard_chain_without_reapproval(self):
        before = self.replace_style()
        self.select(self.original)
        # Reading and exporting already stored work must not need provider auth.
        with patch.object(self.services.tasks, '_owner', side_effect=AssertionError('No provider access')):
            after = self.revisions()
            self.assertTrue(self.coverage()['complete'])
            _, manifest = self.workflow.export(self.ctx, self.project['id'])
        for identity, revision in before.items():
            if revision['stage'] not in ('asset', 'storyboard'):
                continue
            self.assertEqual(after[identity]['status'], 'ready')
            self.assertNotIn('staleReason', after[identity])
            for key in ('review', 'reviewHistory', 'sourceRevisionIds', 'sha256', 'taskId'):
                self.assertEqual(after[identity][key], revision[key])
            self.assertIn(identity, [r['revisionId'] for r in manifest['assets']])
        # Compatibility is computed on read; no rewrite of old receipts/records.
        with self.workflow.repository.transaction(self.ctx) as tx:
            old = next(r for r in tx.state['revisions'].values() if r['stage'] == 'storyboard')
            self.assertEqual(old['status'], 'stale')

    def test_restoring_style_does_not_revive_changed_design_or_other_art_direction_version(self):
        self.replace_style()
        result = copy.deepcopy(self.job['result'])
        result['assets'][0]['design'] = '另一个服装设计'
        self.production.save_review(self.ctx, self.job['id'], {
            'expectedVersion': self.job['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
        self.select(self.original)
        self.assertFalse(self.coverage()['complete'])
        self.assertTrue(any(r['status'] == 'stale' for r in self.revisions().values() if r['stage'] == 'asset'))
        self.workflow.confirm_art_direction(self.ctx, self.project['id'], {
            'revisionId': self.original['id'], 'sha256': self.original['sha256'],
            'notes': '明确更改全剧规范', 'expectedVersion': 1, 'confirmStyle': True})
        self.assertTrue(all(r['status'] == 'stale' for r in self.revisions().values()
                            if r['stage'] in ('asset', 'storyboard')))

    def test_returned_images_are_not_automatically_kept_on_dependency_restore(self):
        self.complete()
        revisions = self.revisions()
        direction = self.workflow.get_project(self.ctx, self.project['id'])['artDirection']
        original = revisions[direction['revisionId']]
        shot = next(r for r in revisions.values() if r['stage'] == 'storyboard')
        self.select(shot, 'changes_requested')
        self.image(original['entityId'], 'image25_style')
        self.select(original)
        returned = self.revisions()[shot['id']]
        self.assertEqual((returned['status'], returned['review']), ('ready', 'changes_requested'))
        self.assertNotIn(shot['id'], self.coverage()['exportRevisionIds'])

    def test_unrecognized_stale_records_remain_unusable(self):
        self.complete()
        revision = next(r for r in self.revisions().values() if r['stage'] == 'storyboard')
        with self.workflow.repository.transaction(self.ctx, write=True) as tx:
            tx.state['revisions'][revision['id']].update(status='stale', staleReason='unknown invalidation')
        with self.assertRaises(WorkflowError):
            self.workflow.get_revision(self.ctx, revision['id'])


if __name__ == '__main__':
    unittest.main()
