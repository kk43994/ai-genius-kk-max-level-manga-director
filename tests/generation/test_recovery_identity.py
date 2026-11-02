"""Partial project receipts are shared; recovery must retain local task identity."""
import copy
import tempfile
import unittest
from pathlib import Path

from backend.generation.errors import GenerationError
from helpers import Fixture


class RecoveryIdentityTests(unittest.TestCase):
    def test_shared_project_receipt_resolves_only_explicit_owned_task(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(Path(root).resolve()); f.prepare(); f.confirm()
            receipt = f.prepared['providerReceipt']
            with f.repository.transaction(f.ctx) as tx:
                other = copy.deepcopy(tx.get_task(f.p['localTaskId']))
                other['id'] = 'second_upload_task'
                tx.put_task(other, None)
            with self.assertRaises(GenerationError):
                f.bridge.task_for_receipt(f.owner, receipt)
            for task_id in [f.p['localTaskId'], other['id']]:
                self.assertEqual(task_id, f.bridge.task_for_receipt(f.owner, receipt, local_task_id=task_id))
            for task_id, ownership, changed in [
                ('missing', f.owner, receipt),
                (other['id'], {**f.owner, 'spaceId':'foreign'}, receipt),
                (other['id'], f.owner, {'projectId':'foreign'}),
            ]:
                with self.assertRaises(GenerationError):
                    f.bridge.task_for_receipt(ownership, changed, local_task_id=task_id)
