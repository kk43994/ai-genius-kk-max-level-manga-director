import {escapeHTML as esc,assetURL,belongsToSelection,stageLabels,states,revisionLabel} from './model.js';
import {sourceImagePicker} from './image-choices.js';
import {bindingPicker} from './production-bindings.js';
import {readableText} from './production-references.js';
import {imageReferencePicker} from './image-references.js';
import {recipePicker} from './prompt-recipes.js';
import {imageModelPicker,selectedImageModel} from './image-models.js';

export const generationModes={style:{label:'生成风格候选图',recipe:'image25_style',model:'Lib Image 2.5 Pro'},asset:{label:'生成资产图',recipe:'image25_asset',model:'Image2.5'},refine:{label:'精修这张资产图',recipe:'nano_refine',model:'Nano'},storyboard:{label:'生成分镜图',recipe:'image25_storyboard',model:'Image2.5'}};
export const assetFormats={
 character:{label:'生成角色四视图',keep:'保留这版四视图',prompt:'制作同一角色的规范四视图：正面全身、侧面全身、背面全身、头部特写。四个视图身份、服装、配色和比例一致，完整清晰，简洁背景，不添加文字。',ratio:'16:9'},
 scene:{label:'生成场景多视图',keep:'保留这版场景多视图',prompt:'制作同一场景的四个空间视角：正视图、反打视图、俯视图、侧面视图。保持建筑、陈设、出入口、道具位置、光线和空间关系一致，不添加文字。',ratio:'16:9'},
 prop:{label:'生成道具白底图',keep:'保留这张道具图',prompt:'制作道具的白底正视图，独立、完整、无人物遮挡，清楚展现形状、材质、颜色和关键结构，不添加文字。',ratio:'1:1'}
};
export const MASTER_STATE_ID='__character_master__';
export const SCENE_MASTER_STATE_ID='__scene_master__';
export function storyboardPrompt(result,shot){
 const lines=[readableText(shot.imagePrompt,result,shot)];
 if(shot.framing)lines.push('构图要求：'+shot.framing);
 if(shot.startState)lines.push('本镜开始时的状态：'+shot.startState);
 if(shot.continuity?.length)lines.push('跨镜连续性必须保持：\n'+shot.continuity.join('\n'));
 return lines.join('\n');
}
export function generationContext(options){
 const {result,job,view,assets=[],selection}=options,stage=view.stage||'style';
 const shot=view.kind==='shots'?result.shots[view.index]:null,asset=!shot?result.assets[view.index]:null;
 const character=asset?.category==='character',scene=asset?.category==='scene',identity=character||scene,master=identity&&(stage==='style'||view.characterLayer!=='state');
 const state=master?{id:character?MASTER_STATE_ID:SCENE_MASTER_STATE_ID,name:character?'人物主多视图':'场景主多视图',imagePrompt:scene?'无人物的基础空间，固定布局、出入口和陈设，不带日夜或剧情破坏的特殊变化。':'锁定人物身份、五官、发型、体型和基础服装。中性站姿，干燥整洁，不带伤情、束缚或剧情动作。'}:asset?.states[Math.min(view.state||0,asset.states.length-1)];
 const binding=shot?(job.shotBindings||[]).find(b=>b.shotId===shot.id):(job.bindings||[]).find(b=>b.assetId===asset?.id&&b.stateId===state?.id);
 const library=assets.find(a=>a.entityId===binding?.entityId&&a.active),owner=job.ownership||selection;
 const siblings=(job.bindings||[]).filter(b=>b.assetId===asset?.id&&b.saved&&!b.changed);
 const family=assets.filter(a=>a.active&&siblings.some(b=>b.entityId===a.entityId)).flatMap(a=>a.revisions.map(r=>({...r,sourceName:a.name})));
 const current=(library?.revisions||[]).filter(r=>belongsToSelection(r,owner));
 const versions=identity&&stage==='style'?family.filter(r=>r.stage==='style'&&belongsToSelection(r,owner)):current;
 const masterBinding=(job.bindings||[]).find(b=>b.assetId===asset?.id&&b.stateId===(character?MASTER_STATE_ID:SCENE_MASTER_STATE_ID)&&!b.changed);
 const sourcePool=stage==='asset'?(identity&&!master?family.filter(r=>r.entityId===masterBinding?.entityId):family):current;
 const sourceStage=stage==='refine'||identity&&!master&&stage==='asset'?'asset':'style';
 const sources=sourcePool.filter(r=>belongsToSelection(r,owner)&&r.status==='ready'&&r.review==='approved'&&r.stage===sourceStage).map(r=>({...r,sourceName:character&&r.stage==='style'?asset.name+' · 已选基础形象':r.sourceName}));
 const mode={...generationModes[shot?'storyboard':stage]};
 const selected=selectedImageModel(options.generationDraft||{},options.imageCatalog);
 mode.model=selected.name;mode.modelId=selected.id;
 if(stage==='asset'&&assetFormats[asset?.category])mode.label=scene?(master?'生成场景主多视图':'生成此场景状态多视图'):character?(master?'生成人物主多视图':'生成此状态多视图'):assetFormats[asset.category].label;
 if(character&&stage==='style')mode.label='生成角色形象候选';
 const identityRules=scene&&!master&&stage==='asset'?'严格参考已确认场景主多视图，保留建筑、出入口、陈设和尺度。只改变当前状态要求的光照、日夜或剧情痕迹；保持正视、反打、俯视、侧视空间一致。':character&&!master&&stage==='asset'?'严格参考已确认的人物主多视图，保留同一张脸、发际线和身形；只修改当前剧情状态要求的服装、湿度、伤情等，不重新设计人物。状态描述仅用于提取外观变化，不照搬其中的场景、镜头、坐卧姿势或戏剧动作。仍制作规范四视图，简洁中性背景，完整展示身体与服装，不绘制多人剧情画面。':character&&stage==='style'?'仅探索基础人物形象，不表现被绑、受伤或具体剧情状态。':'';
 const visualContext=!options.project?.artDirection&&result.styleBible?`\n画风参考（只继承适用画风，不引入其他主体）：${result.styleBible}`:'';
 const prompt=shot?storyboardPrompt(result,shot):`本次制作对象：${asset?.name||''}。\n${asset?.design||''}\n${stage==='style'&&character?'基础人物形象，中性站姿，五官清楚，简洁背景。':state?.imagePrompt||''}\n${identityRules}${stage==='asset'?'\n'+(assetFormats[asset?.category]?.prompt||''):''}${visualContext}`;
 return {shot,asset,state,binding,library,versions,sources,mode,prompt,character,scene,identity,master,masterBinding};
}
export function generationGallery(versions,apiBase,{stage,category,direction=false,busy=false,master=false}={}){
 const rows=stage?versions.filter(r=>r.stage===stage):versions;
 const card=r=>{
  const valid=r.status==='ready',chosen=valid&&r.review==='approved',keep=r.stage==='style'?({character:'选用此张作为人物形象',scene:'选用此张作为场景风格',prop:'选用此张作为道具造型'}[category]||'选用此张风格图'):r.stage==='asset'?(category==='character'?(master?'确认这版人物主多视图':'保留这版状态多视图'):(assetFormats[category]?.keep||'保留这版资产图')):r.stage==='storyboard'?'保留这张分镜图':'保留这版精修图';
  const identity=`${revisionLabel(r)} ${r.id.slice(-6)}`;
  return `<figure class="creator-candidate" data-selected="${chosen}">
   <div class="creator-candidate-media">
    <button type="button" class="creator-candidate-pick" aria-label="${esc(chosen?'已选用 '+identity:!valid?'查看历史图片 '+identity:keep+' '+identity)}" aria-pressed="${chosen}" ${chosen||!valid?'data-image-tools':'data-creator-keep'}="${esc(r.id)}" ${busy?'disabled':''}>
     <img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="${esc(revisionLabel(r))} 候选图" loading="lazy">
     <span class="creator-candidate-choice"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>${chosen?'<path d="m8 12 3 3 5-6"/>':''}</svg><span>${chosen?'已选用':valid?'点击选用':'历史版本'}</span></span>
    </button>
    <button type="button" class="creator-candidate-preview" data-wf-review="${esc(r.id)}" aria-label="放大查看 ${esc(identity)}，可填写修改意见" title="放大查看 / 修改意见"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/></svg></button>
   </div>
   <figcaption><span>${esc(revisionLabel(r))}</span><span class="creator-candidate-status">${chosen?'已选用':esc(states[valid?r.review:'stale']||r.review)}</span></figcaption>
   ${direction&&r.stage==='style'?`<button type="button" class="creator-candidate-direction" data-creator-direction="${esc(r.id)}" ${!valid||busy?'disabled':''}>选为本剧风格 <span aria-hidden="true">↗</span></button>`:''}
  </figure>`;
 };
 const current=[...rows].reverse().filter(r=>r.status==='ready'),history=[...rows].reverse().filter(r=>r.status!=='ready');
 return `<div class="board-generation-gallery">${current.map(card).join('')||(history.length?'':'<div class="wf-empty"><h4>等待第一组候选图</h4><p>生成后在这里看图、选用；每一版都会保留。</p></div>')}</div>${history.length?`<details class="creator-generation-history" ${current.length?'':'open'}><summary>查看历史版本（${history.length}）</summary><p class="wf-note">这些图片的依据或审核已变化，保留供对照；请使用当前已审核的上游版本继续制作。</p><div class="board-generation-gallery">${history.map(card).join('')}</div></details>`:''}`;
}
export function generationInspector(options){
 const {view,result,job,busy,apiBase,tasks=[],generationDraft={}}=options,c=generationContext(options),d=generationDraft,stage=c.shot?'storyboard':view.stage||'style';
 const rows=tasks.filter(t=>t.entityId===c.binding?.entityId).sort((a,b)=>(Date.parse(b.createdAt)||0)-(Date.parse(a.createdAt)||0)),running=rows.find(t=>['preparing','submitting','queued','submitted','running','downloading','unknown_submission','needs_attention'].includes(t.status)&&!(t.status==='needs_attention'&&t.error?.code==='PARTIAL_DELIVERY'&&t.providerReceipt&&t.outputs?.length)),pending=rows.find(t=>t.canConfirm);
 const uploadRetry=rows[0]?.status==='failed'&&['REFERENCE_UPLOAD_FAILED','REFERENCE_PREFLIGHT_REJECTED','REFERENCE_SETUP_STOPPED'].includes(rows[0]?.error?.code);
 const source=d.sourceRevisionId?c.sources.find(r=>r.id===d.sourceRevisionId):c.sources.at(-1),made=c.versions.some(r=>r.stage===stage);
 const styleMissing=options.phase==='asset'&&(!options.project?.artDirection||options.project.artDirection.valid===false),disabled=busy||job.stale||job.status!=='ready'||(c.binding?.changed&&c.binding?.linked)||Boolean(running&&['unknown_submission','needs_attention'].includes(running.status))||styleMissing||(!c.shot&&stage!=='style'&&!source);
 const modelReady=options.imageContracts?.[c.mode.modelId]?.verified;
 const ratio=d.ratio||(stage==='asset'?assetFormats[c.asset?.category]?.ratio:null)||result.aspectRatio;
 return `${c.identity&&stage!=='style'?`<nav class="creator-identity-steps" aria-label="人物资产步骤"><button data-character-layer="master" aria-pressed="${c.master}">1 ${c.scene?'场景':'人物'}主多视图</button><span>→</span><button data-character-layer="state" aria-pressed="${!c.master}">2 剧情状态多视图</button></nav>`:''}${c.asset?bindingPicker({...options,asset:c.asset,state:c.state,changed:Boolean(options.review||options.draft)}):''}<div class="creator-state-line">${c.asset&&stage!=='style'&&!c.master?`<label>剧情状态<select data-board-generation-state>${c.asset.states.map((s,i)=>`<option value="${i}" ${s.id===c.state.id?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>`:''}<span>${esc(c.mode.model)} · ${esc(c.character&&stage==='style'?'基础人物形象':c.state?.name||'本镜')}</span>${options.phase==='asset'?`<button data-board-generation-stage="${stage==='refine'?'asset':'refine'}">${stage==='refine'?'返回规范资产':'精修已有资产'}</button>`:''}</div><div data-board-generation-gallery>${generationGallery(c.versions,apiBase,{stage,category:c.asset?.category,master:c.master,direction:!options.canvasMode&&options.phase==='style',busy:busy||c.binding?.changed||Boolean(options.review)})}</div><form data-wf-form="board-generation" class="wf-compose creator-generation">${recipePicker(options.project)}${imageModelPicker({draft:d,catalog:options.imageCatalog,contracts:options.imageContracts,loading:options.imageModelsLoading,error:options.imageModelsError,ratio})}<label>同时生成<select name="groups">${[1,2,3,4,6,8].map(n=>`<option value="${n}" ${Number(d.groups||1)===n?'selected':''}>${n} 组</option>`).join('')}</select></label>${c.shot?`<div class="board-generation-refs">${c.shot.references.map(ref=>{const ai=result.assets.findIndex(a=>a.id===ref.assetId),a=result.assets[ai];return `<button type="button" data-board-reference-open="${ai}" data-shot-id="${esc(c.shot.id)}">${esc(a?.name)} ↗</button>`;}).join('')}<button type="button" data-board-select="shots" data-board-index="${view.index}">选择参考图版本</button></div>`:stage!=='style'?`${sourceImagePicker(c.sources,d.sourceRevisionId||source?.id,apiBase,{title:stage==='refine'?'选择精修原图':c.identity&&!c.master?`选择${c.scene?'场景':'人物'}主多视图`:'选择基础形象参考'})}${stage==='asset'&&c.character?`<p class="wf-note">${c.master?'先锁定人物长相、体型与基础服装；确认后再派生剧情状态。':'此状态引用已确认的人物主多视图，只改变服装、湿度或伤情。'}</p>`:''}${source?'':`${c.identity&&!c.master&&stage==='asset'?`<p class="wf-note">请先生成并确认${c.scene?'场景':'人物'}主多视图。</p><button type="button" data-character-layer="master">去制作${c.scene?'场景':'人物'}主多视图</button>`:`<p class="wf-note">先选用这个物料的${stage==='refine'?'资产图':'形象候选图'}。</p><button type="button" data-creator-go-stage="${stage==='refine'?'asset':'style'}">${stage==='refine'?'去制作资产图':'去选基础形象'}</button>`}`}`:''}${imageReferencePicker(options)}<details><summary>调整制作要求与画幅</summary>${c.shot&&d.prompt!==undefined&&d.prompt!==c.prompt?'<p class="wf-muted">本次草稿与已保存镜头要求不同，可继续使用草稿或重新载入。</p><button type="button" data-generation-use-saved>使用已保存镜头要求</button>':''}<label>制作要求<textarea name="prompt" rows="4" maxlength="15000" required>${esc(d.prompt??c.prompt)}</textarea></label></details>${styleMissing?'<p class="wf-note">请先确认本剧统一风格。</p>':''}<button class="primary" type="submit" ${made||uploadRetry||running&&!['unknown_submission','needs_attention'].includes(running.status)||pending?'data-generation-reroll':''} ${disabled||!modelReady?'disabled':''}>${uploadRetry?'重新准备本次生成':made?(stage==='style'?'重抽一组风格候选':stage==='refine'?'重新精修此图':'重新'+c.mode.label):esc(c.mode.label)}</button><small class="wf-muted">下一步核对账号、参考与费用，再提交。</small>${c.shot?`<button type="submit" data-generation-missing-shots ${disabled||!modelReady?'disabled':''}>批量准备缺图镜头（最多 8 镜）</button><small class="wf-muted">使用上方模型参数和各镜已保存提示词；每镜一组，跳过参考未齐、已有图片或已有任务的镜头。</small><button type="submit" data-generation-repair-shots ${disabled||!modelReady?'disabled':''}>批量准备待返修镜头（最多 8 镜）</button><small class="wf-muted">仅重做最新图片已退回且原任务已完成的镜头；使用已保存要求，核对新一批清单与费用后提交。</small>`:''}</form><div data-board-generation-feedback>${rows.filter(t=>!['completed','cancelled'].includes(t.status)).map(t=>`<div class="wf-note"><b>${esc(t.modelId||t.modelKey||'生成任务')} · ${t.count||1} 张 · ${esc(t.id?.slice(-6)||'')}</b><span> ${esc(states[t.status]||t.status)}</span>${t.canConfirm?`<button data-wf-confirm-task="${esc(t.id)}">确认这一组</button>`:''}${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询这一组</button>`:''}</div>`).join('')}${pending?`<button data-wf-confirm-task="${esc(pending.id)}">继续确认已准备的生成任务</button>`:''}${running?`<p role="status">${esc(states[running.status]||'先核对原任务状态')}</p><progress aria-label="图片处理中"></progress>`:''}${rows.slice(0,1).filter(t=>t.error).map(t=>`<p class="wf-note">${esc(t.error.message)}</p>${!t.submissionAttempted&&t.status!=='cancelled'?`<button data-wf-cancel="${esc(t.id)}">取消未提交记录</button>`:''}${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询原任务</button>`:''}`).join('')}</div>`;
}
