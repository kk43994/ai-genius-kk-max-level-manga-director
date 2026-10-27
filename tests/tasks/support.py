"""Synthetic SQLite port fixture. Never imports a real LibTV client or CLI."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
import tempfile

from backend.tasks import DownloadArtifact, TaskError, TaskPolicy, TaskService
from backend.tasks.model import digest, tenant


def temporary_directory():
    root = Path(__file__).resolve().parents[2] / "work" / "task-tests"
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


class SQLiteRepository:
    def __init__(self, path):
        self.path = str(path)
        self.fail_attempt_commit = False
        self.selection_reader = None
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (tenant TEXT, id TEXT, version INTEGER, body TEXT,
                    PRIMARY KEY(tenant, id));
                CREATE TABLE IF NOT EXISTS requests (tenant TEXT, scope TEXT, key TEXT, body TEXT,
                    PRIMARY KEY(tenant, scope, key));
            """)
            db.commit()

    @contextmanager
    def transaction(self, ctx):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("BEGIN IMMEDIATE")
            tx = SQLiteTransaction(db, tenant(ctx), self)
            yield tx
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()


class SQLiteTransaction:
    def __init__(self, db, tenant_id, repository):
        self.db, self.tenant_id, self.repository = db, tenant_id, repository

    def assert_selection(self, expected_revision, ownership=None):
        current = self.repository.selection_reader(SimpleNamespace(tenantId=self.tenant_id))
        if current["revision"] != expected_revision or (ownership and any(current[k] != ownership[k] for k in ("providerAccountId", "spaceId"))):
            raise TaskError("SELECTION_CHANGED", "选择已变化", 409)

    def get_task(self, task_id):
        row = self.db.execute("SELECT body FROM tasks WHERE tenant=? AND id=?", (self.tenant_id, task_id)).fetchone()
        return json.loads(row[0]) if row else None

    def put_task(self, task, expected_version):
        if task["ownership"]["tenantId"] != self.tenant_id:
            raise AssertionError("cross-tenant write")
        if self.repository.fail_attempt_commit and task["submissionAttempted"]:
            raise OSError("simulated disk full")
        old = self.get_task(task["id"])
        if old and old["ownership"] != task["ownership"]:
            raise AssertionError("owner mutation")
        if expected_version is None:
            self.db.execute("INSERT INTO tasks VALUES (?, ?, ?, ?)",
                            (self.tenant_id, task["id"], task["version"], json.dumps(task)))
        else:
            changed = self.db.execute("UPDATE tasks SET version=?, body=? WHERE tenant=? AND id=? AND version=?",
                                     (task["version"], json.dumps(task), self.tenant_id, task["id"], expected_version)).rowcount
            if changed != 1:
                raise TaskError("VERSION_CONFLICT", "stale version", 409)

    def list_tasks(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM tasks WHERE tenant=? ORDER BY id", (self.tenant_id,))]

    def get_request(self, scope, key_digest):
        row = self.db.execute("SELECT body FROM requests WHERE tenant=? AND scope=? AND key=?",
                              (self.tenant_id, scope, key_digest)).fetchone()
        return json.loads(row[0]) if row else None

    def put_request(self, scope, key_digest, record):
        self.db.execute("INSERT INTO requests VALUES (?, ?, ?, ?)",
                        (self.tenant_id, scope, key_digest, json.dumps(record)))


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds=200):
        self.value += timedelta(seconds=seconds)


class TestProviderError(Exception):
    def __init__(self, code, message="provider token=do-not-echo https://signed.invalid/private?signature=secret", provider_receipt=None):
        super().__init__(message)
        self.code, self.provider_receipt = code, provider_receipt


class ProcessCrash(BaseException):
    pass


class FakeClient:
    def __init__(self, provider, ctx, owner):
        self.provider, self.ctx, self.owner = provider, ctx, deepcopy(owner)

    def identity(self):
        account_id = self.owner["providerAccountId"]
        self.provider.calls.append(("identity", deepcopy(self.owner)))
        account = self.provider.accounts[(self.ctx.tenantId, account_id)]
        if account["authorization"]["state"] != "connected" or account.get("removedAt"):
            raise TestProviderError("AUTHORIZATION_EXPIRED")
        if self.provider.identity_hook:
            self.provider.identity_hook(self)
        return {"provider": "libtv", "providerAccountId": account_id,
                "issuer": account["identity"]["issuer"], "subject": account["identity"]["subject"],
                "spaceId": self.provider.wrong_space or self.owner["spaceId"],
                "spaceKind": self.owner["spaceKind"], "verified": True}

    def prepare(self, spec):
        self.provider.calls.append(("prepare", deepcopy(self.owner)))
        self.provider.preparation_payloads.append(deepcopy(spec))
        if self.provider.prepare_error:
            raise self.provider.prepare_error
        return {"modelKey": "official-test-image", "schemaHash": digest({"schema": "fixture"}),
                "requestHash": spec["requestHash"], "count": 1, "cost": deepcopy(self.provider.quote),
                "providerReceipt": deepcopy(self.provider.prepared_receipt)}

    def submit(self, prepared, idempotencyKey):
        self.provider.calls.append(("submit", deepcopy(self.owner)))
        self.provider.submission_payloads.append(deepcopy(prepared))
        self.provider.submit_count += 1
        self.provider.submission_keys.append(idempotencyKey)
        if self.provider.submit_hook:
            self.provider.submit_hook(self)
        if self.provider.submit_error:
            raise self.provider.submit_error
        return deepcopy(self.provider.submit_result)

    def lookup(self, ref):
        self.provider.calls.append(("lookup", deepcopy(self.owner)))
        self.provider.lookups.append(deepcopy(ref))
        if self.provider.lookup_hook:
            self.provider.lookup_hook(self)
        if self.provider.lookup_error:
            raise self.provider.lookup_error
        return deepcopy(self.provider.lookup_result)

    def download(self, ref):
        self.provider.calls.append(("download", deepcopy(self.owner)))
        if self.provider.download_error:
            raise self.provider.download_error
        return self.provider.artifacts


class FakeProviders:
    def __init__(self):
        self.accounts, self.calls, self.lookups, self.submission_keys = {}, [], [], []
        self.preparation_payloads, self.submission_payloads = [], []
        self.submit_count = 0
        self.wrong_space = self.prepare_error = self.submit_error = self.lookup_error = self.download_error = None
        self.identity_hook = self.submit_hook = self.lookup_hook = None
        self.prepared_receipt = {"projectId": "official-canvas-original", "nodeId": "official-node-original"}
        self.submit_result = {"status": "queued", "providerReceipt": {"taskId": "official-task-original"}}
        self.lookup_result = {"status": "running"}
        self.quote = {"state": "unknown", "amount": None, "unit": None}
        self.artifacts = [DownloadArtifact(b"synthetic image bytes", "image/png")]

    def add_account(self, tenant_id, account_id, subject=None):
        self.accounts[(tenant_id, account_id)] = {
            "id": account_id, "provider": "libtv", "label": "合成账号 " + account_id,
            "identity": {"verified": True, "issuer": "https://official-test.invalid", "subject": subject or "subject-" + account_id},
            "authorization": {"state": "connected"}, "removedAt": None,
        }

    def get_account(self, ctx, account_id):
        account = self.accounts.get((ctx.tenantId, account_id))
        if account is None:
            raise TaskError("NOT_FOUND", "账号不存在", 404)
        return deepcopy(account)

    def client_for(self, ctx, owner):
        self.calls.append(("client_for", deepcopy(owner)))
        self.get_account(ctx, owner["providerAccountId"])
        return FakeClient(self, ctx, owner)


class FakeSelections:
    def __init__(self):
        self.values = {}

    def get_selection(self, ctx):
        return deepcopy(self.values[ctx.tenantId])

    def set(self, ctx, account="pa_A", space="space_personal", revision=1):
        self.values[ctx.tenantId] = {"providerAccountId": account, "spaceId": space, "revision": revision}


class FakeSpaces:
    def get_space(self, ctx, account_id, space_id):
        return {"id": space_id, "kind": "team" if space_id == "space_team" else "personal",
                "name": "合成空间 " + space_id, "access": "available"}


class FakeInputs:
    def __init__(self):
        self.sources = {}
        self.project_owner = None
        self.hook = None
        self.workflow_snapshot = {"entityVersion": 1, "styleVersion": 1}

    def validate_task_inputs(self, ctx, spec, owner):
        if self.hook:
            self.hook(ctx, spec, owner)
        sources = [deepcopy(self.sources[source]) for source in spec["sourceRevisionIds"]]
        return {"projectTenantId": self.project_owner or ctx.tenantId, "spec": deepcopy(spec), "sources": sources,
                "workflowSnapshot": {**self.workflow_snapshot, "sourceHashes": {s["revisionId"]: s["sha256"] for s in sources}}}


class FakeOutputs:
    def __init__(self):
        self.blobs = {}
        self.corrupt = False
        self.hook = None

    def put(self, ctx, *, task_id, ownership, index, content, mime, sha256):
        if self.hook:
            self.hook()
        blob_id = "blob_" + hashlib.sha256(f"{task_id}:{index}:{sha256}".encode()).hexdigest()
        self.blobs[(ctx.tenantId, blob_id)] = content
        return {"blobId": blob_id}

    def read(self, ctx, blob_id):
        return b"corrupted" if self.corrupt else self.blobs[(ctx.tenantId, blob_id)]


def spec(**changes):
    return {"projectId": "project_one", "entityId": "entity_one", "recipe": "mj_style",
            "prompt": "Synthetic character asset", "sourceRevisionIds": [], "settings": {}, **changes}


class Fixture:
    def __init__(self, path):
        self.ctx = SimpleNamespace(tenantId="tenant_A", siteSessionId="session_A", csrfVerified=True)
        self.other = SimpleNamespace(tenantId="tenant_B", siteSessionId="session_B", csrfVerified=True)
        self.clock, self.providers, self.selections = Clock(), FakeProviders(), FakeSelections()
        self.spaces, self.inputs, self.outputs = FakeSpaces(), FakeInputs(), FakeOutputs()
        self.repository = SQLiteRepository(path)
        for ctx in (self.ctx, self.other):
            self.providers.add_account(ctx.tenantId, "pa_A")
            self.providers.add_account(ctx.tenantId, "pa_B")
            self.selections.set(ctx)
        self.service = self.new_service()

    def new_service(self, *, enabled=True, repository=None):
        repository = repository or self.repository
        repository.selection_reader = self.selections.get_selection
        return TaskService(repository=repository, providers=self.providers,
                           selections=self.selections, spaces=self.spaces, inputs=self.inputs, outputs=self.outputs,
                           policy=TaskPolicy(confirmation_key=b"synthetic-confirmation-key-only-32bytes", allow_paid_submission=enabled),
                           clock=self.clock)

    def prepare(self, key="prepare-key-001", **changes):
        return self.service.prepare(self.ctx, spec(**changes), self.selections.get_selection(self.ctx)["revision"], key)

    def submit(self, prepared, key="submit-key-001"):
        return self.service.submit(self.ctx, prepared["task"]["id"], prepared["task"]["version"], prepared["confirmation"]["token"], key)
