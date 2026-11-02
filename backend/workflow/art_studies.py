"""Three explicit art studies, usable before production planning; no automatic spend."""
import copy
import hashlib

from .errors import WorkflowError, public_input, conflict
from .service import owner_key, text_field

ROLES = {'character': ('character', '全剧美术 · 人物风格样板'),
         'scene': ('scene', '全剧美术 · 场景风格样板'),
         'trial': ('scene', '全剧美术 · 人物入景试镜')}


def entity_id(project_id, role):
    return 'ent_art_' + hashlib.sha256((project_id + '\0' + role).encode()).hexdigest()[:24]


def describe(project):
    return {role: {'entityId': entity_id(project['id'], role), 'name': value[1]}
            for role, value in ROLES.items()}


def checked_samples(workflow, tx, project_id, samples, owner, *, trial=True):
    roles = set(ROLES) if trial else {'character', 'scene'}
    if not isinstance(samples, dict) or set(samples) != roles:
        raise WorkflowError('ART_SAMPLES_REQUIRED', '请选定人物、场景样板，并完成使用这两张图的入景试镜。', 409)
    result = {}
    project = workflow._project(tx, project_id)
    for role in roles:
        item = samples[role]
        public_input(item, {'revisionId', 'sha256'})
        r = workflow._revision(tx, item.get('revisionId'))
        if r['projectId'] != project_id or owner_key(r['ownership']) != owner_key(owner):
            raise WorkflowError('OWNERSHIP_MISMATCH', '美术样板须属于本项目和当前账号空间。', 409)
        entity = workflow._entity(project, r['entityId'])
        if (r['stage'] != 'style' or entity['category'] != ROLES[role][0]
                or not workflow._valid(tx, r, require_approved=True)):
            raise WorkflowError('STYLE_REVIEW_REQUIRED', '请先选用当前有效的人物和场景风格图。', 409)
        if r['sha256'] != item.get('sha256'):
            conflict('样板图片版本已变化，请重新选择。')
        if role == 'trial' and r['entityId'] != entity_id(project_id, 'trial'):
            raise WorkflowError('ART_TRIAL_REQUIRED', '请使用本剧人物入景试镜的结果。', 409)
        result[role] = r
    if trial and not {result['character']['id'], result['scene']['id']} <= set(result['trial']['sourceRevisionIds']):
        raise WorkflowError('ART_TRIAL_CHANGED', '人物或场景样板已更换，请用当前两张样板重新试镜。原图已保留。', 409)
    return result


def prepare(workflow, ctx, project_id, body):
    public_input(body, {'role', 'samples', 'prompt', 'settings', 'modelId', 'expectedPlanVersion',
                        'expectedSelectionRevision', 'expectedArtDirectionVersion', 'idempotencyKey'})
    role = body.get('role')
    if not isinstance(role,str) or role not in ROLES:
        raise WorkflowError('INPUT_INVALID', '请选择人物、场景或入景试镜。')
    prompt = text_field(body, 'prompt', 15000, required=True)
    if not workflow.tasks:
        raise WorkflowError('TASK_SERVICE_UNAVAILABLE', '图片制作服务尚未连接。', 503)
    selection = workflow.tasks._selection(ctx)
    owner = workflow.tasks._owner(ctx, selection)
    if selection['revision'] != body.get('expectedSelectionRevision'):
        conflict('账号选择已变化，请重新核对。')
    sources = []
    with workflow.repository.transaction(ctx) as tx:
        project = workflow._project(tx, project_id)
        if body.get('expectedArtDirectionVersion', 0) != (project.get('artDirection') or {}).get('version', 0):
            conflict('本剧美术标准已变化，请刷新后核对。')
        if role == 'trial':
            samples = checked_samples(workflow, tx, project_id, body.get('samples'), owner, trial=False)
            sources = [samples[k]['id'] for k in ('character', 'scene')]
            prompt = ('人物样板={{reference:' + sources[0] + '}}；场景样板={{reference:' + sources[1]
                      + '}}。将这一人物置入该场景，保持身份与空间，核对画风、光影、材质是否融合。\n' + prompt)
    plan = workflow.get_plan(ctx, project_id)
    target = entity_id(project_id, role)
    if not any(e['id'] == target for e in plan['entities']):
        if body.get('expectedPlanVersion') != plan['version']:
            conflict('物料清单已变化，请刷新后再试。')
        fields = {'id','category','name','description','origin','quote','scriptId','variant'}
        entities = [{k:copy.deepcopy(v) for k,v in e.items() if k in fields} for e in plan['entities']]
        entities.append({'id': target, 'category': ROLES[role][0], 'name': ROLES[role][1],
                         'origin':'manual', 'variant':'美术试做',
                         'description':'全剧美术试做样板，作为画风探索；不等同于已确认的剧情物料。'})
        workflow.save_plan(ctx, project_id, {'expectedVersion': plan['version'], 'stylePrompt':plan['stylePrompt'], 'entities':entities})
    # Trial is an art-study candidate, never a production shot. Its two immutable
    # references flow through the same ownership, review, hash and paid-task gates.
    return workflow.tasks.prepare(ctx, {'projectId':project_id, 'entityId':target,
        'recipe':'image25_style', 'modelId':body.get('modelId','Lib Image 2.5 Pro'),
        'prompt':prompt, 'settings':body.get('settings',{}), 'sourceRevisionIds':sources},
        body.get('expectedSelectionRevision'), body.get('idempotencyKey'))
