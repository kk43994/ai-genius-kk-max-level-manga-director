"""Portable deliverables use synthetic fixtures and never invoke a provider."""
import copy
import hashlib
import io
import json
import unittest
import zipfile
from unittest.mock import patch

import test_production_coverage as fixture
from backend.workflow import WorkflowError
from backend.storage import StorageError


class StoryboardExportTests(unittest.TestCase):
    setUp = fixture.CoverageTests.setUp
    finish = fixture.CoverageTests.finish
    begin = fixture.CoverageTests.begin
    complete = fixture.CoverageTests.complete
    save_entities = fixture.CoverageTests.save_entities
    image = fixture.CoverageTests.image

    def test_complete_package_preserves_dialogue_and_exact_approved_images(self):
        job = self.complete()
        before = len(self.provider.submissions)
        raw, manifest = self.production.export_storyboard(self.ctx, job['id'])
        self.assertTrue(manifest['complete'])
        self.assertEqual(manifest['illustratedShots'], 2)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            html = archive.read('分镜脚本.html').decode()
            self.assertEqual(json.loads(archive.read('storyboard.json')), manifest)
            for shot in manifest['shots']:
                self.assertEqual(hashlib.sha256(archive.read(shot['image']['file'])).hexdigest(), shot['image']['sha256'])
                for dialogue in shot['dialogues']:
                    self.assertIn(dialogue['text'], html)
        self.assertEqual(len(self.provider.submissions), before)

    def test_partial_package_marks_missing_images_and_escapes_prose(self):
        job = self.finish()
        result = copy.deepcopy(job['result'])
        result['shots'][0]['camera'] = '<script>alert(1)</script>'
        self.production.save_review(self.ctx, job['id'], {'expectedVersion': 0, 'expectedEditVersion': 0, 'result': result})
        raw, manifest = self.production.export_storyboard(self.ctx, job['id'])
        self.assertFalse(manifest['complete'])
        self.assertEqual(manifest['illustratedShots'], 0)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            html = archive.read('分镜脚本.html').decode()
            self.assertIn('分镜图待生成或待审核', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)

    def test_old_approved_image_is_excluded_after_shot_changes(self):
        job = self.complete()
        result = copy.deepcopy(job['result']); result['shots'][0]['camera'] = '新版摄影机位'
        self.production.save_review(self.ctx, job['id'], {'expectedVersion': job['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
        _, manifest = self.production.export_storyboard(self.ctx, job['id'])
        self.assertFalse(manifest['complete'])
        self.assertIsNone(manifest['shots'][0]['image'])
        self.assertEqual(manifest['illustratedShots'], 1)

    def test_tenant_boundary_and_snapshot_conflict_fail_closed(self):
        job = self.finish()
        with self.assertRaises((StorageError, WorkflowError)):
            self.production.export_storyboard(self.other, job['id'])
        original = self.production.get
        changed = []
        def concurrent(ctx, identity):
            current = original(ctx, identity)
            if changed: return current
            changed.append(True)
            result = copy.deepcopy(current['result']); result['shots'][0]['camera'] = '并发修改'
            self.production.save_review(ctx, identity, {'expectedVersion': current['reviewVersion'], 'expectedEditVersion': 0, 'result': result})
            return current
        with patch.object(self.production, 'get', side_effect=concurrent), self.assertRaises(WorkflowError):
            self.production.export_storyboard(self.ctx, job['id'])
