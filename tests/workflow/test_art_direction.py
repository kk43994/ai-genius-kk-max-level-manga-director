"""Human art-direction gates and immutable lineage using synthetic images."""
import unittest
from types import SimpleNamespace
import test_workflow as fixture
from backend.workflow import WorkflowError


class ArtDirectionTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    task = fixture.WorkflowTests.task
    output = fixture.WorkflowTests.output
    review = fixture.WorkflowTests.review
    asset = fixture.WorkflowTests.asset

    def confirm(self, revision, version=0, notes='统一二维手绘，柔和配色和细线条'):
        self.workflow.tasks = SimpleNamespace(_selection=lambda ctx:{}, _owner=lambda ctx,s:self.owner)
        return self.workflow.confirm_art_direction(self.ctx, self.project_id, {
            'revisionId':revision['id'], 'sha256':revision['sha256'], 'notes':notes,
            'expectedVersion':version, 'confirmStyle':True})

    def test_confirmation_requires_chosen_image_and_preserves_existing_plan(self):
        style=self.output('mj_style');before=self.workflow.get_plan(self.ctx,self.project_id)
        with self.assertRaises(WorkflowError):self.confirm(style)
        style=self.review(style);direction=self.confirm(style)
        self.assertTrue(direction['valid']);self.assertEqual(direction['version'],1)
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project_id),before)
        with self.assertRaises(WorkflowError):self.confirm(style)
        self.assertEqual(self.confirm(style,1)['version'],1)
        project=self.workflow.get_project(self.ctx,self.project_id)
        self.assertEqual(len(project['artDirectionHistory']),1)

    def test_new_assets_snapshot_direction_and_changing_it_does_not_delete_old_images(self):
        style=self.review(self.output('mj_style'));self.confirm(style)
        task=self.task('image2_asset',source=style['id'])
        self.assertIn('本剧美术规范 v1',task['prompt'])
        self.assertEqual(task['workflowSnapshot']['artDirectionVersion'],1)
        asset=self.workflow.record_output(self.ctx,task,fixture.png())
        self.assertEqual(asset['artDirectionVersion'],1)
        self.confirm(style,1,'新版：统一水彩质感')
        current=self.asset(asset)['revisions']
        self.assertEqual(next(r for r in current if r['id']==asset['id'])['status'],'stale')
        self.assertEqual(next(r for r in current if r['id']==style['id'])['status'],'ready')
        self.assertEqual(len(current),2)

    def test_foreign_owner_and_source_change_cannot_silently_continue(self):
        style=self.review(self.output('mj_style'));self.confirm(style)
        with self.assertRaises(WorkflowError):self.task('mj_style',owner={**self.owner,'spaceId':'foreign'})
        replacement=self.review(self.output('mj_style',color=(200,100,90)))
        self.assertFalse(self.workflow.get_project(self.ctx,self.project_id)['artDirection']['valid'])
        with self.assertRaises(WorkflowError):self.task('image2_asset',source=replacement['id'])

    def test_approved_standard_assets_can_complete_without_optional_refinement(self):
        for entity in ('ent_character','ent_scene','ent_prop'):
            style=self.review(self.output('mj_style',entity=entity))
            self.review(self.output('image2_asset',entity=entity,source=style['id']))
        coverage=self.workflow.list_assets(self.ctx,self.project_id)['coverage']
        self.assertTrue(coverage['complete'])
        self.assertFalse(any(row['stages']['refine'] for row in coverage['entities']))
