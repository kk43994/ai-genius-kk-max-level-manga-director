"""Revision boundaries preserve submitted jobs and their exact source contracts."""
import copy
import json
from datetime import datetime, timezone
from production_actions import ActionError, atomic_json

REFERENCE_BATCH = 'death-exception-reference-v2'

def now():
    return datetime.now(timezone.utc).isoformat()

def begin_revision(owner, payload):
    with owner.lock:
        state = owner.read()
        if state.get('revision', 1) >= 2:
            return {'ok': True, 'alreadyStarted': True, 'revision': state['revision']}
        if owner.workers or any(x.get('status') == 'running' for x in state['operations'].values()):
            raise ActionError('制作任务仍在运行，完成后再创建修订版。', 409)
        final = state['operations'].get('assemble', {})
        if not final.get('sha256') or payload.get('sha256') != final['sha256']:
            raise ActionError('请刷新后核对要修订的成片。', 409)
        if any(j.get('status') not in ('completed', 'cancelled') for j in state.get('videoJobs', [])):
            raise ActionError('请先取回已有视频任务，不能丢弃已提交记录。', 409)
        plan = json.loads((owner.folder/'video-plan-v2.json').read_text())
        if plan.get('revision') != 2 or plan.get('textMode') != 'native-video':
            raise ActionError('新版镜头方案尚未准备。', 409)
        archive = owner.folder/'history/v1'
        archive.mkdir(parents=True, exist_ok=True)
        for name in ('execution.json', 'run.json', 'video-plan.json', 'shots.json', 'edit.json'):
            src = owner.folder/name
            if src.exists() and not (archive/name).exists():
                (archive/name).write_bytes(src.read_bytes())
        old_final = copy.deepcopy(final)
        old_final['review'] = {'accepted': False, 'reviewedAt': now(), 'reviewer': 'user',
                              'reason': '双人朝向不一致；死期与人物名牌改为模型原生生成。'}
        state.setdefault('revisionHistory', []).append({'revision': 1, 'status': 'changes_requested',
            'archivedAt': now(), 'final': old_final, 'videoJobs': copy.deepcopy(state.get('videoJobs', [])),
            'snapshot': 'history/v1/execution.json'})
        state['revision'] = 2
        state['revisionReason'] = old_final['review']['reason'] + ' 叶宇造型需按剧本重新设计。'
        state['revisionRequirements'] = plan.get('requirements', [])
        state['videoJobs'] = []
        state['operations'] = {k: v for k, v in state['operations'].items() if k in ('previs', 'storyboards')}
        state['operations']['references'] = {'status': 'not_started', 'batchId': REFERENCE_BATCH}
        state['updatedAt'] = now()
        atomic_json(owner.path, state)
        run = json.loads((owner.folder/'run.json').read_text())
        run.update(status='revision_in_progress', activeRevision=2)
        run.pop('final', None)
        atomic_json(owner.folder/'run.json', run)
        return {'ok': True, 'revision': 2}

def reference_state(owner, manifest):
    path = owner.root/'batches'/f'{REFERENCE_BATCH}.json'
    definition = json.loads(path.read_text()) if path.exists() else {'items': []}
    tasks = [t for t in manifest['tasks'] if t.get('batchId') == REFERENCE_BATCH and t.get('generated')]
    jobs = [{k: j.get(k) for k in ('id', 'title', 'status', 'executionState', 'resultTaskId', 'batchId')}
            for j in manifest.get('generationQueue', []) if j.get('batchId') == REFERENCE_BATCH]
    items = [{k: item.get(k) for k in ('id', 'name', 'ratio', 'kind', 'variant')} for item in definition['items']]
    return {'referenceAssets': tasks, 'referenceJobs': jobs, 'referenceItems': items,
            'referenceBatchId': REFERENCE_BATCH}

def selected_references(state):
    selected = {}
    for item in state.get('referenceItems', []):
        latest = next((t for t in reversed(state.get('referenceAssets', [])) if t.get('characterId') == item['id']), None)
        if not latest or latest.get('humanReview') != 'approved':
            raise ActionError('请先审看并选用全部新版参考图。', 409)
        selected[item['id']] = latest
    if not selected:
        raise ActionError('新版参考包为空。', 409)
    pending = [j for j in state.get('imageJobs', []) + state.get('referenceJobs', [])
               if j.get('status') in ('queued', 'running', 'needs_attention')]
    if pending:
        raise ActionError('仍有参考图等待生成或取回，请先处理原任务。', 409)
    return selected
