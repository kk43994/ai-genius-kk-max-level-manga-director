"""Version selection and durable draw requests. Image execution is a separate worker."""
import copy,hashlib,json,os,uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

TARGETS={'lin-jingwen-reference-v2','taiping-reference-v2','lin-jingwen-fourview-v2'}
class ActionError(Exception):
    def __init__(self,message,status=400):self.message=message;self.status=status

def target_data(m,target):
    if target=='white-model':
        w=m['whiteModelReview']
        return w,{'version':w['sceneVersion'],'fingerprint':w['meshSha256'],'selectionId':w.get('lastReviewId')}
    t=next((t for t in m['tasks'] if t['id']==target),None)
    if not t:raise ActionError('找不到这张素材',404)
    if target not in TARGETS and not t.get('generated') and not t.get('generationPlan'):raise ActionError('这个素材目前只支持查看')
    return t,{'version':t['id'],'fingerprint':t.get('contentSha256',t['file']),'selectionId':t.get('lastReviewId')}

def atomic_json(path,data):
    temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));os.replace(temp,path)

def make_preview_job(m,target,now,preset='warm'):
    if preset not in ['natural','warm','cool']:raise ActionError('请选择一种可用的配色。')
    source,revision=target_data(m,target)
    if target!='white-model' and source.get('qualityTier')!='material_preview':raise ActionError('这个素材不支持本地材质预览。')
    white,geometry=target_data(m,'white-model')
    if white['status']!='approved':raise ActionError('请先选用一版场景布局。',409)
    identity=json.dumps({'source':revision,'geometry':geometry,'preset':preset,'kind':'material-preview'},sort_keys=True)
    signature=hashlib.sha256(identity.encode()).hexdigest()
    existing=next((j for j in m.get('generationQueue',[]) if j['signature']==signature and j['status'] not in ['cancelled','superseded']),None)
    if existing:return existing,False
    labels={'natural':'自然木石','warm':'暖阳木石','cool':'清冷青灰'}
    job={'id':'preview-'+uuid.uuid4().hex,'signature':signature,'createdAt':now,'sourceTarget':target,'sourceRevision':revision,
         'geometryRevision':geometry,'kind':'material-preview','stage':'scene-preview','provider':'local','status':'queued',
         'executionState':'waiting_for_worker','title':'太平峰庭院 · '+labels[preset]+'预览','materialPreset':preset,
         'basePrompt':'同一白模、同一机位和灯光；检查配色与构图。','additionalPrompt':'',
         'outputRequirements':'主视角、反打、俯视、侧面，四张独立16:9材质预览。',
         'outputs':[{'view':v['view'],'ratio':'16:9'} for v in white['views']],
         'inputs':['consistency-v2/scene.json','consistency-v2/scene.obj'],'generationStarted':False,
         'videoEnabled':False,'preservePreviousVersions':True,'externalCreditsUsed':0,'qualityTier':'material_preview'}
    m.setdefault('generationQueue',[]).append(job)
    return job,True

def make_job(m,target,prompt,kind,now):
    source,revision=target_data(m,target)
    if target=='white-model' and kind=='next-stage' and m.get('workflowVersion')==2:
        return make_preview_job(m,target,now)
    settings=m.get('generationSettings',{})
    recipe=copy.deepcopy(source.get('pipelineRecipe',{}))
    mapping=settings.get('pipelineModels',{}).get('refine')
    if recipe and mapping:
        recipe.setdefault('models',{})['refine']=mapping['modelKey']
        recipe['refineVerification']=mapping
    phase='asset' if kind=='next-stage' else 'refine' if kind=='polish' else source.get('phase','asset')
    model_key=recipe.get('models',{}).get(phase) or source.get('modelKey') or settings.get('imageModelKey')
    if recipe and phase=='refine' and not recipe.get('models',{}).get('refine'):
        raise ActionError('Banana 2.1 的平台模型映射尚未核实，不能用其他模型代替。',409)
    count=source.get('generationCount',1) if phase=='style' else 1
    identity=json.dumps({'target':target,'source':revision,'prompt':prompt,'kind':kind,'provider':settings.get('provider'),'model':model_key,'count':count,'account':settings.get('accountId')},ensure_ascii=False,sort_keys=True)
    signature=hashlib.sha256(identity.encode()).hexdigest()
    existing=next((j for j in m.get('generationQueue',[]) if j['signature']==signature and j['status'] in ['queued','running','blocked','needs_attention','failed']),None)
    if existing:return existing,False
    white=target=='white-model'
    views=[{'view':v['view'],'ratio':'16:9'} for v in source['views']] if white or source.get('views') else [{'view':'fourview-sheet' if source.get('phase')!='style' else 'style','ratio':source['ratio']}]
    inputs=source.get('referenceFiles') or ([v['file'] for v in source['views']] if white or source.get('views') else [source['file']])
    if white:
        inputs+=['consistency-v2/scene.obj','consistency-v2/scene.json',next(t['file'] for t in m['tasks'] if t['id']=='taiping-reference-v2')]
    spec='同一个庭院，主视角、反打、俯视、侧面，四张独立16:9。保持剧本设定；全部机位共享同一模型版本。' if white else ('单张16:9人物资产图，正面、侧面、背面全身和大头。保持已选人物身份与造型。' if source.get('phase')!='style' else '沿用剧本设定与已确认的参考片画风。')
    base=source.get('prompt',m['whiteModelReview']['description'] if white else '')
    if kind=='next-stage' and white:spec+=' 在已选布局上细化模型，统一材质和灯光，再从同一场景渲染四个角度。'
    if kind=='next-stage' and not white:
        views=[{'view':'fourview-sheet','ratio':'16:9'}]
        spec='单张16:9人物资产图，正面、侧面、背面全身和大头。保持已选人物身份与造型。'
        if source.get('entity')!='scene':
            # Identity comes from the selected image, not the previous portrait layout.
            base='以输入参考图锁定人物身份、脸型、发型、服饰、配色和画风。制作一张横向16:9人物资产设定图：按正面全身、侧面全身、背面全身、头部近景排列。三个全身视图保持相同身高与服装细节；采用简洁背景、均匀照明，保证轮廓和细节清楚。'
    job={'id':'draw-'+uuid.uuid4().hex,'signature':signature,'createdAt':now,'sourceTarget':target,'sourceRevision':revision,'kind':kind,'stage':'scene-render' if kind=='next-stage' else target,'status':'queued','executionState':'waiting_for_worker','title':'太平峰庭院 · 彩色场景' if kind=='next-stage' else '太平峰庭院 · 新布局' if white else source['title'],'requestedModel':m.get('requestedModel'),'basePrompt':base,'additionalPrompt':prompt,'outputRequirements':spec,'outputs':views,'inputs':inputs,'preservePreviousVersions':True,'generationStarted':False,'videoEnabled':False}
    if kind=='next-stage' and not white:job.update(stage='character-asset',title=source['title']+' · 人物四视图')
    if kind=='next-stage' and not white and source.get('entity')=='scene':
        job.update(stage='scene-layout',title=source['title']+' · 场景布局',outputRequirements='基于已选风格建立同一套三维场景，从主视角、反打、俯视、侧面渲染四张16:9布局白模。',outputs=[{'view':v,'ratio':'16:9'} for v in ['main','reverse','overhead','side']])
    if kind=='final-render':
        job.update(stage='scene-render',title='太平峰庭院 · 正式场景制作',outputRequirements='基于已选材质预览细化同一三维模型，四个机位共享最终材质和灯光，输出四张16:9正式场景资产。')
    if settings.get('provider')=='libtv' and not white and (recipe or job['stage'] not in ('scene-render','scene-layout')):
        job.update(provider='libtv',modelKey=model_key,accountId=settings.get('accountId'),downloadWatermark=settings.get('downloadWatermark',False))
    if source.get('catalog'):
        catalog=dict(source['catalog'])
        same=lambda c:all(c.get(k)==catalog.get(k) for k in ('seriesId','entityId','kind','variant'))
        versions=[int(x.get('catalog',{}).get('version',0)) for x in m.get('tasks',[])+m.get('generationQueue',[]) if same(x.get('catalog',{}))]
        catalog['version']=max(versions,default=0)+1
        job.update(catalog=catalog)
    for key in ('batchId','characterId'):
        if key in source:job[key]=source[key]
    if source.get('generationPlan') or source.get('entity')=='shot':
        job.update(stage='storyboard' if source.get('entity')=='shot' else 'character-asset',outputRequirements=source.get('outputRequirements','单张9:16电影分镜，保持机位和人物，无拼图无文字。'))
        # Asset batches can request resolution too; do not silently drop it outside style recipes.
        if source.get('modelSettings') and not recipe:
            job['modelSettings']=copy.deepcopy(source['modelSettings'])
    if recipe and kind=='next-stage' and source.get('batchId')=='death-exception-support-v2' and source.get('characterId') in ('feng','shi'):
        # Repair an authoring-template leak from Ye; never put his sword or fur on other roles.
        old=recipe['assetRequirements']
        clean='单张16:9角色资产卡，正面、侧面、背面全身和大头四栏。正面和侧面颈部以上完全留空无脸，背面保留完整头发轮廓，仅大头栏显示面容。严格保持本角色衣服与饰品，不引入其他人物的毛领或佩剑。'
        recipe['assetPrompt']=recipe['assetPrompt'].replace(old,clean)
        recipe['assetRequirements']=clean
    if recipe and source.get('batchId')=='gift-thoughts-assets-v1' and kind=='next-stage':
        recipe['assetPrompt']+=' 必须彻底移除风格图中所有人物、人体、人物四视图、文字，最终只保留本场景或独立玉瓶。不得复制背景里的角色。'
        framefile=Path(__file__).resolve().parent.parent/'dashixiong-scene-studio/production/gift-hears-thoughts-60s/frame-manifest.json'
        if source.get('characterId') in ('gate','hall') and framefile.exists():
            fdata=json.loads(framefile.read_text());sid='S01' if source['characterId']=='gate' else 'S11'
            guide=next((f['file'] for f in fdata['frames'] if f['shotId']==sid and f['index']==2),None)
            if guide:
                recipe['assetReferenceFiles']=[guide]
                recipe['assetPrompt']+=' 第二张白模图锁定建筑空间与视角，使用第一张的材质和光照完成第二张空间的16:9全景。白模中的彩色人物也全部移除。主体位置和建筑尺寸按白模，不改变场景结构。'
    if recipe:
        # Model setting names differ by stage (Image2 resolution vs Nano quality).
        # Keep same-stage settings on reroll; never leak them into a different model.
        phase_settings=recipe.get('modelSettings',{}).get(phase)
        if phase_settings is None:
            phase_settings=source.get('modelSettings',{}) if phase==source.get('phase','asset') else {}
        job.update(pipelineRecipe=recipe,phase=phase,generationCount=count,modelSettings=copy.deepcopy(phase_settings),stage='character-'+phase)
        if job.get('catalog'):job['catalog'].pop('candidate',None)
        if kind=='reroll' and phase in ('asset','refine'):
            job.update(basePrompt='以唯一输入参考图为基础局部修正角色卡。保持参考图的身份、服装、材质、画幅和版式，只执行本次修改要求。未指定的区域保持原样。',outputRequirements=source.get('outputRequirements',spec))
            if phase=='refine':
                # Re-polish the selected asset, not the previous lossy polish.
                # Walk only recorded ancestry; never select a different character.
                ancestor=source;seen=set()
                while ancestor.get('sourceTarget') and ancestor['id'] not in seen:
                    seen.add(ancestor['id'])
                    parent=next((t for t in m['tasks'] if t['id']==ancestor['sourceTarget']),None)
                    if not parent or not parent.get('generated'):break
                    if parent.get('phase')=='asset':
                        job.update(inputs=[parent['file']],basePrompt=recipe['refinePrompt'],refineSourceTarget=parent['id'])
                        break
                    if parent.get('phase')!='refine':break
                    ancestor=parent
        if kind=='next-stage':
            job.update(inputs=[source['file']]+recipe.get('assetReferenceFiles',[]),basePrompt=recipe['assetPrompt'],outputs=[{'view':recipe.get('assetView','fourview-sheet' if source.get('entity')=='character' else 'reference'),'ratio':recipe.get('assetRatio','16:9')}],
                       outputRequirements=recipe['assetRequirements'],title=source.get('catalog',{}).get('entityName',source['title'])+' · Image2 资产卡')
            if job.get('catalog'):job['catalog'].update(kind=recipe.get('assetKind','fourview' if source.get('entity')=='character' else 'reference'),variant=recipe.get('variant','日常造型 V2'))
        elif kind=='polish':
            job.update(inputs=[source['file']],basePrompt=recipe['refinePrompt'],outputs=[{'view':'fourview-sheet','ratio':source['ratio']}],
                       outputRequirements=source.get('outputRequirements','保持原图结构与版式，仅精修画质。'),title=source.get('catalog',{}).get('entityName',source['title'])+' · Banana 精修')
            if job.get('catalog'):job['catalog'].update(kind='refined',variant=recipe.get('variant','日常造型 V2'))
        if job.get('catalog'):
            catalog=job['catalog']
            same=lambda c:all(c.get(k)==catalog.get(k) for k in ('seriesId','entityId','kind','variant'))
            catalog['version']=max([int(x.get('catalog',{}).get('version',0)) for x in m.get('tasks',[])+m.get('generationQueue',[]) if same(x.get('catalog',{}))],default=0)+1
    m.setdefault('generationQueue',[]).append(job)
    return job,True

def process_action(root,payload,action,lock):
    if not isinstance(payload,dict):raise ActionError('请求格式不正确')
    target=payload.get('target');prompt=payload.get('prompt','')
    if not isinstance(prompt,str) or len(prompt)>4000:raise ActionError('补充要求请控制在4000字以内')
    prompt=prompt.strip()
    with lock:
        path=root/'manifest.json';m=json.loads(path.read_text());source,revision=target_data(m,target)
        if payload.get('sourceRevision')!=revision:raise ActionError('这张图的版本刚刚更新，请刷新页面后再选',409)
        now=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat();selection=None;job=None
        if action=='choose':
            if source.get('generationPlan'):raise ActionError('请等待生成结果后再选版。',409)
            if source.get('staleInput'):raise ActionError('这张图的来源版本已经变化，请基于当前版本重新生成。',409)
            if source.get('geometryRevision'):
                _,geometry=target_data(m,'white-model')
                if geometry!=source['geometryRevision']:raise ActionError('预览对应的白模已变化，请基于当前白模重新制作。',409)
            if source.get('status')=='approved' or source.get('humanReview')=='approved':
                return {'ok':True,'alreadySelected':True,'generationStarted':False}
            rid='choice-'+uuid.uuid4().hex
            selection={'id':rid,'submittedAt':now,'target':target,'decision':'approved','interaction':'use_this_version','sourceRevision':revision,'previousReviewId':revision['selectionId'],'source':'local_selection_web_form','reviewer':payload.get('reviewer','workbench'),'nextStageCorrection':prompt}
            if target=='white-model':
                source.update(status='approved',humanApproval=True,lastReviewId=rid,reviewedAt=now,reviewNote='用户选择：用这版')
                m['scenePipeline'][1]['status']='approved';m['pipeline'][2]['state']='已选用当前布局';m['pipeline'][3]['state']='彩色场景已排队 / 尚未开始生成';m['phase']='已选用布局 · 等待生成彩色场景'
                job,_=make_job(m,target,'','next-stage',now)
            else:
                source.update(humanReview='approved',lastReviewId=rid,reviewedAt=now)
                if source.get('qualityTier')=='material_preview':
                    m['selectedMaterialPreview']=target
                    job,_=make_job(m,target,'','final-render',now)
                elif source.get('generated') and source.get('phase')=='style':
                    job,_=make_job(m,target,prompt,'next-stage',now)
                elif source.get('pipelineRecipe') and source.get('phase')=='asset':
                    source['archivedAt']=now
                    m.setdefault('assetLibrary',[]).append({'taskId':target,'selectedAt':now,'selectionId':rid})
                    if source['pipelineRecipe'].get('models',{}).get('refine') or m.get('generationSettings',{}).get('pipelineModels',{}).get('refine'):
                        job,_=make_job(m,target,prompt,'polish',now)
                elif source.get('phase')!='style':
                    source['archivedAt']=now
                    m.setdefault('assetLibrary',[]).append({'taskId':target,'selectedAt':now,'selectionId':rid})
            m.setdefault('selections',[]).append(selection)
        elif action=='preview':job,_=make_preview_job(m,target,now,payload.get('preset','warm'))
        elif action=='draw':
            if source.get('qualityTier')=='material_preview':raise ActionError('材质预览请使用配色选项生成新版；自由文字修改需要生图或三维制作服务。')
            job,_=make_job(m,target,prompt,'reroll',now)
        else:raise ActionError('不支持的操作')
        atomic_json(path,m)
        # The manifest is the authoritative commit. Mirror files are recoverable exports.
        try:
            if selection:
                folder=root/'reviews';folder.mkdir(exist_ok=True);atomic_json(folder/(selection['id']+'.json'),selection)
                if target=='white-model':atomic_json(root/'consistency-v2/white-model-review.json',source)
            if job:
                folder=root/'draw-requests';folder.mkdir(exist_ok=True);atomic_json(folder/(job['id']+'.json'),job)
        except OSError:pass
        return {'ok':True,'selection':selection,'job':job,'generationStarted':False}
