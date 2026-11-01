"""Human-confirmed project art direction, independent of screenplay design."""
import copy

from .errors import WorkflowError, public_input, conflict
from .service import now, owner_key, OWNER_FIELDS, text_field


def describe(workflow, tx, project):
    direction = copy.deepcopy(project.get('artDirection'))
    if not direction:
        return None
    source = tx.state['revisions'].get(direction['revisionId'])
    direction['valid'] = bool(source and source['sha256'] == direction['sha256']
        and workflow._valid(tx, source, require_approved=True))
    return direction


def confirm(workflow, ctx, project_id, payload):
    public_input(payload, {'revisionId', 'sha256', 'notes', 'expectedVersion', 'confirmStyle'})
    if payload.get('confirmStyle') is not True:
        raise WorkflowError('CONFIRMATION_REQUIRED', '请确认这张图与美术规范作为本剧统一风格。', 409)
    notes = text_field(payload, 'notes', 4000, required=True)
    if workflow.tasks is None:
        raise WorkflowError('TASK_SERVICE_UNAVAILABLE', '请先连接本项目的制作账号。', 503)
    selection = workflow.tasks._selection(ctx)
    owner = workflow.tasks._owner(ctx, selection)
    with workflow.repository.transaction(ctx, write=True) as tx:
        project = workflow._project(tx, project_id)
        current = project.get('artDirection') or {}
        if type(payload.get('expectedVersion')) is not int or payload['expectedVersion'] != current.get('version', 0):
            conflict('本剧风格已在另一处更新，请重新核对。')
        revision = workflow._revision(tx, payload.get('revisionId'))
        if revision['projectId'] != project_id or owner_key(revision['ownership']) != owner_key(owner):
            raise WorkflowError('OWNERSHIP_MISMATCH', '风格图须属于本项目和当前账号空间。', 409)
        if revision['stage'] != 'style' or not workflow._valid(tx, revision, require_approved=True):
            raise WorkflowError('STYLE_REVIEW_REQUIRED', '请先选用一张有效的 MJ 风格候选图。', 409)
        if revision['sha256'] != payload.get('sha256'):
            conflict('风格图片版本已变化，请刷新核对。')
        if current.get('revisionId') == revision['id'] and current.get('notes') == notes:
            return describe(workflow, tx, project)
        direction = {'version':current.get('version', 0)+1, 'revisionId':revision['id'],
            'assetId':revision['assetId'], 'sha256':revision['sha256'], 'notes':notes,
            'ownership':{k:revision['ownership'].get(k) for k in OWNER_FIELDS}, 'confirmedAt':now()}
        project['artDirection'] = direction
        project.setdefault('artDirectionHistory', []).append(copy.deepcopy(direction))
        project.update(version=project['version']+1, updatedAt=now())
        return describe(workflow, tx, project)


def prompt_context(direction):
    return (f"\n\n[本剧美术规范 v{direction['version']}：仅作画风背景]\n"
        "当前任务的主体、性别、物件、视图数量和构图只以上文制作要求为准。"
        "以下全剧规范只继承适用的画风、材质和光影；不要把其中其他人物、场景、道具或视图画进本图。\n"
        f"{direction['notes']}\n[/本剧美术规范]\n"
        "最终只绘制上文当前制作对象，严格遵守上文的单体或多视图要求。")


def contains_direction(prompt, direction):
    # Preserve already prepared immutable tasks from the previous composer.
    legacy = f"[本剧美术规范 v{direction['version']}]\n{direction['notes']}\n[/本剧美术规范]\n"
    return prompt.startswith(legacy) or prompt.endswith(prompt_context(direction))


def apply(workflow, tx, project, prompt, ownership, recipe):
    direction = describe(workflow, tx, project)
    if not direction:
        return prompt, 0
    if recipe != 'mj_style' and not direction['valid']:
        raise WorkflowError('STYLE_REVIEW_REQUIRED', '本剧风格参考已变化，请先重新确认风格。', 409)
    if owner_key({**direction['ownership'], 'tenantId':project['tenantId']}) != owner_key(ownership):
        raise WorkflowError('OWNERSHIP_MISMATCH', '请切回本剧风格原账号与空间继续制作。', 409)
    # Put the concrete subject first. A whole-show bible may mention several
    # identities and layouts; leading with it contaminated real MJ candidates.
    return (prompt if contains_direction(prompt, direction) else prompt + prompt_context(direction)), direction['version']
