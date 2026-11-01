"""Explicit links to existing assets. Linking never rewrites images or reviews."""
import copy
import hashlib
import json

from backend.workflow.errors import WorkflowError, public_input, conflict
from backend.workflow.service import owner_key, now


def fingerprint(candidate):
    return hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def describe(job, project, plan, script, library, owner):
    from .production import candidates, entity_id
    links = project.get('productionLinks', {}).get(job['id'], {})
    rows = {e['id']: e for e in plan['entities']}
    records = {a['entityId']: a for a in library if a.get('active')}
    templates = {e['id']: e for e in candidates(job['result'], script)}
    bindings = []
    for asset in job['result']['assets']:
        for state in asset['states']:
            default_id = entity_id(job['scriptId'], asset['id'], state['id'])
            candidate = templates[default_id]
            link = links.get(default_id)
            identity = link['entityId'] if link else default_id
            entity = rows.get(identity)
            changed = bool(entity and (
                (link['designFingerprint'] != fingerprint(candidate) or link['entityVersion'] != entity['version'])
                if link else any(entity.get(k) != candidate[k] for k in ('description', 'variant', 'quote'))))
            suggestions = []
            for existing in plan['entities']:
                if existing['id'] == identity or existing['category'] != asset['category']:
                    continue
                # Generated state IDs are explicit destinations, not name-based matches.
                if existing['id'].startswith(('ent_pd_', 'ent_shot_')):
                    continue
                record = records.get(existing['id'], {})
                revisions = record.get('revisions', [])
                owned = [r for r in revisions if all(r['ownership'].get(k) == owner.get(k) for k in ('provider', 'providerAccountId', 'providerIssuer', 'providerSubject', 'spaceId'))]
                if revisions and not owned:
                    continue
                suggestions.append({'entityId': existing['id'], 'name': existing['name'],
                    'entityVersion': existing['version'], 'revisionCount': len(owned),
                    'pendingCount': sum(r['review'] == 'pending' and r['status'] == 'ready' for r in owned),
                    'nameMatch': existing['name'] == asset['name']})
            suggestions.sort(key=lambda e: (not e['nameMatch'], -e['revisionCount'], e['name']))
            bindings.append({'assetId': asset['id'], 'stateId': state['id'], 'entityId': identity,
                'name': entity['name'] if entity else candidate['name'], 'saved': entity is not None,
                'changed': changed, 'linked': bool(link), 'legacyCandidates': suggestions})
    return bindings


def save(service, ctx, identity, body):
    public_input(body, {'assetId', 'stateId', 'entityId', 'expectedPlanVersion',
        'expectedReviewVersion', 'expectedEditVersion', 'expectedBindingVersion',
        'expectedEntityVersion', 'confirmApplicable'})
    if body.get('confirmApplicable') is not True:
        raise WorkflowError('CONFIRMATION_REQUIRED', '请确认已有档案适用于这个物料状态。', 409)
    job = service.get(ctx, identity)
    if job['status'] != 'ready' or job['stale']:
        raise WorkflowError('PRODUCTION_NOT_READY', '请先核对并保存当前制作方案。', 409)
    if (body.get('expectedReviewVersion') != job['reviewVersion']
            or body.get('expectedEditVersion') != job['editVersion']):
        conflict('方案已更新，请重新核对关联。')
    binding = next((b for b in job['bindings'] if b['assetId'] == body.get('assetId')
                    and b['stateId'] == body.get('stateId')), None)
    if not binding:
        raise WorkflowError('NOT_FOUND', '未找到这个物料状态。', 404)
    original_owner = service._get(ctx, identity)['data']['ownership']
    selection = service.services.tasks._selection(ctx)
    if owner_key(service.services.tasks._owner(ctx, selection)) != owner_key(original_owner):
        raise WorkflowError('OWNERSHIP_MISMATCH', '请切回本方案原账号与空间后关联。', 409)
    from .production import candidates, entity_id
    workflow = service.services.workflow
    script = workflow.get_script(ctx, job['projectId'], job['scriptId'])
    default_id = entity_id(job['scriptId'], body['assetId'], body['stateId'])
    candidate = next(e for e in candidates(job['result'], script) if e['id'] == default_id)
    with workflow.repository.transaction(ctx, write=True) as tx:
        project = workflow._project(tx, job['projectId'])
        if project['plan']['version'] != body.get('expectedPlanVersion'):
            conflict('清单已更新，请重新核对已有档案。')
        links = project.setdefault('productionLinks', {}).setdefault(identity, {})
        version = project.get('productionBindingVersions', {}).get(identity, 0)
        if version != body.get('expectedBindingVersion'):
            conflict('关联已在另一处更新，请刷新后核对。')
        entity = workflow._entity(project, body.get('entityId'))
        if entity['category'] != candidate['category']:
            raise WorkflowError('BINDING_CATEGORY_MISMATCH', '请选择相同类型的物料档案。', 422)
        if entity['version'] != body.get('expectedEntityVersion'):
            conflict('已有档案已变更，请重新核对适用性。')
        if entity['id'] != default_id and entity['id'].startswith(('ent_pd_', 'ent_shot_')):
            raise WorkflowError('BINDING_STATE_MISMATCH', '其他状态的专用档案不能合并到当前状态。', 422)
        revisions = [r for r in tx.state['revisions'].values()
                     if r['projectId'] == project['id'] and r['entityId'] == entity['id']]
        if revisions and not any(owner_key(r['ownership']) == owner_key(original_owner) for r in revisions):
            raise WorkflowError('OWNERSHIP_MISMATCH', '该档案的素材属于其他账号或空间。', 409)
        link = {'entityId': entity['id'], 'entityVersion': entity['version'],
                'designFingerprint': fingerprint(candidate)}
        old = links.get(default_id)
        if old != link:
            links[default_id] = link
            project.setdefault('productionBindingVersions', {})[identity] = version + 1
            project.setdefault('productionLinkHistory', []).append({'productionId': identity,
                'stateEntityId': default_id, 'previous': copy.deepcopy(old), 'link': copy.deepcopy(link), 'at': now()})
            project.update(version=project['version'] + 1, updatedAt=now())
    return service.get(ctx, identity)
