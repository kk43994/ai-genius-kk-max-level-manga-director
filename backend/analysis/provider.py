"""LibTV text-node route verified with a real structured task on 2026-11-01."""
import copy
import hashlib
from types import SimpleNamespace

from backend.providers.libtv_bound_tools import BoundMCPTools
from backend.generation.contracts import ToolCatalog
from backend.generation.live import PersonalProjects, personal_account
from backend.workflow.errors import WorkflowError
from .contract import prompt
from backend.workflow.service import now

from .models import DEFAULT_MODEL
MODEL = DEFAULT_MODEL
SCOPES = {'libtv:account:read', 'libtv:project:read', 'libtv:project:write', 'libtv:task:write'}


class LibTVAnalysisProvider:
    def __init__(self, services):
        self.services = services

    def preflight(self, ctx, owner):
        account = self.services.providers.get_account(ctx, owner['providerAccountId'])
        if not SCOPES <= set(account.get('grantedScopes', [])):
            raise WorkflowError('ANALYSIS_SCOPE_REQUIRED', 'AI 分析需要 LibTV 项目读取、项目写入和任务权限，请在账号面板补充创作授权。', 403)

    def bind(self, ctx, owner):
        self.preflight(ctx, owner)
        return LibTVAnalysisClient(self.services, ctx, owner)


class LibTVAnalysisClient:
    def __init__(self, services, ctx, owner):
        self.services, self.ctx, self._owner = services, ctx, copy.deepcopy(owner)
        self.tools = BoundMCPTools(services.providers, ctx, owner)
        self.catalog = ToolCatalog(self.tools.list_tools(), evidence='Current official LibTV tools/list')

    def _call(self, name, args):
        self.catalog.request(name, args)
        return self.tools.call_tool(name, args, space_id=self._owner['spaceId'])

    def _project(self, job):
        # The resolver rechecks the original personal account and exact project.
        shim = SimpleNamespace(_owner=self._owner, _call=self._call,
                               a=SimpleNamespace(policy=SimpleNamespace(allow_external_writes=True)))
        return PersonalProjects(self.services, lambda owner: self.ctx).resolve(shim, job['projectId']).project_id

    def prepare(self, job, script, save):
        self.catalog.tool('create_node'); self.catalog.tool('task_status')
        model_id = job.get('modelId', MODEL)
        model = self._call('get_model', {'model': model_id})
        contract = model.get('inputContract', {})
        exact = contract.get('model', model.get('modelId'))
        modality = contract.get('modality', model.get('modality'))
        if exact != model_id or modality != 'text':
            raise WorkflowError('ANALYSIS_MODEL_UNAVAILABLE', '官方文本模型配置已变化，尚未提交分析。', 503)
        remote = self._project(job)
        save({'remoteProjectId': remote})

    def submit(self, job, script, save):
        asset_prompt = job.get('context', {}).get('kind') == 'asset_prompt' if job.get('context') else False
        if asset_prompt:
            from .asset_prompts import instruction
            prompt_text = instruction(script, job['context'])
        else:
            prompt_text = prompt(script, job.get('repairDraft') if job['phase'].startswith('repair') else job.get('draft') if job['phase'] == 'review' else None)
        number=job['displayNumber']
        name=(job['context']['entity']['name'][:30]+'提示词') if asset_prompt else {'extract':'剧本分析','review':'剧本复核','repair':'剧本修复','repair2':'剧本再复核'}[job['phase']]
        attempt=len(job.get('rejectedSteps',{}).get(job['phase'],[]))
        args = {'name': f'{name} {number:03d}',
                'nodeType': 'text', 'projectId': job['remoteProjectId'], 'model': job.get('modelId', MODEL),
                'prompt': prompt_text,
                'params': {}, 'run': True, 'idempotencyKey': job['id'] + '-' + job['phase'] + (f'-retry{attempt}' if attempt else '')}
        self.catalog.request('create_node', args)
        step = {'attempted': True, 'startedAt':now(), 'arguments': copy.deepcopy(args),
                'promptSha256': hashlib.sha256(args['prompt'].encode()).hexdigest(), 'taskId': None, 'nodeId': None}
        save({'steps': {**job['steps'], job['phase']: step}, 'status': 'submitting', 'error': None})
        result = self._call('create_node', args)
        task_id = result.get('task_id')
        node_id = result.get('plan', {}).get('nodeId')
        if (result.get('projectId') != job['remoteProjectId'] or result.get('status') not in ('accepted', 'completed')
                or not isinstance(task_id, str) or not task_id or task_id.startswith('cop_')
                or not isinstance(node_id, str) or not node_id):
            raise WorkflowError('ANALYSIS_RECEIPT_REQUIRED', '官方未返回可核对的文本任务回执，已停止自动重发。', 502)
        step.update(taskId=task_id, nodeId=node_id)
        return step

    def read(self, job, step):
        # Do not create a replacement project or task during receipt recovery.
        user = personal_account(self._call('account_user', {}), self._owner)
        info = self._call('project_info', {'project_id': job['remoteProjectId']})
        meta = info.get('data', {}).get('projectMeta', {})
        if info.get('projectId') != job['remoteProjectId'] or meta.get('uuid') != job['remoteProjectId'] or meta.get('ownerId') != user.get('id'):
            raise WorkflowError('OWNERSHIP_MISMATCH', '原分析项目归属已变化，已停止读取。', 409)
        result = self._call('task_status', {'project_id': job['remoteProjectId'], 'task_id': step['taskId']})
        if result.get('task_id') != step['taskId']:
            raise WorkflowError('ANALYSIS_RECEIPT_MISMATCH', '官方返回的任务编号不一致。', 502)
        outcome = result.get('outcome')
        if outcome in ('FAILED', 'CANCELLED', 'CANCELED'):
            raise WorkflowError('ANALYSIS_PROVIDER_FAILED', '官方文本分析任务失败或已取消，原文已保留。', 422)
        if outcome != 'SUCCEEDED' or result.get('readiness') != 'TERMINAL_READY':
            return 'pending', None
        texts = result.get('result', {}).get('texts')
        if result.get('result_kind') != 'structured' or not isinstance(texts, list) or len(texts) != 1 or not isinstance(texts[0], str):
            raise WorkflowError('ANALYSIS_RESULT_INVALID', '官方任务已结束，但没有返回完整的结构化文本。', 422)
        return 'completed', texts[0]
