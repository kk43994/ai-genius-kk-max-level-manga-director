"""Human-curated prompt recipes with inspectable evidence; no quality guarantees."""
import copy
import re
from .errors import WorkflowError, public_input, conflict
from .service import owner_key, text_field, now, new_id


def portable_prompt(prompt):
    text = re.sub(r'\n*\[本剧美术规范[^\]]*\][\s\S]*?\[/本剧美术规范\][\s\S]*$', '', prompt)
    text = re.sub(r'\{\{reference:[^}]+\}\}', '{{参考图}}', text)
    return re.sub(r'本次制作对象：[^\n]+', '本次制作对象：{{主体}}。', text).strip()


def save(workflow, ctx, project_id, body):
    public_input(body, {'revisionId','sha256','name','prompt','notes','evidenceRevisionIds','expectedVersion'})
    name=text_field(body,'name',120,required=True)
    prompt=text_field(body,'prompt',15000,required=True)
    notes=text_field(body,'notes',2000,required=True)
    if not workflow.tasks:
        raise WorkflowError('TASK_SERVICE_UNAVAILABLE','请连接原制作账号后保存规范。',503)
    owner=workflow.tasks._owner(ctx,workflow.tasks._selection(ctx))
    ids=body.get('evidenceRevisionIds',[])
    if not isinstance(ids,list) or len(ids)>20 or any(not isinstance(i,str) for i in ids):
        raise WorkflowError('INPUT_INVALID','验证图片列表无效。')
    with workflow.repository.transaction(ctx,write=True) as tx:
        project=workflow._project(tx,project_id)
        if body.get('expectedVersion') != project.get('promptRecipeVersion',0):
            conflict('提示词规范已更新，请刷新后再保存。')
        source=workflow._revision(tx,body.get('revisionId'))
        if source['projectId']!=project_id or owner_key(source['ownership'])!=owner_key(owner):
            raise WorkflowError('OWNERSHIP_MISMATCH','请选择当前项目和账号的已选图片。',409)
        if source['sha256']!=body.get('sha256') or not workflow._valid(tx,source,require_approved=True):
            raise WorkflowError('REVIEW_REQUIRED','先确认选用这张图，再整理它的提示词规范。',409)
        evidence=[]
        for identity in dict.fromkeys([source['id'],*ids]):
            r=workflow._revision(tx,identity)
            if (r['projectId']!=project_id or owner_key(r['ownership'])!=owner_key(owner)
                or r['entityId']!=source['entityId'] or r['stage']!=source['stage']
                or r['prompt']!=source['prompt'] or r['settings']!=source['settings']
                or r.get('modelLabel')!=source.get('modelLabel')
                or r.get('sourceRevisionIds',[])!=source.get('sourceRevisionIds',[])
                or r.get('artDirectionVersion',0)!=source.get('artDirectionVersion',0)
                or not workflow._valid(tx,r)
                or not (r['review']=='approved' or any(h['decision']=='approved' for h in r['reviewHistory']))):
                raise WorkflowError('EVIDENCE_MISMATCH','重复验证需要同一对象、要求、模型与参数下已人工选用的结果。',409)
            evidence.append({'revisionId':r['id'],'assetId':r['assetId'],'sha256':r['sha256']})
        state='draft' if prompt!=portable_prompt(source['prompt']) else 'repeated' if len(evidence)>1 and source.get('modelLabel') else 'single'
        recipe={'id':new_id('prm'),'name':name,'prompt':prompt,'notes':notes,'status':state,
            'category':workflow._entity(project,source['entityId'])['category'],'stage':source['stage'],
            'modelLabel':source.get('modelLabel'),'settings':copy.deepcopy(source['settings']),
            'sourceRevisionId':source['id'],'sourcePrompt':source['prompt'],'evidence':evidence,
            'artDirectionVersion':source.get('artDirectionVersion',0),'createdAt':now()}
        project.setdefault('promptRecipes',[]).append(recipe)
        project['promptRecipeVersion']=project.get('promptRecipeVersion',0)+1
        project.update(version=project['version']+1,updatedAt=now())
        return copy.deepcopy(recipe)
