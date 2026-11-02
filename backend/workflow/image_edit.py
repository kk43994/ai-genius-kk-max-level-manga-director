"""Explicit use of a candidate as an editing input, separate from adoption."""
import copy

from .errors import WorkflowError, invalid, tenant
from .service import inspect_image, new_id, now, owner_key, STAGES


def editing_reference(workflow, ctx, project_id, entity_id, owner, recipe, body):
    if body.get('confirmEditReference') is not True:
        invalid('请确认以这张原图为参考重抽。')
    note = body.get('editNote', '')
    if not isinstance(note, str) or len(note) > 2000:
        invalid('修改意见不能超过 2000 字。')
    with workflow.repository.transaction(ctx, write=True) as tx:
        source = workflow._revision(tx, body.get('editRevisionId'))
        if (source['projectId'] != project_id or source['entityId'] != entity_id
                or source['stage'] != STAGES[recipe] or source.get('referenceOnly')
                or owner_key(source['ownership']) != owner_key(owner)):
            raise WorkflowError('OWNERSHIP_MISMATCH', '重抽原图与当前档案、阶段或账号不一致。', 409)
        reconfirmation = workflow._reconfirmation(tx, source)
        applicable = workflow._valid(tx, source) or (reconfirmation and body.get('expectedEditEntityVersion') == reconfirmation['entityVersion'])
        if source['sha256'] != body.get('editSha256') or not applicable:
            raise WorkflowError('SOURCE_CHANGED', '重抽原图或制作依据已变化，请重新选图。', 409)
        raw = tx.get_blob(source['blobId'])
        metadata = inspect_image(raw)
        if metadata['sha256'] != source['sha256']:
            raise WorkflowError('SOURCE_CHANGED', '原图文件校验失败，尚未准备重抽。', 409)
        # Preserve original identity/scene references, replacing only earlier edit
        # seeds. These are still validated by build_spec and before submission.
        retired = [rid for rid in source['sourceRevisionIds']
                   if tx.state['revisions'].get(rid, {}).get('provenance', {}).get('kind') == 'image_edit']
        refs = [rid for rid in source['sourceRevisionIds']
                if tx.state['revisions'].get(rid, {}).get('provenance', {}).get('kind') != 'image_edit']
        provenance = {'kind': 'image_edit', 'revisionId': source['id'], 'sha256': source['sha256']}
        prior = next((r for r in tx.state['revisions'].values()
                      if r['projectId'] == project_id and r.get('referenceOnly')
                      and r.get('provenance') == provenance
                      and owner_key(r['ownership']) == owner_key(owner)
                      and workflow._valid(tx, r, True)), None)
        if prior:
            return prior['id'], refs, retired
        # A separate immutable input records the explicit reference-use decision.
        # The generated source retains its pending/rejected/adopted state untouched.
        asset_id, revision_id = new_id('ast'), new_id('rev')
        asset = {'id': asset_id, 'projectId': project_id, 'entityId': new_id('ref'),
                 'name': tx.state['assets'][source['assetId']]['name'] + ' · 修改参考',
                 'category': 'reference', 'referenceOnly': True, 'version': 1,
                 'entityVersion': 1, 'active': True, 'createdAt': now(), 'revisionIds': [revision_id]}
        reference = {'id': revision_id, 'assetId': asset_id, 'projectId': project_id,
                     'entityId': asset['entityId'], 'tenantId': tenant(ctx), 'ownership': copy.deepcopy(owner),
                     'referenceOnly': True, 'stage': 'reference', 'recipe': 'imported_reference',
                     'taskId': None, 'outputKey': '0', 'provenance': provenance,
                     'sourceRevisionIds': [], 'refineSourceRevisionId': None, 'entityVersion': 1,
                     'styleVersion': 0, 'prompt': '', 'settings': {}, 'modelLabel': '重抽原图',
                     'review': 'approved', 'reviewNote': '人工明确选择此图作为修改参考；不代表选用原图为成片。',
                     'reviewHistory': [{'decision': 'approved', 'at': now(), 'purpose': 'edit_reference',
                                        'note': '点击带原图重抽，确认使用此图作为编辑输入。'}],
                     'status': 'ready', 'createdAt': now(), 'blobId': tx.put_blob(raw), **metadata}
        tx.state['assets'][asset_id] = asset
        tx.state['revisions'][revision_id] = reference
        return revision_id, refs, retired
