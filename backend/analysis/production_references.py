"""Resolve a saved shot's exact reference images. Read-only; never submits AI work."""
from .production import MENTION


def build_packet(job, shot, library, owner):
    result = job['result']
    assets = {a['id']: a for a in result['assets']}
    references = []
    labels = {}
    for index, ref in enumerate(shot['references'], 1):
        asset = assets[ref['assetId']]
        state = next(s for s in asset['states'] if s['id'] == ref['stateId'])
        name = asset['name'] + ' · ' + state['name']
        label = f'参考图{index}（{name}）'
        labels[asset['id']] = label
        binding = next((b for b in job['bindings'] if b['assetId'] == asset['id'] and b['stateId'] == state['id']), None)
        record = next((a for a in library if binding and a['entityId'] == binding['entityId'] and a.get('active')), None)
        revision = next((r for r in (record or {}).get('revisions', []) if r['id'] == ref.get('revisionId')), None)
        row = {'assetId': asset['id'], 'stateId': state['id'], 'name': name, 'label': label, 'issue': None}
        if not binding or not binding['saved']:
            row['issue'] = '请先确认物料并建立资产档案'
        elif binding['changed']:
            row['issue'] = '物料设定已变化，需要同步档案并重新审核图片'
        elif not ref.get('revisionId'):
            row['issue'] = '请选择并固定一张已审核的 Image2 / Nano 参考图'
        elif not revision or revision['stage'] not in ('asset', 'refine') or revision['status'] != 'ready' or revision['review'] != 'approved' or any(revision['ownership'].get(k) != owner.get(k) for k in ('providerAccountId', 'spaceId', 'provider', 'providerIssuer', 'providerSubject')):
            row['issue'] = '原参考图不可用、未审核或不属于原账号空间，请重新选择'
        else:
            row.update(revisionId=revision['id'], sha256=revision['sha256'],
                       contentUrl=revision['contentUrl'], thumbnailUrl=revision['thumbnailUrl'])
        references.append(row)
    prompt = MENTION.sub(lambda m: labels[m.group(1)], shot['imagePrompt'])
    return {'shotId': shot['id'], 'reviewVersion': job['reviewVersion'],
            'ready': all(r['issue'] is None for r in references),
            'readyCount': sum(r['issue'] is None for r in references),
            'references': references,
            'prompt': '\n'.join(labels.values()) + '\n' + prompt,
            'submissionCreated': False}
