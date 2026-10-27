"""Adapter over module 3's tenant-scoped Store, with no second database.

Each object is a separate central record (so a script is not multiplied into
one giant tenant document). A per-tenant CAS guard serializes all workflow
mutations. Blobs are durably staged before metadata commit; a crashed/rejected
commit can leave an unreferenced private blob, never a dangling approved asset.
"""
import copy
from contextlib import contextmanager

from .errors import WorkflowError, conflict, tenant

KINDS = ('projects', 'scripts', 'assets', 'revisions', 'bundles', 'starts')


class _View:
    def __init__(self, state, storage, ctx, write):
        self.state, self.storage, self.ctx, self.write = state, storage, ctx, write
        self.pending = {}

    def put_blob(self, content):
        if not self.write:
            raise WorkflowError('READ_ONLY', '只读操作不能保存文件。', 500)
        identity = 'wf_pending_' + str(len(self.pending))
        self.pending[identity] = content
        return identity

    def get_blob(self, identity):
        if identity in self.pending:
            return self.pending[identity]
        result = self.storage.blob_get(self.ctx, identity)
        if isinstance(result, bytes):
            return result
        if isinstance(result, dict) and isinstance(result.get('content'), bytes):
            return result['content']
        if isinstance(result, tuple) and isinstance(result[0], bytes):
            return result[0]
        raise WorkflowError('STORAGE_UNAVAILABLE', '素材存储返回格式尚未适配。', 503)


class WorkflowRepository:
    def __init__(self, storage):
        self.storage = storage

    @contextmanager
    def transaction(self, ctx, write=False):
        tenant(ctx)
        state, records = {}, {}
        with self.storage.transaction(ctx, readonly=True) as transaction:
            guard = self._guard(transaction)
            for kind in KINDS:
                state[kind], records[kind] = {}, {}
                cursor = None
                while True:
                    page = transaction.list('workflow.' + kind, limit=1000, after=cursor)
                    for row in page['items']:
                        state[kind][row['id']] = copy.deepcopy(row['data'])
                        records[kind][row['id']] = row
                    cursor = page.get('nextCursor')
                    if not cursor:
                        break
        view = _View(state, self.storage, ctx, write)
        yield view
        if not write:
            return
        # blob_put opens its own short transaction; never nest it under a writer.
        replacement = {}
        for pending_id, raw in view.pending.items():
            stored = self.storage.blob_put(ctx, raw)
            replacement[pending_id] = stored['id'] if isinstance(stored, dict) else stored
        for kind in KINDS:
            for data in state[kind].values():
                if data.get('blobId') in replacement:
                    data['blobId'] = replacement[data['blobId']]
        with self.storage.transaction(ctx) as transaction:
            current_guard = self._guard(transaction)
            if (current_guard or {}).get('version') != (guard or {}).get('version'):
                conflict('资产记录已被另一个操作更新，请重新读取后再试。')
            if current_guard:
                transaction.update('workflow.control', 'workflow_state', {'schemaVersion': 1},
                                   expected_version=current_guard['version'])
            else:
                transaction.create('workflow.control', {'schemaVersion': 1}, record_id='workflow_state')
            for kind in KINDS:
                for identity, data in state[kind].items():
                    prior = records[kind].get(identity)
                    if prior and prior['data'] != data:
                        transaction.update('workflow.' + kind, identity, data, expected_version=prior['version'])
                    elif not prior:
                        transaction.create('workflow.' + kind, data, record_id=identity)
                if set(records[kind]) - set(state[kind]):
                    raise WorkflowError('HISTORY_PROTECTED', '工作流历史不能物理删除。', 409)

    @staticmethod
    def _guard(transaction):
        try:
            return transaction.get('workflow.control', 'workflow_state')
        except Exception as error:
            if getattr(error, 'code', None) != 'NOT_FOUND':
                raise
            return None
