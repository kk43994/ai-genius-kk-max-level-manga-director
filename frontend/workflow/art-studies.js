import {escapeHTML as esc,assetURL,belongsToSelection,states} from './model.js';
import {affectedRevisions,impactCards} from './in-place.js';
import {imageModelPicker} from './image-models.js';
import {PRODUCTION_TEMPLATE,placeholderIcon,analysisMaterials} from './canvas-template.js';

export const artLabels={character:'人物风格',scene:'场景风格',trial:'人物入景试镜',standard:'确认美术标准'};
export function artModel(role,catalog){
 return role!=='trial'?(catalog?.items||[]).find(m=>/\bmj\b|midjourney/i.test(m.name+' '+m.id)):null;
}
export function studyPrompt(role,analysis,subjectId){
 const rows=analysisMaterials(analysis||{}),item=rows.find(r=>r.id===subjectId)||rows.find(r=>r.category===(role==='scene'?'scene':'character'));
 const subject=item?`${item.name}。${item.description||'原文未明确的外观由本次试做探索。'}`:'请填写本次试做的人物或场景设定。';
 return role==='trial'?'让选定的人物自然站在选定的场景中。保持人物长相与服装、场景空间结构，统一人物与环境的画风、色彩、材质和光照。完整展示人物与周围环境，供全剧美术标准试镜。':role==='scene'?`探索全剧场景的美术方向。试做对象：${subject}\n清楚展示场景空间、建筑、材质、色彩与光照。不出现人物，不添加文字。此图用于选择场景画风。`:`探索全剧人物的美术方向。试做对象：${subject}\n一位人物，基础服装，中性站姿，五官和体态清楚，简洁背景。不带剧情伤情或动作，不添加文字。此图用于选择人物画风；其他人物只继承画风，不复制此人的脸。`;
}
export function artRevisions({assets,selection,project,role,existing=false}){
 const entityId=project.artStudies?.[role]?.entityId;
 return assets.filter(a=>a.active&&(existing?a.category===(role==='scene'?'scene':'character'):a.entityId===entityId))
   .flatMap(a=>(a.revisions||[]).map(r=>({...r,name:a.name})))
   .filter(r=>r.stage==='style'&&r.status==='ready'&&belongsToSelection(r,selection));
}
export function resolvedArtSamples(bundle,project,assets){
 const all=assets.flatMap(a=>a.revisions||[]),ids={...(project.artDirection?.samples||{}),...(bundle.samples||{})};
 return Object.fromEntries(Object.entries(ids).map(([role,item])=>[role,all.find(r=>r.id===item.revisionId&&r.sha256===item.sha256&&r.status==='ready'&&r.review==='approved')]).filter(([,r])=>r));
}
export function artStudiesPanel(o){
 const {role,project,assets,apiBase,selection,busy,draft={},bundle={},catalog,contracts,loading,error,analysis,tasks=[]}=o;
 const samples=resolvedArtSamples(bundle,project,assets),all=assets.flatMap(a=>a.revisions||[]);
 const thumb=(key)=>samples[key]?`<img src="${esc(assetURL(apiBase,samples[key].assetId,samples[key].id,true))}" alt="已选${artLabels[key]}">`:`<span class="pipeline-placeholder">${placeholderIcon(key)}</span>`;
 const tabs=`<nav class="art-tabs" aria-label="美术试做步骤">${Object.entries(artLabels).map(([key,title])=>`<button type="button" data-canvas-art="${key}" aria-pressed="${role===key}">${title}${samples[key]?' ✓':''}</button>`).join('')}</nav>`;
 const tile=(r)=>`<figure class="creator-candidate" data-selected="${samples[role]?.id===r.id}"><div class="creator-candidate-media"><button type="button" class="creator-candidate-pick" data-art-pick="${esc(r.id)}" data-art-role="${role}" aria-label="选为${artLabels[role]}样板 ${esc(r.id.slice(-6))}" aria-pressed="${samples[role]?.id===r.id}" ${busy?'disabled':''}><img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="${esc(r.name)}候选图"><span class="creator-candidate-choice">${samples[role]?.id===r.id?'✓ 已选样板':'点击选为样板'}</span></button><button class="creator-candidate-preview" type="button" data-wf-review="${esc(r.id)}" aria-label="放大查看样板 ${esc(r.id.slice(-6))}">⛶</button></div><figcaption>${esc(r.modelLabel||'风格候选')} · ${esc(r.id.slice(-6))}</figcaption></figure>`;
 if(role==='standard'){
  const legacy=project.artDirection&&!project.artDirection.samples?all.find(r=>r.id===project.artDirection.revisionId):null;
  const legacyPanel=legacy?`<section class="wf-panel"><h4>原单图美术标准 · 第 ${project.artDirection.version} 版</h4><button type="button" data-wf-review="${esc(legacy.id)}" aria-label="核对原美术参考图"><img style="max-width:240px;max-height:220px;object-fit:contain" src="${esc(assetURL(apiBase,legacy.assetId,legacy.id,true))}" alt="原美术参考图"></button><p>${project.artDirection.valid?'原标准仍可继续制作。':'原参考图已改选或失效。点击原图核对版本；选回仍适用的原图后，可以继续使用原标准。'}</p><p class="wf-muted">补齐下方三项试做并确认，才会建立新标准；不会自动替换旧标准。</p></section>`:'';
  const complete=['character','scene','trial'].every(k=>samples[k]),matched=complete&&['character','scene'].every(k=>samples.trial.sourceRevisionIds?.includes(samples[k].id));
  const affected=all.filter(r=>r.artDirectionVersion===project.artDirection?.version&&r.stage!=='style').length;
  return tabs+legacyPanel+`<div class="art-standard-samples">${PRODUCTION_TEMPLATE.artSlots.map(([key,title])=>`<button data-canvas-art="${key}">${thumb(key)}<strong>${title}</strong><small>${samples[key]?'已选定':'待试做并选用'}</small></button>`).join('')}</div>${project.artDirection?`<p class="wf-note">当前使用第 ${project.artDirection.version} 版美术标准。更新后 ${affected} 张旧标准图片需要核对；原图和已准备任务仍保留。</p>`:''}<form data-wf-form="art-standard" class="wf-compose"><label>全剧美术规范<textarea name="notes" rows="4" maxlength="4000" required placeholder="只写统一的画风、人物比例、线条、材质、配色与光照。各角色的长相在各自档案中确定。">${esc(bundle.notes??project.artDirection?.notes??'')}</textarea></label>${!matched?`<p class="wf-note">${complete?'样板已更换，请用当前人物和场景重新试镜。':'先选好人物、场景和入景试镜三张样板。'}</p>`:''}<button class="primary" ${busy||!matched?'disabled':''}>确认这套全剧美术标准</button></form>${project.artDirection?`<details><summary>查看更新美术标准的影响范围</summary>${impactCards(affectedRevisions(assets,[],{styleVersion:project.artDirection.version}),apiBase)}</details>`:''}${project.artDirection?'<details><summary>已确认版本的制作依据</summary><p>图片版本、原始提示词、参数与模型标签随标准一起保存，后续制作分别继承画风和主体身份。</p></details>':''}`;
 }
 const revisions=artRevisions({...o,role}),existing=role==='trial'?[]:artRevisions({...o,role,existing:true}).filter(r=>!revisions.some(v=>v.id===r.id));
 const entityId=project.artStudies?.[role]?.entityId,ownTasks=tasks.filter(t=>t.entityId===entityId),unresolved=ownTasks.some(t=>['unknown_submission','needs_attention'].includes(t.status));
 const subjects=analysisMaterials(analysis||{}).filter(r=>r.category===(role==='scene'?'scene':'character'));
 return tabs+`<p class="wf-muted">${role==='trial'?'用当前两张样板少量试做，核对人物与环境能否融合。':'生成候选后，点图选定本剧的风格样板。'}</p>${role==='trial'?`<div class="art-trial-inputs">${['character','scene'].map(k=>`<button data-canvas-art="${k}">${thumb(k)}<span>${samples[k]?'更换':'先选'}${artLabels[k]}</span></button>`).join('')}</div>`:''}<div class="board-generation-gallery" data-art-gallery>${revisions.slice().reverse().map(tile).join('')||'<p class="wf-empty">生成后在这里比较和选用。</p>'}</div>${existing.length?`<details><summary>从本剧已有候选中选样板（${existing.length}）</summary><div class="board-generation-gallery">${existing.slice().reverse().map(tile).join('')}</div></details>`:''}<form data-wf-form="art-generation" class="wf-compose creator-generation">${imageModelPicker({draft,catalog,contracts,loading,error,ratio:role==='character'?'2:3':'16:9'})}${role!=='trial'&&subjects.length?`<label>试做对象<select name="subjectId" data-art-subject>${subjects.map(r=>`<option value="${esc(r.id)}" ${draft.subjectId===r.id?'selected':''}>${esc(r.name)}</option>`).join('')}</select></label>`:''}<label>生成组数<select name="groups">${[1,2,3,4,6,8].map(n=>`<option ${Number(draft.groups||1)===n?'selected':''}>${n}</option>`).join('')}</select></label><details><summary>调整本次试做要求</summary><label>制作要求<textarea name="prompt" rows="5" maxlength="15000" required>${esc(draft.prompt??studyPrompt(role,analysis,draft.subjectId))}</textarea></label></details><button type="submit" class="primary" ${revisions.length?'data-art-reroll':''} ${busy||unresolved||!contracts?.[draft.modelId]?.verified||role==='trial'&&(!samples.character||!samples.scene)?'disabled':''}>${revisions.length?'重抽':'生成'}${artLabels[role]}候选</button><small class="wf-muted">先核对参考与费用，再提交生成。</small></form><div data-art-feedback>${ownTasks.filter(t=>!['completed','cancelled'].includes(t.status)).map(t=>`<p class="wf-note">${esc(states[t.status]||t.status)} · ${esc(t.id.slice(-6))}${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询原任务</button>`:''}${t.canConfirm?`<button data-wf-confirm-task="${esc(t.id)}">继续确认这一组</button>`:''}${t.error?`<span>${esc(t.error.message)}</span>`:''}${!t.submissionAttempted&&!['preparing','completed','cancelled'].includes(t.status)?`<button data-wf-cancel="${esc(t.id)}">取消未提交记录</button>`:''}</p>`).join('')}</div><button type="button" data-canvas-art="${role==='character'?'scene':role==='scene'?'trial':'standard'}">${role==='character'?'去试场景风格':role==='scene'?'去做入景试镜':'核对全剧美术标准'} →</button>`;
}
