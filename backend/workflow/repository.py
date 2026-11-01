"""Adapter over module 3's tenant-scoped Store, with no second database.

Each object is a separate central record (so a script is not multiplied into
one giant tenant document). A per-tenant CAS guard serializes all workflow
mutations. Blobs are durably staged before metadata commit; a crashed/rejected
commit can leave an unreferenced private blob, never a dangling approved asset.
"""
import copy
import hashlib
from contextlib import contextmanager

from .errors import WorkflowError, conflict, tenant

KINDS = ('projects', 'scripts', 'assets', 'revisions', 'bundles', 'starts')


class _View:
    def __init__(self, state, storage, ctx, write):
        self.state, self.storage, self.ctx, self.write = state, storage, ctx, write
        self.pending = {}
        self.production = {}
        self.production_reads = {}
        self.coverage_projects = set()

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
            # Capture production and workflow in the same read snapshot. Coverage
            # must not call ProductionService.get (which itself lists assets).
            production, production_reads = {}, {}
            for project in state['projects'].values():
                reads = {}
                def read(collection, identity):
                    row = self._optional(transaction, collection, identity)
                    reads[(collection, identity)] = row['version'] if row else None
                    return row
                snapshot = {'job': None, 'prior': False, 'current': False}
                for offset, script_id in enumerate(reversed(project['scriptIds'])):
                    key = 'idx_' + hashlib.sha256((project['id'] + '\0' + script_id).encode()).hexdigest()
                    index = read('production.current', key)
                    if not index:
                        continue
                    if offset:
                        snapshot['prior'] = True
                        break
                    identity = index['data']['analysisId']
                    snapshot.update(current=True, job=read('production.jobs', identity),
                                    review=read('production.reviews', identity),
                                    edit=read('production.edits', identity))
                    break
                production[project['id']], production_reads[project['id']] = snapshot, reads
        view = _View(state, self.storage, ctx, write)
        view.production, view.production_reads = production, production_reads
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
            for project_id in view.coverage_projects:
                for (collection, identity), version in view.production_reads[project_id].items():
                    current = self._optional(transaction, collection, identity)
                    if (current['version'] if current else None) != version:
                        conflict('制作方案已变化，请重新核对交付范围。')
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
    def _optional(transaction, collection, identity):
        try:
            return transaction.get(collection, identity)
        except Exception as error:
            if getattr(error, 'code', None) != 'NOT_FOUND':
                raise
            return None

    @staticmethod
    def _guard(transaction):
        try:
            return transaction.get('workflow.control', 'workflow_state')
        except Exception as error:
            if getattr(error, 'code', None) != 'NOT_FOUND':
                raise
            return None
