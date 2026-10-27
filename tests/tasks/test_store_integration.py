"""Optional real shared-Store integration, enabled after module 3 is available.

ASSET_LAB_STORAGE_MODULE_ROOT=/absolute/path/to/module3/repo adds that read-only
backend package path. All data, sessions, grants and provider calls are synthetic.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import backend

if os.environ.get("ASSET_LAB_STORAGE_MODULE_ROOT"):
    backend.__path__.append(str(Path(os.environ["ASSET_LAB_STORAGE_MODULE_ROOT"]).resolve() / "backend"))

try:
    from backend.sessions import SessionService
    from backend.storage import AccountRepository, SelectionRepository, Store, VerifiedIdentity
except ImportError:
    Store = None

from backend.tasks import TaskError, TaskPolicy, TaskService
from backend.tasks.adapters import SelectionAdapter, StoreOutputStore, StoreTaskRepository
from support import Fixture, ProcessCrash, spec


@unittest.skipIf(Store is None, "shared storage module and cryptography dependency are not installed")
class SharedStoreTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "work" / "task-store-tests"
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = Fixture(self.root / "fixture.sqlite3")
        self.release = self.root / "release"
        self.release.mkdir()
        self.store = Store(self.root / "data", encryption_key=b"S" * 32, release_root=self.release,
                           clock=lambda: self.f.clock().timestamp())
        self.sessions = SessionService(self.store, public_origin="https://test.invalid")
        self.f.ctx, self.f.other = self.sessions.create().context, self.sessions.create().context
        self.accounts, self.selections = AccountRepository(self.store), SelectionRepository(self.store)
        self.account = self.accounts.complete_authorization(
            self.f.ctx, VerifiedIdentity("https://official-test.invalid", "synthetic-subject"),
            {"access_token": "synthetic-secret-only"}, minimum_read_verified=True,
            expected_authorization_epoch=self.accounts.authorization_epoch(self.f.ctx),
            expires_at=self.f.clock().timestamp() + 3600)
        self.selections.replace_spaces(self.f.ctx, self.account["id"], [
            {"id": "space_personal", "kind": "personal", "name": "合成个人空间", "access": "available"},
            {"id": "space_team", "kind": "team", "name": "合成团队空间", "access": "available"}])
        self.selections.set(self.f.ctx, self.account["id"], "space_personal", expected_revision=0)
        self.f.providers.add_account(self.f.ctx.tenantId, self.account["id"], "synthetic-subject")
        self.repository = StoreTaskRepository(self.store, selection_reader=SelectionRepository._get)
        self.output_store = StoreOutputStore(self.store)
        self.f.service = self.new_service()
        self.f.selections = SelectionAdapter(self.selections)

    def new_service(self, store=None):
        store = store or self.store
        return TaskService(repository=StoreTaskRepository(store, selection_reader=SelectionRepository._get),
                           providers=self.f.providers, selections=SelectionAdapter(SelectionRepository(store)),
                           spaces=self.f.spaces, inputs=self.f.inputs, outputs=StoreOutputStore(store),
                           policy=TaskPolicy(confirmation_key=b"C" * 32, allow_paid_submission=True), clock=self.f.clock)

    def test_shared_store_persists_tasks_requests_and_immutable_ownership(self):
        prepared = self.f.prepare()
        row = self.store.get(self.f.ctx, "tasks", prepared["task"]["id"])
        self.assertEqual(row["data"]["version"], row["version"])
        self.assertEqual(row["data"]["ownership"], prepared["task"]["ownership"])
        restarted = Store(self.root / "data", encryption_key=b"S" * 32,
                          release_root=self.root / "release-next", clock=lambda: self.f.clock().timestamp())
        replay = self.new_service(restarted).prepare(self.f.ctx, spec(), 1, "prepare-key-001")
        self.assertEqual(replay, prepared)
        changed = {**row["data"], "version": row["version"] + 1,
                   "ownership": {**row["data"]["ownership"], "spaceId": "space_team"}}
        with self.assertRaises(TaskError) as cm:
            with self.repository.transaction(self.f.ctx) as tx:
                tx.put_task(changed, row["version"])
        self.assertEqual(cm.exception.code, "OWNERSHIP_MISMATCH")

    def test_selection_cas_and_task_insert_share_real_transaction(self):
        def switch(*args):
            self.selections.set(self.f.ctx, self.account["id"], "space_team", expected_revision=1)
        self.f.inputs.hook = switch
        with self.assertRaises(TaskError) as cm:
            self.f.prepare()
        self.assertEqual(cm.exception.code, "SELECTION_CHANGED")
        self.assertEqual(self.store.list(self.f.ctx, "tasks")["items"], [])
        self.assertEqual(self.store.list(self.f.ctx, "task_requests")["items"], [])

    def test_downloads_saved_and_verified_through_shared_private_blob_store(self):
        task = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed"}
        task = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(task["status"], "completed")
        content, metadata = self.store.blob_get(self.f.ctx, task["outputs"][0]["blobId"])
        self.assertEqual(content, b"synthetic image bytes")
        self.assertEqual(metadata["sha256"], task["outputs"][0]["sha256"])
        with self.assertRaises(TaskError) as cm:
            self.output_store.read(self.f.other, task["outputs"][0]["blobId"])
        self.assertEqual(cm.exception.code, "NOT_FOUND")
        self.assertNotIn("synthetic-secret-only", self.store.db_path.read_bytes().decode("latin1"))

    def test_new_python_process_recovers_crash_without_second_submission(self):
        prepared = self.f.prepare()
        self.f.providers.submit_error = ProcessCrash()
        with self.assertRaises(ProcessCrash):
            self.f.submit(prepared)
        script = '''
import json,sys
from datetime import datetime,timezone
from types import SimpleNamespace
from pathlib import Path
import backend
p=json.load(sys.stdin)
if p['moduleRoot']: backend.__path__.append(str(Path(p['moduleRoot'])/'backend'))
sys.path.insert(0,str(Path.cwd()/'tests'/'tasks'))
from backend.storage import Store,SelectionRepository
from backend.tasks import TaskPolicy,TaskService
from backend.tasks.adapters import StoreTaskRepository,StoreOutputStore,SelectionAdapter
from support import FakeProviders,FakeSpaces,FakeInputs
now=datetime.fromisoformat(p['now'])
store=Store(p['data'],encryption_key=b'S'*32,release_root=p['release'],clock=lambda:now.timestamp())
ctx=SimpleNamespace(tenantId=p['tenant'],siteSessionId=p['session'])
providers=FakeProviders()
providers.add_account(ctx.tenantId,p['account'],'synthetic-subject')
providers.lookup_result={'status':'completed'}
service=TaskService(repository=StoreTaskRepository(store,selection_reader=SelectionRepository._get),
 providers=providers,selections=SelectionAdapter(SelectionRepository(store)),spaces=FakeSpaces(),
 inputs=FakeInputs(),outputs=StoreOutputStore(store),policy=TaskPolicy(confirmation_key=b'C'*32),clock=lambda:now)
service.reconcile_after_restart(ctx)
t=service.get(ctx,p['task'])
result=service.recover(ctx,t['id'],t['version'])['task']
print(json.dumps({'task':result,'submitCount':providers.submit_count,'lookupCount':len(providers.lookups)}))
'''
        self.f.clock.advance()
        payload = {"moduleRoot": os.environ.get("ASSET_LAB_STORAGE_MODULE_ROOT"), "data": str(self.root / "data"),
                   "release": str(self.root / "release-new-process"), "now": self.f.clock().isoformat(),
                   "tenant": self.f.ctx.tenantId, "session": self.f.ctx.siteSessionId,
                   "account": self.account["id"], "task": prepared["task"]["id"]}
        process = subprocess.run([sys.executable, "-c", script], input=json.dumps(payload), text=True,
                                 capture_output=True, cwd=Path(__file__).resolve().parents[2], check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["submitCount"], 0)
        self.assertEqual(result["lookupCount"], 1)
        self.assertEqual(result["task"]["status"], "completed")
        self.assertEqual(result["task"]["ownership"], prepared["task"]["ownership"])


if __name__ == "__main__":
    unittest.main()
