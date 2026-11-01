import copy
import json
import unittest
import test_analysis as fixture
from backend.workflow import WorkflowError
from backend.storage import StorageError


class AnalysisReviewTests(unittest.TestCase):
    setUp = fixture.AnalysisTests.setUp
    begin = fixture.AnalysisTests.begin

    def failed_result(self):
        self.ai.analysis_policy = 'single'
        result = copy.deepcopy(fixture.EXAMPLE['result']); result['sourceRevision'] = self.script['sourceRevision']
        result['characters'][0]['evidence'][0]['quote'] = '错误引用……'
        self.provider.text = json.dumps(result)
        job = self.begin()
        self.ai.advance(self.ctx, job['id']); self.ai.advance(self.ctx, job['id'])
        return self.ai.get(self.ctx, job['id'])

    def payload(self, job, result):
        return {'expectedVersion': job['reviewVersion'], 'expectedResultHash': job['resultHash'], 'result': result}

    def test_failed_literal_check_exposes_result_and_manual_fix_without_new_call(self):
        job = self.failed_result()
        self.assertEqual(job['status'], 'needs_review')
        self.assertIsNone(job['result'])
        self.assertEqual(job['validationIssues'][0]['path'], 'characters.0.evidence.0.quote')
        self.assertTrue(job['validationIssues'][0]['sourceText'])
        result = copy.deepcopy(job['draftResult'])
        result['characters'][0]['evidence'][0]['quote'] = fixture.EXAMPLE['result']['characters'][0]['evidence'][0]['quote']
        updated = self.ai.save_review(self.ctx, job['id'], self.payload(job, result))
        self.assertEqual(updated['status'], 'ready')
        self.assertEqual(updated['validationIssues'], [])
        self.assertFalse(updated['canResumeReview'])
        self.assertFalse(updated['canRepairResult'])
        self.assertEqual(len(self.provider.submissions), 1)
        self.assertEqual(self.ai._get(self.ctx, job['id'])['data']['status'], 'failed')
        self.assertTrue(self.ai.candidate(self.ctx, job['id'])['entities'])
        self.assertEqual(len(self.store.list(self.ctx, 'analysis.review_history')['items']), 1)

    def test_partial_corrections_are_saved_but_not_used_as_valid_production(self):
        job = self.failed_result()
        result = copy.deepcopy(job['draftResult']); result['characters'][0]['name'] = '人工修改的名字'
        updated = self.ai.save_review(self.ctx, job['id'], self.payload(job, result))
        self.assertEqual(updated['status'], 'needs_review')
        self.assertEqual(updated['draftResult']['characters'][0]['name'], '人工修改的名字')
        with self.assertRaises(WorkflowError): self.ai.candidate(self.ctx, job['id'])
        self.assertEqual(len(self.provider.submissions), 1)

    def test_edit_conflict_and_other_tenant_cannot_overwrite_original(self):
        job = self.failed_result(); payload = self.payload(job, job['draftResult'])
        with self.assertRaises((WorkflowError, StorageError)): self.ai.save_review(self.other, job['id'], payload)
        self.ai.save_review(self.ctx, job['id'], payload)
        with self.assertRaises(WorkflowError): self.ai.save_review(self.ctx, job['id'], payload)

    def test_malformed_return_is_visible_and_can_be_completed_manually(self):
        self.ai.analysis_policy = 'single'; self.provider.text = '{"complete":'
        job = self.begin(); self.ai.advance(self.ctx, job['id']); self.ai.advance(self.ctx, job['id'])
        job = self.ai.get(self.ctx, job['id'])
        self.assertEqual(job['returnedText'], self.provider.text)
        self.assertEqual(job['status'], 'needs_review')
        result = copy.deepcopy(fixture.EXAMPLE['result']); result['sourceRevision'] = self.script['sourceRevision']
        updated = self.ai.save_review(self.ctx, job['id'], self.payload(job, result))
        self.assertEqual(updated['status'], 'ready')
        self.assertEqual(len(self.provider.submissions), 1)
