"""Reroll editing inputs preserve adoption, ownership, lineage and original bytes."""
import copy
import io
import unittest
from PIL import Image

import test_production_coverage as coverage_fixture
from backend.workflow import WorkflowError
from backend.workflow.image_edit import editing_reference


class ImageEditTests(unittest.TestCase):
    setUp = coverage_fixture.CoverageTests.setUp
    finish = coverage_fixture.CoverageTests.finish
    begin = coverage_fixture.CoverageTests.begin
    save_entities = coverage_fixture.CoverageTests.save_entities
    image = coverage_fixture.CoverageTests.image
    complete = coverage_fixture.CoverageTests.complete

    def setup_edit(self):
        job = self.production.get(self.ctx, self.complete()['id'])
        asset = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] if a['category'] == 'shot')
        r = asset['revisions'][0]
        body = {'recipe': 'image25_storyboard', 'shotId': next(b['shotId'] for b in job['shotBindings'] if b['entityId'] == r['entityId']),
                'prompt': '保持人物与仓库设计', 'settings': {'count': 1},
                'expectedReviewVersion': job['reviewVersion'], 'expectedEditVersion': job['editVersion'],
                'expectedPlanVersion': self.workflow.get_plan(self.ctx, self.project['id'])['version'],
                'expectedSelectionRevision': 1, 'expectedArtDirectionVersion': 1, 'idempotencyKey': 'edit-test',
                'editRevisionId': r['id'], 'editSha256': r['sha256'], 'editNote': '只修正手部姿势', 'confirmEditReference': True}
        calls = []
        def prepare(ctx, spec, rev, key):
            verified = self.workflow.build_spec(ctx, spec, self.owner)
            calls.append(verified)
            return {'task': {'id': 'synthetic'}, 'confirmation': {}}
        self.services.tasks.prepare = prepare
        return job, r, body, calls

    def test_reroll_uses_exact_bytes_and_original_references_without_changing_adoption(self):
        job, r, body, calls = self.setup_edit()
        before = copy.deepcopy(self.workflow.get_revision(self.ctx, r['id']))
        self.production.prepare_image(self.ctx, job['id'], body)
        self.production.prepare_image(self.ctx, job['id'], body)
        self.assertEqual(calls[0], calls[1])
        spec = calls[0]
        self.assertEqual(spec['sourceRevisionIds'][:-1], r['sourceRevisionIds'])
        seed = self.workflow.get_revision(self.ctx, spec['sourceRevisionIds'][-1])
        self.assertEqual(seed['sha256'], r['sha256'])
        self.assertEqual(seed['provenance']['revisionId'], r['id'])
        self.assertEqual(seed['reviewHistory'][0]['purpose'], 'edit_reference')
        self.assertIn('只修正手部姿势', spec['prompt'])
        self.assertIn('{{reference:' + seed['id'] + '}}', spec['prompt'])
        self.assertEqual(before, self.workflow.get_revision(self.ctx, r['id']))
        raw = io.BytesIO(); Image.new('RGB', (32, 32), 'blue').save(raw, format='PNG')
        new = self.workflow.record_output(self.ctx, {**spec, 'id': 'reroll-task', 'ownership': self.owner, 'status': 'downloading'}, raw.getvalue())
        self.assertEqual(new['review'], 'pending')
        self.assertEqual(self.workflow.get_revision(self.ctx, r['id'])['review'], 'approved')
        # A second correction replaces the old seed rather than accumulating images.
        body.update(editRevisionId=new['id'], editSha256=new['sha256'], prompt=spec['prompt'])
        self.production.prepare_image(self.ctx, job['id'], body)
        self.assertEqual(len(calls[-1]['sourceRevisionIds']), len(spec['sourceRevisionIds']))
        self.assertNotIn(seed['id'], calls[-1]['sourceRevisionIds'])
        self.assertNotIn(seed['id'], calls[-1]['prompt'])

    def test_pending_and_returned_candidates_can_be_edit_inputs_but_are_not_adopted(self):
        job, r, body, calls = self.setup_edit()
        for review in ('pending', 'changes_requested'):
            with self.workflow.repository.transaction(self.ctx, write=True) as tx:
                tx.state['revisions'][r['id']]['review'] = review
            self.production.prepare_image(self.ctx, job['id'], body)
            self.assertEqual(self.workflow.get_revision(self.ctx, r['id'], require_approved=False)['review'], review)
        self.assertEqual(len(calls), 2)

    def test_rejects_missing_consent_wrong_hash_target_owner_and_stale_source(self):
        job, r, body, calls = self.setup_edit()
        for patch in ({'confirmEditReference': False}, {'editSha256': 'wrong'}, {'editNote': 'x' * 2001}):
            with self.subTest(patch=next(iter(patch))), self.assertRaises(WorkflowError):
                self.production.prepare_image(self.ctx, job['id'], {**body, **patch})
        for target, owner, recipe in (('different', self.owner, body['recipe']),
                                     (r['entityId'], {**self.owner, 'spaceId': 'other'}, body['recipe']),
                                     (r['entityId'], self.owner, 'image25_asset')):
            with self.assertRaises(WorkflowError):
                editing_reference(self.workflow, self.ctx, self.project['id'], target, owner, recipe, body)
        with self.workflow.repository.transaction(self.ctx, write=True) as tx:
            tx.state['revisions'][r['id']]['status'] = 'stale'
            tx.state['revisions'][r['id']]['staleReason'] = 'unknown'
        with self.assertRaises(WorkflowError):
            self.production.prepare_image(self.ctx, job['id'], body)
        self.assertEqual(calls, [])

    def test_new_version_can_be_selected_without_invalidating_itself_via_old_image(self):
        job, r, body, calls = self.setup_edit()
        self.production.prepare_image(self.ctx, job['id'], body)
        raw = io.BytesIO(); Image.new('RGB', (32, 32), 'blue').save(raw, format='PNG')
        new = self.workflow.record_output(self.ctx, {**calls[0], 'id': 'reroll-task', 'ownership': self.owner, 'status': 'downloading'}, raw.getvalue())
        asset = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] if a['id'] == r['assetId'])
        result = self.workflow.review(self.ctx, asset['id'], {'revisionId': new['id'], 'sha256': new['sha256'],
            'expectedVersion': asset['version'], 'decision': 'approved', 'note': '人工选用新版本'})
        self.assertEqual(result['revision']['status'], 'ready')
        self.assertEqual(self.workflow.get_revision(self.ctx, r['id'], require_approved=False)['review'], 'superseded')

    def test_character_master_reroll_keeps_primary_identity_reference(self):
        job, _, body, calls = self.setup_edit()
        binding = next(b for b in job['bindings'] if b['stateId'] == '__character_master__')
        asset = next(a for a in self.workflow.list_assets(self.ctx, self.project['id'])['items'] if a['entityId'] == binding['entityId'])
        original = next(r for r in asset['revisions'] if r['stage'] == 'asset')
        body.update(recipe='image25_asset', assetId=binding['assetId'], stateId=binding['stateId'],
                    editRevisionId=original['id'], editSha256=original['sha256'])
        self.production.prepare_image(self.ctx, job['id'], body)
        self.assertEqual(calls[0]['sourceRevisionIds'][0], original['sourceRevisionIds'][0])
        self.assertEqual(calls[0]['entityId'], original['entityId'])
        self.assertEqual(self.workflow.get_revision(self.ctx, original['id'])['review'], 'approved')


if __name__ == '__main__': unittest.main()
