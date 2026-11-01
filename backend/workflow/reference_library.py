"""Project reference images are separate from generated production assets."""
import base64
import copy

from .errors import invalid, public_input, WorkflowError, tenant
from .service import inspect_image, new_id, now, owner_key, OWNER_FIELDS, REQUIRED_OWNER, text_field


def import_reference(workflow, ctx, project_id, body, *, provenance=None):
    public_input(body, {'name','contentBase64','expectedSelectionRevision'})
    selected=workflow.tasks._selection(ctx)
    if selected['revision']!=body.get('expectedSelectionRevision'):
        raise WorkflowError('SELECTION_CHANGED','当前账号选择已变化，请重新核对。',409)
    owner=workflow.tasks._owner(ctx,selected)
    try:
        encoded=body.get('contentBase64')
        if not isinstance(encoded,str) or len(encoded)>12*1024*1024: raise ValueError()
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError): invalid('请选择不超过 8 MiB 的 PNG、JPEG 或 WebP 图片。')
    if len(raw)>8*1024*1024: invalid('参考图不能超过 8 MiB。')
    metadata=inspect_image(raw)
    name=text_field(body,'name',120,required=True)
    with workflow.repository.transaction(ctx,write=True) as tx:
        workflow._project(tx,project_id)
        prior=next((r for r in tx.state['revisions'].values() if r.get('referenceOnly') and r['projectId']==project_id
                    and r['sha256']==metadata['sha256'] and owner_key(r['ownership'])==owner_key(owner)),None)
        if prior:return {'revision':workflow._public_revision(tx,prior),'duplicate':True}
        asset_id,revision_id=new_id('ast'),new_id('rev')
        asset={'id':asset_id,'projectId':project_id,'entityId':new_id('ref'),'name':name,'category':'reference',
               'referenceOnly':True,'version':1,'entityVersion':1,'active':True,'createdAt':now(),'revisionIds':[revision_id]}
        revision={'id':revision_id,'assetId':asset_id,'projectId':project_id,'entityId':asset['entityId'],
            'tenantId':tenant(ctx),'ownership':{k:copy.deepcopy(owner.get(k)) for k in (*REQUIRED_OWNER,*OWNER_FIELDS)},
            'referenceOnly':True,'stage':'reference','recipe':'imported_reference','taskId':None,'outputKey':'0',
            'provenance':copy.deepcopy(provenance or {'kind':'local_upload'}),
            'sourceRevisionIds':[],'refineSourceRevisionId':None,'entityVersion':1,'styleVersion':0,
            'prompt':'','settings':{},'modelLabel':'LibTV 素材库参考图' if provenance else '上传参考图','review':'pending','reviewNote':'','reviewHistory':[],
            'status':'ready','createdAt':now(),'blobId':tx.put_blob(raw),**metadata}
        tx.state['assets'][asset_id]=asset;tx.state['revisions'][revision_id]=revision
        return {'revision':workflow._public_revision(tx,revision),'duplicate':False}


def import_library_reference(services,ctx,project_id,body):
    public_input(body,{'assetId','expectedAssetVersion','imageIndex','expectedSelectionRevision'})
    tasks=services.tasks
    selected=tasks._selection(ctx)
    if selected['revision']!=body.get('expectedSelectionRevision'):
        raise WorkflowError('SELECTION_CHANGED','当前账号选择已变化，请重新核对。',409)
    owner=tasks._owner(ctx,selected);client=tasks._client(ctx,owner)
    from backend.generation.asset_library import details
    item=details(client.get_asset(body.get('assetId'),project_id))
    if item['id']!=body.get('assetId') or item['version']!=body.get('expectedAssetVersion'):
        raise WorkflowError('VERSION_CONFLICT','素材库图片已更新，请重新查看后引用。',409)
    image=next((r for r in item['images'] if r['index']==body.get('imageIndex')),None)
    if image is None:invalid('请选择素材中的一张图片。')
    raw,_=services.generation.media.get_image(image['url'],max_bytes=8*1024*1024,max_pixels=40_000_000)
    result=import_reference(services.workflow,ctx,project_id,{'name':item['name'],
        'contentBase64':base64.b64encode(raw).decode(),'expectedSelectionRevision':selected['revision']},
        provenance={'kind':'libtv_asset_library','assetId':item['id'],'assetVersion':item['version'],
                    'itemIndex':image['itemIndex'],'outputIndex':image['outputIndex']})
    # Imported images still require the visible review action before use.
    return result
