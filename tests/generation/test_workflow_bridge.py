"""Real task + Store + workflow image persistence; provider responses are synthetic."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.generation import WorkflowReferenceReader
from backend.tasks import TaskPolicy, TaskService
from backend.workflow import WorkflowOutputStore, WorkflowRepository, WorkflowService
from helpers import Fixture


class WorkflowBridgeTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'work' / 'generation-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        f = self.f = Fixture(self.tmp.name)
        self.workflow = WorkflowService(WorkflowRepository(f.store))
        self.project = self.workflow.create_project(f.ctx, {'name': 'Synthetic integration', 'description': 'No real assets'})
        self.plan = self.workflow.save_plan(f.ctx, self.project['id'], {'expectedVersion': 0, 'stylePrompt': 'Test style',
            'entities': [{'id': 'entity_one', 'category': 'character', 'name': 'Synthetic', 'description': 'Test', 'origin': 'manual'}]})
        selected = {'providerAccountId': f.owner['providerAccountId'], 'spaceId': f.owner['spaceId'], 'revision': 1}
        f.repository.selection_reader = lambda tx: selected
        class Client:
            def __init__(self, bound): self.bound = bound
            def __getattr__(self, name): return getattr(self.bound, name)
            def identity(self):
                return {'issuer': f.owner['providerIssuer'], 'subject': f.owner['providerSubject'], 'verified': True}
        class Providers:
            def get_account(self, ctx, account):
                return {'id': account, 'provider': 'libtv', 'identity': {'issuer': f.owner['providerIssuer'],
                         'subject': f.owner['providerSubject'], 'verified': True}, 'authorization': {'state': 'connected'}}
            def client_for(self, ctx, owner):
                return Client(f.adapter.bind(ownership=owner, authorize=f.authorize))
        self.tasks = TaskService(repository=f.repository, providers=Providers(),
            selections=SimpleNamespace(get_selection=lambda ctx: copy.deepcopy(selected)),
            spaces=SimpleNamespace(get_space=lambda ctx, a, s: {'id': s, 'kind': 'personal', 'access': 'available'}),
            inputs=self.workflow, outputs=WorkflowOutputStore(self.workflow, f.repository),
            policy=TaskPolicy(confirmation_key=b'T' * 32, allow_paid_submission=True))
        f.adapter.references = WorkflowReferenceReader(self.workflow, f.ctx)
        for name in ['socket.create_connection', 'socket.getaddrinfo']:
            guard = patch(name, side_effect=AssertionError('LIVE NETWORK FORBIDDEN'))
            guard.start()
            self.addCleanup(guard.stop)

    def finish_style(self):
        spec = {'projectId': self.project['id'], 'entityId': 'entity_one', 'recipe': 'mj_style',
                'prompt': 'Synthetic image', 'settings': {}, 'sourceRevisionIds': []}
        prepared = self.tasks.prepare(self.f.ctx, spec, 1, 'integration-prepare-1')
        self.assertEqual(prepared['task']['status'], 'draft', prepared['task'].get('error'))
        task = self.tasks.submit(self.f.ctx, prepared['task']['id'], prepared['task']['version'],
                                 prepared['confirmation']['token'], 'integration-submit-1')['task']
        self.assertEqual(task['status'], 'queued', task.get('error'))
        task = self.tasks.recover(self.f.ctx, task['id'], task['version'])['task']
        self.assertEqual(task['status'], 'completed', task.get('error'))
        return task

    def test_real_task_to_workflow_preserves_snapshot_and_requires_human_review(self):
        task = self.finish_style()
        output = task['outputs'][0]
        revision = self.workflow.get_revision(self.f.ctx, output['revisionId'], require_approved=False)
        self.assertEqual(revision['sha256'], output['sha256'])
        self.assertEqual(revision['styleVersion'], self.plan['styleVersion'])
        self.assertEqual(revision['review'], 'pending')
        self.assertEqual(self.workflow.content(self.f.ctx, output['assetId'], output['revisionId'])[0], self.f.raw)
        self.assertEqual(self.f.count('generation_submit'), 1)

    def test_workflow_reference_reader_uses_approved_revision_and_original_bytes(self):
        task = self.finish_style()
        output = task['outputs'][0]
        snapshot = {'revisionId': output['revisionId'], 'sha256': output['sha256']}
        with self.assertRaises(Exception):
            self.f.adapter.references.read(task['ownership'], snapshot)
        asset = next(a for a in self.workflow.list_assets(self.f.ctx, self.project['id'])['items'] if a['id'] == output['assetId'])
        self.workflow.review(self.f.ctx, output['assetId'], {'revisionId': output['revisionId'],
            'sha256': output['sha256'], 'decision': 'approved', 'note': 'Synthetic test review', 'expectedVersion': asset['version']})
        reference = self.f.adapter.references.read(task['ownership'], snapshot)
        self.assertEqual(reference.content, self.f.raw)
        self.assertEqual(reference.stage, 'style')
        self.assertTrue(reference.approved)

    def test_image2_preparation_accepts_task_snapshot_but_rereads_actual_review(self):
        task = self.finish_style(); output = task['outputs'][0]
        spec = {'projectId': self.project['id'], 'entityId': 'entity_one', 'recipe': 'image2_asset',
                'prompt': 'Synthetic four views', 'settings': {}, 'sourceRevisionIds': [output['revisionId']]}
        with self.assertRaises(Exception):
            self.tasks.prepare(self.f.ctx, spec, 1, 'asset-before-review')
        asset = next(a for a in self.workflow.list_assets(self.f.ctx, self.project['id'])['items'] if a['id'] == output['assetId'])
        self.workflow.review(self.f.ctx, output['assetId'], {'revisionId': output['revisionId'],
            'sha256': output['sha256'], 'decision': 'approved', 'note': 'Synthetic test review', 'expectedVersion': asset['version']})
        prepared = self.tasks.prepare(self.f.ctx, spec, 1, 'asset-after-review')
        self.assertEqual(prepared['task']['status'], 'draft', prepared['task'].get('error'))
        self.assertTrue(prepared['confirmation'])
        self.assertEqual(prepared['confirmation']['summary']['sourceRevisionIds'], [output['revisionId']])
        self.assertEqual(self.f.count('generation_submit'), 1)


if __name__ == '__main__':
    unittest.main()
