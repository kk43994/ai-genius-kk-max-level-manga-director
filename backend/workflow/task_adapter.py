"""TaskService OutputStore port; model transport remains wholly in providers."""
import copy
import hashlib

from .errors import WorkflowError, conflict, tenant
from .service import inspect_image


class WorkflowOutputStore:
    def __init__(self, workflow, task_repository):
        self.workflow, self.task_repository = workflow, task_repository

    def put(self, ctx, *, task_id, ownership, index, content, mime, sha256):
        if hashlib.sha256(content).hexdigest() != sha256:
            conflict('任务输出摘要不一致。')
        if inspect_image(content)['mime'] != mime:
            conflict('官方声明的图片类型与实际文件不一致。')
        # Read its durable task; never reconstruct from the current UI selection.
        with self.task_repository.transaction(ctx) as transaction:
            task = transaction.get_task(task_id)
        if not task or task.get('ownership', {}).get('tenantId') != tenant(ctx):
            raise WorkflowError('NOT_FOUND', '任务不存在。', 404)
        if task['ownership'] != ownership:
            conflict('任务输出归属与原任务不一致。')
        snapshot = task.get('inputs', {}).get('workflowSnapshot') or task.get('workflowSnapshot')
        if not snapshot:
            raise WorkflowError('WORKFLOW_SNAPSHOT_MISSING', '任务缺少准备时的资产版本快照，尚未入库。', 409)
        material = {**copy.deepcopy(task.get('spec', {})), **copy.deepcopy(task), 'workflowSnapshot': snapshot, 'modelLabel': task.get('spec', {}).get('modelId') or (task.get('prepared') or {}).get('modelKey')}
        revision = self.workflow.record_output(ctx, material, content, str(index))
        # revision IDs are opaque read handles, never local paths or upstream URLs.
        return {'blobId': revision['id'], 'assetId': revision['assetId'], 'revisionId': revision['id'],
                'sha256': revision['sha256'], 'mime': revision['mime']}

    def read(self, ctx, blob_id):
        revision = self.workflow.get_revision(ctx, blob_id, require_approved=False)
        return self.workflow.content(ctx, revision['assetId'], revision['id'])[0]
