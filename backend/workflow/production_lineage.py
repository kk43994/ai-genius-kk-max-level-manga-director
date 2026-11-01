"""Verified current-plan state families; names never establish identity."""
import copy


def same_state_family(tx, project, first, second):
    if first == second:
        return True
    from backend.analysis.production import ACTIVE, candidates, entity_id
    from backend.analysis.production_bindings import fingerprint
    from backend.analysis.production_review import decode, inspect
    snapshot = getattr(tx, 'production', {}).get(project['id'], {})
    row = snapshot.get('job')
    if not row or not project.get('scriptIds'):
        return False
    tx.coverage_projects.add(project['id'])
    data = row['data']
    script = tx.state['scripts'][project['scriptIds'][-1]]
    if (data['status'] in ACTIVE or data['scriptId'] != script['id']
            or data['sourceRevision'] != script['sourceRevision']
            or data['context']['stylePrompt'] != project['plan']['stylePrompt']
            or snapshot.get('analysisReview') and snapshot['analysisReview']['data']['result'] != data['context']['analysis']):
        return False
    result = copy.deepcopy((snapshot.get('review') or {}).get('data', {}).get('result')
                           or data.get('result') or decode(data.get('productionDraft')))
    if not result or inspect(result, script, data['context']):
        return False
    templates = {e['id']: e for e in candidates(result, script)}
    entities = {e['id']: e for e in project['plan']['entities']}
    links = project.get('productionLinks', {}).get(row['id'], {})
    membership = {first: set(), second: set()}
    for asset in result['assets']:
        for state in asset['states']:
            key = entity_id(script['id'], asset['id'], state['id'])
            link = links.get(key)
            identity = link['entityId'] if link else key
            if identity not in membership:
                continue
            entity, candidate = entities.get(identity), templates[key]
            applicable = bool(entity and (
                link['designFingerprint'] == fingerprint(candidate) and link['entityVersion'] == entity['version']
                if link else all(entity.get(k, '') == candidate.get(k, '')
                                 for k in ('category', 'name', 'description', 'variant', 'quote'))))
            if applicable:
                membership[identity].add(asset['id'])
    return len(membership[first]) == 1 and membership[first] == membership[second]
