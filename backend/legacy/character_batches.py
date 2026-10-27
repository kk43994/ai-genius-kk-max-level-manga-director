"""Idempotent, reviewed batch definitions. Each character gets an independent job."""
import hashlib
import json
import re
from datetime import datetime, timezone
from production_actions import ActionError, make_job


def start_batch(execution, payload):
    batch_id = payload.get('batchId', '')
    if not isinstance(batch_id, str) or not re.fullmatch(r'[a-z0-9-]{1,80}', batch_id):
        raise ActionError('批次编号不正确。')
    path = execution.root / 'batches' / (batch_id + '.json')
    if not path.is_file():
        raise ActionError('找不到已准备的角色批次。', 404)
    definition = json.loads(path.read_text())
    if not execution.verified or execution.provider is not execution.libtv:
        raise ActionError('请先连接 LibTV。', 409)
    with execution.lock:
        m = execution.read()
        existing = next((b for b in m.get('characterBatches', []) if b['id'] == batch_id), None)
        if existing:
            return {'ok': True, 'batch': existing, 'alreadyCreated': True}
        settings = m.get('generationSettings', {})
        if settings.get('provider') != 'libtv':
            raise ActionError('当前图片服务不是 LibTV。', 409)
        stamp = datetime.now(timezone.utc).isoformat()
        jobs = []
        for char in definition.get('characters', definition.get('items', [])):
            target = 'plan-' + batch_id + '-' + char['id']
            suffix={'shot':'镜头图','character':'角色四视图','scene':'场景参考','prop':'物品参考','effect':'效果参考'}.get(char.get('category','character'),'参考图')
            source = {'id': target, 'title': char.get('title',char['name'] + ' · ' + suffix),
                      'generationPlan': True, 'entity': char.get('category','character'), 'phase': char.get('phase','asset'),
                      'ratio': char.get('ratio','16:9'), 'file': char['references'][0], 'referenceFiles': char['references'],
                      'prompt': char['prompt'], 'outputRequirements': definition['outputRequirements'],
                      'contentSha256': hashlib.sha256(json.dumps(char, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                      'batchId': batch_id, 'characterId': char['id'], 'humanReview': 'not_generated',
                      'catalog': {'seriesId': 'dashixiong', 'seriesTitle': '别惹大师兄',
                                  'category': char.get('category','character'), 'entityId': char.get('entityId',char['id']), 'entityName': char.get('entityName',char['name']),
                                  'kind': char.get('kind','fourview'), 'variant': char.get('variant','正片造型'), 'version': 0}}
            for key in ('modelKey','generationCount','modelSettings','pipelineRecipe'):
                if key in char:source[key]=char[key]
            m.setdefault('tasks', []).append(source)
            job, _ = make_job(m, target, definition.get('instruction','按本批次的角色设定重新设计。唯一的共享约束是参考图的渲染画风与四栏版式。'), 'character-card', stamp)
            execution.libtv.validate(job)
            jobs.append(job['id'])
        batch = {'id': batch_id, 'title': definition['title'], 'createdAt': stamp, 'jobIds': jobs,
                 'reviewPolicy': definition['reviewPolicy'], 'videoEnabled': False}
        m.setdefault('characterBatches', []).append(batch)
        limit=max(1,min(24,int(definition.get('maxConcurrentImages',settings.get('maxConcurrentImages',12)))))
        settings['maxConcurrentImages'] = limit
        # Keep the original entitlement observation date; dispatch is not a fresh account check.
        settings.setdefault('concurrencyEvidence', {}).update(localDispatchLimit=limit, reservedSlots=0)
        execution.write(m)
    execution.wake()
    return {'ok': True, 'batch': batch, 'alreadyCreated': False}
