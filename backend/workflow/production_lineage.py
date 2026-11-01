"""Current-plan identity master -> screenplay state lineage. Never infer from names."""
import copy


def members(tx, project):
    # One immutable repository read snapshot can share its expensive plan check.
    # Writers may change entities in place, so never reuse results in a write tx.
    if getattr(tx, 'write', True):
        return _members(tx, project)
    if not hasattr(tx, '_lineage_members'):
        tx._lineage_members = {}
    if project['id'] not in tx._lineage_members:
        tx._lineage_members[project['id']] = _members(tx, project)
    return tx._lineage_members[project['id']]


def _members(tx, project):
    from backend.analysis.production import ACTIVE, candidates, entity_id, production_states, MASTER_STATE_ID
    from backend.analysis.production_bindings import fingerprint
    from backend.analysis.production_review import decode, inspect
    snapshot = getattr(tx, 'production', {}).get(project['id'], {})
    row = snapshot.get('job')
    if not row or not project.get('scriptIds'):
        return {}
    tx.coverage_projects.add(project['id'])
    data = row['data']
    script = tx.state['scripts'][project['scriptIds'][-1]]
    if (data['status'] in ACTIVE or data['scriptId'] != script['id']
            or data['sourceRevision'] != script['sourceRevision']
            or data['context']['stylePrompt'] != project['plan']['stylePrompt']
            or snapshot.get('analysisReview') and snapshot['analysisReview']['data']['result'] != data['context']['analysis']):
        return {}
    result = copy.deepcopy((snapshot.get('review') or {}).get('data', {}).get('result')
                           or data.get('result') or decode(data.get('productionDraft')))
    if not result or inspect(result, script, data['context']):
        return {}
    templates = {e['id']: e for e in candidates(result, script)}
    entities = {e['id']: e for e in project['plan']['entities']}
    links = project.get('productionLinks', {}).get(row['id'], {})
    membership = {}
    for asset in result['assets']:
        for state in production_states(asset):
            key = entity_id(script['id'], asset['id'], state['id'])
            link = links.get(key)
            identity = link['entityId'] if link else key
            entity, candidate = entities.get(identity), templates[key]
            applicable = bool(entity and (
                link['designFingerprint'] == fingerprint(candidate) and link['entityVersion'] == entity['version']
                if link else all(entity.get(k, '') == candidate.get(k, '')
                                 for k in ('category', 'name', 'description', 'variant', 'quote'))))
            membership.setdefault(identity, []).append(dict(assetId=asset['id'], category=asset['category'],
                role='master' if state['id'] == MASTER_STATE_ID else 'state', valid=applicable))
    return {key: rows[0] if len(rows) == 1 else dict(assetId=None, category='character', role='ambiguous', valid=False)
            for key, rows in membership.items()}


def same_state_family(tx, project, first, second):
    if first == second:
        return True
    rows = members(tx, project)
    a, b = rows.get(first), rows.get(second)
    return bool(a and b and a['valid'] and b['valid'] and a['assetId'] == b['assetId'])


def image2_source_allowed(tx, project, target, source):
    rows = members(tx, project)
    a, b = rows.get(target), rows.get(source['entityId'])
    if target.startswith('ent_pd_') and not a:
        return False
    if a and a['category'] == 'character':
        if not (a['valid'] and b and b['valid'] and a['assetId'] == b['assetId']):
            return False
        if a['role'] == 'state':
            return b['role'] == 'master' and source['stage'] == 'asset'
        # Existing approved MJ identities stay usable without rewriting history.
        return source['stage'] == 'style'
    return source['stage'] == 'style' and (target == source['entityId'] or bool(
        a and b and a['valid'] and b['valid'] and a['assetId'] == b['assetId']))


def character_state(tx, project, target):
    member = members(tx, project).get(target)
    return bool(member and member['category'] == 'character' and member['role'] == 'state')
