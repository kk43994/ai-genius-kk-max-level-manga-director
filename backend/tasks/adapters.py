"""Adapters for session 3's Store and session 4's SpaceService.

No database/path implementation lives here; all records, CAS and blobs pass
through the shared Store. Pass a transaction-local selection reader explicitly.
"""

from contextlib import contextmanager
from copy import deepcopy

from .errors import TaskError
from .model import digest, owner_match, tenant


def _storage_error(exc):
    code = getattr(exc, "code", None)
    errors = {
        "NOT_FOUND": ("NOT_FOUND", "任务或文件不存在。", 404),
        "SESSION_REQUIRED": ("SESSION_REQUIRED", "请恢复本站会话后继续。", 401),
        "VERSION_CONFLICT": ("VERSION_CONFLICT", "任务已更新，请刷新状态。", 409),
        "OWNERSHIP_MISMATCH": ("OWNERSHIP_MISMATCH", "任务归属不能更改。", 409),
        "IDEMPOTENCY_CONFLICT": ("IDEMPOTENCY_CONFLICT", "相同请求编号的内容不同。", 409),
    }
    return TaskError(*errors.get(code, ("STORAGE_UNAVAILABLE", "任务存储暂不可用，已停止后续操作。", 503)))


class StoreTaskRepository:
    def __init__(self, store, *, selection_reader):
        """selection_reader(shared_tx) -> {providerAccountId, spaceId, revision}.

        It must read within the passed transaction, never open a nested Store
        transaction. Session 3 currently exposes SelectionRepository._get(tx);
        the composition layer can pass it, or a public equivalent when added.
        """
        if not callable(selection_reader):
            raise ValueError("A transaction-local selection reader is required")
        self.store, self.selection_reader = store, selection_reader

    @contextmanager
    def transaction(self, ctx):
        tenant(ctx)
        try:
            with self.store.transaction(ctx) as tx:
                yield StoreTaskTransaction(tx, self.selection_reader)
        except TaskError:
            raise
        except Exception as exc:
            raise _storage_error(exc) from None


class StoreTaskTransaction:
    def __init__(self, transaction, selection_reader):
        self.tx, self.selection_reader = transaction, selection_reader

    def assert_selection(self, expected_revision, ownership=None):
        selected = self.selection_reader(self.tx)
        if (selected.get("revision") != expected_revision
                or ownership and any(selected.get(k) != ownership.get(k) for k in ("providerAccountId", "spaceId"))):
            raise TaskError("SELECTION_CHANGED", "当前账号或空间已变化，请重新核对。", 409)

    def _optional(self, collection, identifier):
        try:
            return self.tx.get(collection, identifier)
        except Exception as exc:
            if getattr(exc, "code", None) == "NOT_FOUND":
                return None
            raise

    @staticmethod
    def _task(row):
        data = deepcopy(row["data"])
        if data.get("id") != row["id"] or data.get("version") != row["version"]:
            raise TaskError("INVALID_RECORD", "任务版本记录不一致，已停止处理。", 409)
        return data

    def get_task(self, task_id):
        row = self._optional("tasks", task_id)
        return self._task(row) if row else None

    def put_task(self, task, expected_version):
        if expected_version is None:
            if task["version"] != 1:
                raise TaskError("INVALID_RECORD", "新任务版本无效。", 409)
            self.tx.create("tasks", deepcopy(task), record_id=task["id"],
                           immutable_fields=("ownership", "projectId", "entityId", "recipe", "spec",
                                             "inputs", "inputHash", "sourceRevisionIds", "createdAt"))
        else:
            if task["version"] != expected_version + 1:
                raise TaskError("INVALID_RECORD", "任务更新版本无效。", 409)
            self.tx.update("tasks", task["id"], deepcopy(task), expected_version=expected_version)

    def list_tasks(self):
        cursor, rows = None, []
        while True:
            page = self.tx.list("tasks", limit=1000, after=cursor)
            rows.extend(self._task(row) for row in page["items"])
            cursor = page["nextCursor"]
            if cursor is None:
                return rows

    def get_request(self, scope, key_digest):
        row = self._optional("task_requests", "req_" + digest([scope, key_digest]))
        return deepcopy(row["data"]) if row else None

    def put_request(self, scope, key_digest, record):
        self.tx.create("task_requests", deepcopy(record), record_id="req_" + digest([scope, key_digest]),
                       immutable_fields=("requestHash", "taskId"))


class SpaceAdapter:
    """Translate the space module's authoritative read without caching identity."""
    def __init__(self, spaces):
        self.spaces = spaces

    def get_space(self, ctx, account_id, space_id):
        return self.spaces.assert_space_access(ctx, account_id, space_id)


class SelectionAdapter:
    def __init__(self, selection_repository):
        self.selections = selection_repository

    def get_selection(self, ctx):
        return self.selections.get(ctx)


class StoreOutputStore:
    """Persist idempotent output links via Store blobs and tenant-scoped records.

    A crash between blob_put and creating its link can leave an unreferenced
    private blob. It cannot create a completed task or a second visible revision;
    the common storage maintenance job may later collect unreferenced blobs.
    """
    def __init__(self, store):
        self.store = store

    def _existing(self, tx, identifier):
        try:
            return tx.get("task_outputs", identifier)["data"]
        except Exception as exc:
            if getattr(exc, "code", None) == "NOT_FOUND":
                return None
            raise

    def put(self, ctx, *, task_id, ownership, index, content, mime, sha256):
        identifier = "out_" + digest([task_id, index, sha256])
        try:
            with self.store.transaction(ctx) as tx:
                task = tx.get("tasks", task_id)["data"]
                if not owner_match(task["ownership"], ownership):
                    raise TaskError("OWNERSHIP_MISMATCH", "文件归属与原任务不符。", 409)
                existing = self._existing(tx, identifier)
                if existing:
                    return {"blobId": existing["blobId"]}
            blob = self.store.blob_put(ctx, content, mime=mime)
            if blob.get("sha256") != sha256:
                raise TaskError("OUTPUT_STORE_UNVERIFIED", "文件存储摘要不一致。", 409)
            record = {"taskId": task_id, "ownership": deepcopy(ownership), "index": index,
                      "blobId": blob["id"], "sha256": sha256, "mime": mime, "review": "pending"}
            with self.store.transaction(ctx) as tx:
                existing = self._existing(tx, identifier)
                if existing:
                    return {"blobId": existing["blobId"]}
                self.store_record(tx, identifier, record)
            return {"blobId": blob["id"]}
        except TaskError:
            raise
        except Exception as exc:
            raise _storage_error(exc) from None

    @staticmethod
    def store_record(tx, identifier, record):
        tx.create("task_outputs", record, record_id=identifier,
                  immutable_fields=("ownership", "taskId", "index", "blobId", "sha256", "mime"))

    def read(self, ctx, blob_id):
        try:
            content, _ = self.store.blob_get(ctx, blob_id)
            return content
        except Exception as exc:
            raise _storage_error(exc) from None
