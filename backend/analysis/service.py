"""Durable, ownership-pinned AI jobs. GET never calls a model or resumes work."""
import copy
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict

from backend.workflow.errors import WorkflowError, public_input
from backend.tasks.errors import TaskError
from backend.auth.errors import AuthError
from backend.spaces.errors import SpaceError
from backend.workflow.service import now
from .models import MODELS, DEFAULT_MODEL, selected_model
from .contract import MAX_SOURCE_CHARACTERS, PROMPT_VERSION, asset_candidates, parse_result

ACTIVE = {'preparing', 'submitting', 'running', 'reviewing', 'interrupted', 'unknown_submission'}
MESSAGES = {
    'preparing': '正在核对原账号、空间与文本模型',
    'submitting': '正在提交 AI 全文分析',
    'running': 'AI 正在通读剧本并提取六类信息',
    'reviewing': 'AI 正在对照原文复核台词、人物和时空关系',
    'ready': 'AI 分析与原文格式核验完成，等待你核对',
    'failed': '本次分析未完成，原文和任务记录已保留',
    'interrupted': '查询暂时中断，可继续查询原任务',
    'unknown_submission': '提交回执尚未确认，已停止新建请求以免重复计费',
}


class AnalysisService:
    collection = 'analysis.jobs'
    index_collection = 'analysis.current'
    id_prefix = 'ana_'
    prompt_version = PROMPT_VERSION

    def __init__(self, services, provider, *, enabled=False, background=True, clock=time.time, analysis_policy='single'):
        self.services, self.store, self.provider = services, services.storage, provider
        self.enabled, self.background, self.clock = enabled, background, clock
        self._threads = set()
        self._lock = threading.Lock()
        self.analysis_policy = analysis_policy
        self._clients = OrderedDict()

    def capabilities(self):
        return {'configured': self.enabled, 'method': 'ai', 'model': 'GVLM 3.1',
                'maxCharacters': MAX_SOURCE_CHARACTERS, 'localRuleFallback': False,
                'models': copy.deepcopy(list(MODELS)), 'defaultModelId': DEFAULT_MODEL,
                'defaultCalls': 1,
                'message': '导入后使用 LibTV 文本模型分析，需当前账号创作权限。' if self.enabled
                else 'AI 分析服务尚未启用。原文会保留，不会使用本地规则替代。'}

    def _get(self, ctx, identity):
        return self.store.get(ctx, self.collection, identity)

    def _public(self, row):
        data = row['data']
        result = {k: copy.deepcopy(data.get(k)) for k in (
            'id', 'projectId', 'scriptId', 'sourceRevision', 'status', 'phase', 'model',
            'createdAt', 'updatedAt', 'error', 'result', 'completedCalls', 'promptVersion', 'modelId', 'displayNumber')}
        result['version'] = row['version']
        result['message'] = data.get('error', {}).get('message') if data.get('error') else MESSAGES[data['status']]
        if not data.get('error') and data['status']=='reviewing' and data['phase'].startswith('repair'):
            result['message'] = 'AI 正在修复原文引用' if data['phase']=='repair' else 'AI 正在修复台词分段与逐字引用'
        result['ownership'] = {k: data['ownership'].get(k) for k in ('providerAccountId', 'spaceId', 'accountLabelAtCreation', 'spaceNameAtCreation')}
        result['canRefresh'] = data['status'] in ACTIVE
        result['canResumeReview'] = bool(data['status']=='failed' and data['phase']=='extract' and data.get('error',{}).get('code')=='ANALYSIS_RESULT_INVALID' and data['steps'].get('extract',{}).get('taskId') and not data['steps'].get('review'))
        result['canRetry'] = data['status'] == 'failed'
        result['canRetrySubmission'] = bool(data['status']=='failed' and data['steps'].get(data['phase'],{}).get('rejectedBeforeSubmission'))
        result['canRepairResult'] = bool(data['status']=='failed' and data['phase'] in ('review','repair') and data.get('error',{}).get('code')=='ANALYSIS_RESULT_INVALID' and data['steps'].get(data['phase'],{}).get('taskId') and data.get('repairFromPhase')!=data['phase'])
        base_calls=1 if data.get('analysisPolicy')=='single' and not data.get('reviewRequested') else 2
        result['totalCalls'] = 4 if data.get('repairFromPhase')=='repair' else 3 if data.get('repairRequested') else base_calls
        result['phaseStartedAt'] = data['steps'].get(data['phase'],{}).get('startedAt')
        result['cost'] = {'state': 'unknown', 'message': '使用当前账号的 LibTV 积分，以官方扣费记录为准。'}
        return result

    def get(self, ctx, identity):
        return self._public(self._get(ctx, identity))

    def latest(self, ctx, project_id, script_id):
        self.services.workflow.get_script(ctx, project_id, script_id)
        key = 'idx_' + hashlib.sha256((project_id + '\0' + script_id).encode()).hexdigest()
        try:
            index = self.store.get(ctx, self.index_collection, key)
        except Exception as error:
            if getattr(error, 'code', None) == 'NOT_FOUND':
                return {'analysis': None}
            raise
        return {'analysis': self.get(ctx, index['data']['analysisId'])}

    def start(self, ctx, project_id, script_id, body, *, context=None):
        public_input(body, {'idempotencyKey', 'expectedSelectionRevision', 'confirmSpend', 'reanalyze', 'modelId'})
        if not self.enabled:
            raise WorkflowError('ANALYSIS_UNAVAILABLE', self.capabilities()['message'], 503)
        if body.get('confirmSpend') is not True:
            raise WorkflowError('ANALYSIS_SPEND_CONFIRMATION_REQUIRED', '开始前请确认使用当前账号的 LibTV 积分。', 409)
        key = body.get('idempotencyKey')
        if not isinstance(key, str) or not 8 <= len(key) <= 200 or not key.isascii() or not all(c.isalnum() or c in '-_.:' for c in key):
            raise WorkflowError('IDEMPOTENCY_KEY_REQUIRED', '分析请求编号无效。')
        model = selected_model(body.get('modelId', DEFAULT_MODEL))
        script = self.services.workflow.get_script(ctx, project_id, script_id)
        if len(script['text']) > MAX_SOURCE_CHARACTERS:
            raise WorkflowError('ANALYSIS_SOURCE_TOO_LARGE', f'当前 AI 分析每次支持 {MAX_SOURCE_CHARACTERS} 字，请按剧集分别导入；原文已完整保存，没有截断。')
        try:
            selected = self.services.tasks._selection(ctx)
        except (TaskError, AuthError, SpaceError) as error:
            raise WorkflowError(error.code, error.message, error.status) from None
        if selected['revision'] != body.get('expectedSelectionRevision'):
            raise WorkflowError('SELECTION_CHANGED', '账号或空间已变化，请核对后重新开始。', 409)
        try:
            owner = self.services.tasks._owner(ctx, selected)
            self.provider.preflight(ctx, owner)
        except (TaskError, AuthError, SpaceError) as error:
            raise WorkflowError(error.code, error.message, error.status) from None
        if owner['spaceKind'] != 'personal':
            raise WorkflowError('ANALYSIS_SPACE_UNSUPPORTED', '当前文本分析已验证个人空间，请切换到自己的个人空间。', 409)
        identity = self.id_prefix + hashlib.sha256(key.encode()).hexdigest()
        scope_id = context['entityId'] if context else script_id
        index_id = 'idx_' + hashlib.sha256((project_id + '\0' + scope_id).encode()).hexdigest()
        digest = hashlib.sha256((project_id + script_id + script['sourceRevision'] + str(selected['revision']) + model['id'] + self.analysis_policy + (json.dumps(context,sort_keys=True) if context else '')).encode()).hexdigest()
        with self.store.transaction(ctx) as tx:
            try:
                row = tx.get(self.collection, identity)
            except Exception as error:
                if getattr(error, 'code', None) != 'NOT_FOUND': raise
                row = None
            if row:
                if row['data']['requestHash'] != digest:
                    raise WorkflowError('IDEMPOTENCY_CONFLICT', '这个请求编号已用于另一份分析。', 409)
            else:
                try: index = tx.get(self.index_collection, index_id)
                except Exception as error:
                    if getattr(error, 'code', None) != 'NOT_FOUND': raise
                    index = None
                if index:
                    old = tx.get(self.collection, index['data']['analysisId'])
                    if old['data']['status'] in ACTIVE or body.get('reanalyze') is not True:
                        row = old
                if row is None:
                    # Selection check participates in the same local transaction as intent.
                    fresh = self.services.selections._get(tx)
                    if fresh['revision'] != selected['revision']:
                        raise WorkflowError('SELECTION_CHANGED', '账号或空间已变化，尚未提交分析。', 409)
                    data = {'id': identity, 'requestHash': digest, 'projectId': project_id, 'scriptId': script_id,
                        'sourceRevision': script['sourceRevision'], 'ownership': owner, 'model': model['name'], 'modelId': model['id'],
                        'promptVersion': self.prompt_version, 'status': 'preparing', 'phase': 'extract',
                        'createdAt': now(), 'updatedAt': now(), 'completedCalls': 0, 'result': None,
                        'error': None, 'steps': {}, 'lease': None, 'context': copy.deepcopy(context), 'analysisPolicy':self.analysis_policy}
                    row = tx.create(self.collection, data, record_id=identity,
                        immutable_fields=('ownership', 'requestHash', 'sourceRevision', 'projectId', 'scriptId', 'promptVersion', 'modelId', 'model', 'context', 'analysisPolicy'))
                    index_data = {'analysisId': identity, 'projectId': project_id, 'scriptId': script_id, 'entityId': (context or {}).get('entityId')}
                    if index: tx.update(self.index_collection, index_id, index_data, expected_version=index['version'])
                    else: tx.create(self.index_collection, index_data, record_id=index_id)
        self._schedule(ctx, row['id'])
        return self.get(ctx, row['id'])

    def refresh(self, ctx, identity):
        row = self._get(ctx, identity)
        if row['data']['status'] in ACTIVE:
            self._schedule(ctx, identity)
        return self.get(ctx, identity)

    def _schedule(self, ctx, identity):
        if not self.enabled:
            return
        if not self.background:
            return
        with self._lock:
            pair = (ctx.tenantId, identity)
            if pair in self._threads: return
            self._threads.add(pair)
        def work():
            try: self.advance(copy.copy(ctx), identity)
            finally:
                with self._lock: self._threads.discard(pair)
        threading.Thread(target=work, name='screenplay-analysis', daemon=True).start()

    @staticmethod
    def _allocate_number(tx, project_id):
        key='num_'+hashlib.sha256(project_id.encode()).hexdigest()
        try:row=tx.get('analysis.numbering',key)
        except Exception as error:
            if getattr(error,'code',None)!='NOT_FOUND':raise
            row=None
        number=row['data']['lastNumber']+1 if row else 1
        data={'projectId':project_id,'lastNumber':number}
        if row:tx.update('analysis.numbering',key,data,expected_version=row['version'])
        else:tx.create('analysis.numbering',data,record_id=key)
        return number

    def _client(self, ctx, data):
        key=(ctx.tenantId,ctx.siteSessionId,data['id'])
        with self._lock:
            cached=self._clients.get(key)
            if cached is not None:
                self._clients.move_to_end(key)
                return cached
        client=self.provider.bind(ctx,data['ownership'])
        with self._lock:
            self._clients[key]=client
            while len(self._clients)>16:self._clients.popitem(last=False)
        # BoundMCPTools still checks token, local revocation and live account /
        # space on every operation. Only connection setup/catalog are reused.
        return client

    def advance(self, ctx, identity):
        """One original provider step per explicit start/refresh. Never a blind retry."""
        token = uuid.uuid4().hex
        with self.store.transaction(ctx) as tx:
            row = tx.get(self.collection, identity); data = row['data']
            if data['status'] not in ACTIVE or (data.get('lease') and data['lease']['until'] > self.clock()):
                return
            if not data.get('displayNumber'):
                data['displayNumber']=self._allocate_number(tx,data['projectId'])
            data['lease'] = {'token': token, 'until': self.clock() + 180}
            tx.update(self.collection, identity, data, expected_version=row['version'])
        def save(updates):
            with self.store.transaction(ctx) as tx:
                row = tx.get(self.collection, identity); data = row['data']
                if not data.get('lease') or data['lease']['token'] != token:
                    raise WorkflowError('ANALYSIS_LEASE_LOST', '分析已由另一个操作接管。', 409)
                data.update(copy.deepcopy(updates), updatedAt=now())
                data['lease']['until'] = self.clock() + 180
                tx.update(self.collection, identity, data, expected_version=row['version'])
        try:
            data = self._get(ctx, identity)['data']
            script = self.services.workflow.get_script(ctx, data['projectId'], data['scriptId'])
            if script['sourceRevision'] != data['sourceRevision']:
                raise WorkflowError('ANALYSIS_SOURCE_CHANGED', '原文版本已变化，未使用旧分析覆盖新剧本。', 409)
            step = copy.deepcopy(data['steps'].get(data['phase'], {}))
            if step.get('attempted') and not step.get('taskId'):
                save({'status': 'unknown_submission', 'error': {'code': 'ANALYSIS_RECEIPT_REQUIRED',
                    'message': '原分析提交回执尚未确认，请保留记录并联系支持核对；系统不会重复提交。'}})
                return
            client = self._client(ctx, data)
            if not step.get('taskId'):
                client.prepare(data, script, save)
                data = self._get(ctx, identity)['data']
                step = client.submit(data, script, save)
                # Receipt is durable before returning control to the browser.
                save({'steps': {**data['steps'], data['phase']: step},
                      'status': 'running' if data['phase'] == 'extract' else 'reviewing', 'error': None})
                return
            status, text = client.read(data, step)
            if status == 'pending':
                save({'status': 'running' if data['phase'] == 'extract' else 'reviewing', 'error': None})
                return
            # A returned model call still consumed a step if its content fails
            # validation; never hide that call from customer progress/cost review.
            save({'completedCalls': max(data.get('completedCalls',0), {'extract':1,'review':2,'repair':3,'repair2':4}[data['phase']])})
            save(self.result_updates(data, text, script))
        except Exception as error:
            data = self._get(ctx, identity)['data']
            step = data['steps'].get(data['phase'], {})
            code = getattr(error, 'code', 'ANALYSIS_PROVIDER_UNAVAILABLE')
            if code == 'PROVIDER_NODE_NAME_CONFLICT':
                step['rejectedBeforeSubmission']=True
                save({'steps':{**data['steps'],data['phase']:step}})
                state, message = 'failed', 'LibTV 拒绝了重名节点，尚未提交。可以使用新编号继续本步骤。'
            elif step.get('attempted') and not step.get('taskId'):
                state, message = 'unknown_submission', '提交结果尚未确认，已保留原请求并停止重发。'
            elif code in ('ANALYSIS_RESULT_INVALID', 'ANALYSIS_PROVIDER_FAILED', 'ANALYSIS_SOURCE_CHANGED'):
                state, message = 'failed', str(error)
            elif code == 'PROVIDER_RESPONSE_TOO_LARGE':
                state, message = 'interrupted', str(error)
            elif code in ('PROVIDER_PROTOCOL_ERROR','PROVIDER_UNAVAILABLE'):
                state, message = 'interrupted', 'LibTV 的状态查询暂时异常，已保留原任务；继续查询不会重新生成或重复提交。'
            else:
                state, message = 'interrupted', '分析暂时中断，请检查原账号授权后继续查询；已有结果和原文保留。'
            try: save({'status': state, 'error': {'code': code, 'message': message}})
            except WorkflowError: pass
        finally:
            with self.store.transaction(ctx) as tx:
                row = tx.get(self.collection, identity); data = row['data']
                if data.get('lease') and data['lease']['token'] == token:
                    data['lease'] = None
                    tx.update(self.collection, identity, data, expected_version=row['version'])
            if data['status'] not in ('preparing','submitting','running','reviewing'):
                with self._lock:self._clients.pop((ctx.tenantId,ctx.siteSessionId,identity),None)

    def result_updates(self, data, text, script):
        if data['phase']=='extract' and data.get('analysisPolicy')=='single' and not data.get('reviewRequested'):
            return {'result':parse_result(text,script),'completedCalls':1,'status':'ready','error':None}
        if data['phase'] == data.get('repairFromPhase', 'review' if data.get('repairRequested') else None):
            result = parse_result(text, script, reviewable=True)
            return {'repairDraft': result, 'completedCalls': 3 if data['phase']=='repair' else 2, 'phase': 'repair2' if data['phase']=='repair' else 'repair', 'status': 'reviewing', 'error': None}
        result = parse_result(text, script, reviewable=data['phase']=='extract')
        if data['phase'] == 'extract':
            return {'draft': result, 'completedCalls': 1, 'phase': 'review', 'status': 'reviewing', 'error': None}
        return {'result': result, 'completedCalls': {'review':2,'repair':3,'repair2':4}[data['phase']], 'status': 'ready', 'error': None}

    def repair_result(self, ctx, identity, body):
        public_input(body, {'confirmSpend'})
        if not self.enabled or body.get('confirmSpend') is not True:
            raise WorkflowError('ANALYSIS_SPEND_CONFIRMATION_REQUIRED', '修复需要额外 1 次 AI 调用，请确认使用原账号积分。', 409)
        with self.store.transaction(ctx) as tx:
            row=tx.get(self.collection,identity);data=row['data']
            if data['status'] in ACTIVE and data.get('repairRequested'):
                return self._public(row)
            if not self._public(row).get('canRepairResult'):
                raise WorkflowError('ANALYSIS_REVIEW_UNAVAILABLE','这份记录不满足继续修复条件，请核对任务状态。',409)
            data.update(status='reviewing',repairRequested=True,repairFromPhase=data['phase'],error=None,updatedAt=now())
            tx.update(self.collection,identity,data,expected_version=row['version'])
        self._schedule(ctx,identity)
        return self.get(ctx,identity)

    def retry_submission(self, ctx, identity):
        if not self.enabled:
            raise WorkflowError('ANALYSIS_UNAVAILABLE', self.capabilities()['message'], 503)
        with self.store.transaction(ctx) as tx:
            row=tx.get(self.collection,identity);data=row['data']
            if not self._public(row).get('canRetrySubmission'):
                raise WorkflowError('ANALYSIS_RETRY_UNAVAILABLE','只允许继续被官方明确拒绝、尚未提交的请求；不重发未知回执。',409)
            step=data['steps'].pop(data['phase'])
            data.setdefault('rejectedSteps',{}).setdefault(data['phase'],[]).append(copy.deepcopy(step))
            data.update(displayNumber=self._allocate_number(tx,data['projectId']),status='preparing',error=None,updatedAt=now())
            tx.update(self.collection,identity,data,expected_version=row['version'])
        self._schedule(ctx,identity)
        return self.get(ctx,identity)

    def resume_review(self, ctx, identity):
        if not self.enabled:
            raise WorkflowError('ANALYSIS_UNAVAILABLE', self.capabilities()['message'], 503)
        with self.store.transaction(ctx) as tx:
            row=tx.get(self.collection,identity);data=row['data']
            if not (data['status']=='failed' and data['phase']=='extract' and
                    data.get('error',{}).get('code')=='ANALYSIS_RESULT_INVALID' and
                    data['steps'].get('extract',{}).get('taskId') and not data['steps'].get('review')):
                raise WorkflowError('ANALYSIS_REVIEW_UNAVAILABLE','此记录不能继续原结果复核，请核对任务状态。',409)
            data.update(status='running',reviewRequested=True,error=None,updatedAt=now())
            tx.update(self.collection,identity,data,expected_version=row['version'])
        self._schedule(ctx,identity)
        return self.get(ctx,identity)

    def candidate(self, ctx, identity):
        data = self._get(ctx, identity)['data']
        if data['status'] != 'ready':
            raise WorkflowError('ANALYSIS_NOT_READY', 'AI 分析尚未完整返回，请先核对状态。', 409)
        script = self.services.workflow.get_script(ctx, data['projectId'], data['scriptId'])
        plan = self.services.workflow.get_plan(ctx, data['projectId'])
        return {'analysisId': identity, 'expectedVersion': plan['version'], 'stylePrompt': plan['stylePrompt'],
                'entities': asset_candidates(data['result'], script), 'hasExistingPlan': bool(plan['entities'])}
