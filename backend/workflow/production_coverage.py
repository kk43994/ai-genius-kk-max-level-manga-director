"""Read-only delivery scope from the current production snapshot, never name matching."""
import copy
import hashlib
import json

from .service import owner_key


def shot_candidate(script_id, shot, refs, position):
    from backend.analysis.production import shot_entity_id
    signature = hashlib.sha256(json.dumps({'shot': shot, 'refs': refs}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'id': shot_entity_id(script_id, shot['id']), 'category': 'shot',
            'name': f"分镜 {position:03d} · {shot['purpose']}"[:120],
            'description': ('方案签名：' + signature + '\n' + shot['purpose'])[:4000],
            'origin': 'manual', 'quote': '', 'variant': '分镜静帧'}


def coverage(workflow, tx, project):
    """None preserves legacy-only projects; any current production fails closed."""
    from backend.analysis.production import ACTIVE, candidates, entity_id, production_states
    from backend.analysis.production_bindings import fingerprint
    from backend.analysis.production_review import decode, inspect
    from .art_direction import describe
    snapshot = tx.production[project['id']]
    tx.coverage_projects.add(project['id'])
    row = snapshot.get('job')
    if not row and not snapshot['prior'] and not snapshot['current']:
        return None
    versions = sorted((collection, identity, version)
                      for (collection, identity), version in tx.production_reads[project['id']].items())
    scope_version = hashlib.sha256(json.dumps(versions).encode()).hexdigest()
    base = dict(scope='production', scopeVersion=scope_version, total=0, ready=0,
                complete=False, entities=[], missing=[], exportRevisionIds=[])
    if not row:
        return {**base, 'message': '当前剧本尚未完成制作清单，请回到剧本分析。'}
    data = row['data']
    base['productionId'] = row['id']
    script = tx.state['scripts'][project['scriptIds'][-1]]
    if (data['scriptId'] != script['id'] or data['sourceRevision'] != script['sourceRevision']
            or data['context']['stylePrompt'] != project['plan']['stylePrompt']):
        return {**base, 'message': '制作方案依据已变化，请先核对当前剧本和方案。'}
    if snapshot.get('analysisReview') and snapshot['analysisReview']['data']['result'] != data['context']['analysis']:
        return {**base, 'message': '剧本分析已修改，请先更新制作方案。'}
    if data['status'] in ACTIVE:
        return {**base, 'message': '制作方案正在处理，完成后才能核对交付范围。'}
    result = copy.deepcopy(data.get('result') or decode(data.get('productionDraft')))
    if snapshot.get('review'):
        result = copy.deepcopy(snapshot['review']['data']['result'])
    if result is None:
        return {**base, 'message': '制作方案尚未返回完整清单，请先完成剧本分析。'}
    edits = (snapshot.get('edit') or {}).get('data', {}).get('shots', {})
    for shot in result.get('shots', []):
        shot.update(edits.get(shot['id'], {}))
    if inspect(result, script, data['context']):
        return {**base, 'message': '制作方案还有待核对项，请先修改并保存。'}
    owner = data['ownership']
    direction = describe(workflow, tx, project)
    style_ready = bool(direction and direction['valid'] and
                       owner_key({**direction['ownership'], 'tenantId': project['tenantId']}) == owner_key(owner))
    entities = {e['id']: e for e in project['plan']['entities']}
    links = project.get('productionLinks', {}).get(row['id'], {})
    approved = [r for r in tx.state['revisions'].values()
                if r['projectId'] == project['id'] and owner_key(r['ownership']) == owner_key(owner)
                and workflow._valid(tx, r, True)]
    rows, exports = [], set()

    def add(candidate, *, link=None, blocked=False, **identity):
        target = link['entityId'] if link else candidate['id']
        entity = entities.get(target)
        applicable = bool(entity and not blocked and (
            link['designFingerprint'] == fingerprint(candidate) and link['entityVersion'] == entity['version']
            if link else all(entity.get(k, '') == candidate.get(k, '')
                             for k in ('category', 'name', 'description', 'variant', 'quote'))))
        revisions = [r for r in approved if r['entityId'] == target] if applicable else []
        stages = {stage: any(r['stage'] == stage for r in revisions)
                  for stage in (('storyboard',) if candidate['category'] == 'shot' else ('style', 'asset', 'refine'))}
        if applicable and candidate['category'] != 'shot' and not stages['style']:
            from .production_lineage import same_state_family
            shared_styles = [r for r in approved if r['stage'] == 'style'
                             and same_state_family(tx, project, target, r['entityId'])]
            stages['style'] = bool(shared_styles)
            exports.update(r['id'] for r in shared_styles)
        required = ('storyboard',) if candidate['category'] == 'shot' else ('style', 'asset')
        rows.append(dict(entityId=target, name=candidate['name'], category=candidate['category'],
                         stages=stages, ready=style_ready and all(stages[s] for s in required), **identity))
        exports.update(r['id'] for r in revisions)

    templates = {e['id']: e for e in candidates(result, script)}
    for asset in result['assets']:
        for state in production_states(asset):
            key = entity_id(script['id'], asset['id'], state['id'])
            add(templates[key], link=links.get(key), assetId=asset['id'], stateId=state['id'])
    material_rows = {(r['assetId'], r['stateId']): r for r in rows}
    for position, shot in enumerate(result['shots'], 1):
        refs = [ref.get('revisionId') for ref in shot['references']]
        valid_refs = all(any(r['id'] == ref.get('revisionId') and r['stage'] in ('asset', 'refine')
                             and r['entityId'] == material_rows[(ref['assetId'], ref['stateId'])]['entityId']
                             for r in approved) and material_rows[(ref['assetId'], ref['stateId'])]['ready']
                         for ref in shot['references'])
        add(shot_candidate(script['id'], shot, refs, position), blocked=not valid_refs, shotId=shot['id'])
    if style_ready:
        exports.add(direction['revisionId'])
    ready = sum(r['ready'] for r in rows)
    return {**base, 'total': len(rows), 'ready': ready, 'complete': bool(rows) and ready == len(rows),
            'entities': rows, 'missing': [r for r in rows if not r['ready']],
            'exportRevisionIds': sorted(exports),
            'message': '' if style_ready else '请先确认本剧美术风格，再核对交付。'}
