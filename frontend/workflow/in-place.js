import {currentTaskFeedback,isTaskFailure,taskFailureReason} from './task-feedback.js';
import {escapeHTML as esc,assetURL,belongsToSelection,states} from './model.js';
import {field} from './production-editor.js';
import {referenceCards,dialogueText} from './production.js';
import {referenceField} from './production-references.js';
import {shotStructureControls,removedShotControls} from './shot-structure.js';
import {dialogueEditor} from './dialogue-editor.js';
import {imageChoice} from './image-choices.js';

export const shotNumber=i=>String(i+1).padStart(3,'0');
export function rememberedSettings(input={}) {
  // Only rendering preferences travel between objects. Never carry content,
  // references, seeds, ownership or a previous paid request identity with them.
  const keys=['modelId','groups','param:ratio','param:aspectRatio','param:count','param:resolution','param:quality'];
  return Object.fromEntries(keys.filter(k=>input[k]!==undefined).map(k=>[k,input[k]]));
}
export function uniqueReferencePins(job,result,assets,selection,shot) {
  const cards=referenceCards({...job,result},shot,assets,selection,'/api/v1');
  return shot.references.map((ref,i)=>!ref.revisionId&&cards[i]?.versions.length===1?{...ref,revisionId:cards[i].versions[0].id}:{...ref});
}
export function addSharedDirection(result,ids,note) {
  if(!note.trim()||!ids.length)throw Error('先选镜头并填写共同修改要求。');
  const selected=new Set(ids);if(selected.size!==ids.length||ids.some(id=>!result.shots.some(s=>s.id===id)))throw Error('所选镜头已变化，请重新选择。');
  const next=structuredClone(result);
  for(const shot of next.shots)if(selected.has(shot.id)){
    const value=shot.imagePrompt+'\n本次共同调整：'+note.trim();
    if(value.length>3000)throw Error('镜头要求超过容量，请缩短共同要求或先精简原要求。');
    shot.imagePrompt=value;
  }
  return next;
}
export function affectedRevisions(assets,seedIds,{styleVersion}={}) {
  const all=assets.filter(a=>a.active).flatMap(a=>a.revisions.map(r=>({...r,name:a.name}))),ids=new Set(seedIds),found=[];
  let changed=true;
  while(changed){changed=false;for(const r of all){
    if(ids.has(r.id))continue;
    if((r.sourceRevisionIds||[]).some(id=>ids.has(id))||(styleVersion!==undefined&&r.artDirectionVersion===styleVersion&&r.stage!=='style')){
      ids.add(r.id);found.push(r);changed=true;
    }
  }}
  return found;
}
export function impactCards(rows,apiBase){
  if(!rows.length)return '<p class="wf-muted">没有发现依赖此版本的已生成图片。</p>';
  return `<p>${new Set(rows.map(r=>r.entityId)).size} 个制作对象 · ${rows.length} 张关联图片需要核对，原图保留。</p><div class="quick-impact-grid">${rows.map(r=>`<button type="button" data-wf-review="${esc(r.id)}"><img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="${esc(r.name)}" loading="lazy"><span>${esc(r.name)}</span></button>`).join('')}</div>`;
}
export function compactTasks(tasks){
  return currentTaskFeedback(tasks).map(t=>isTaskFailure(t)?`<article class="quick-task" data-quick-task="${esc(t.id)}" data-current-failure><strong>本次生成失败</strong><p>原因：${esc(taskFailureReason(t))}</p>${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询原任务</button>`:''}</article>`:`<article class="quick-task" data-quick-task="${esc(t.id)}"><strong>${esc(states[t.status]||t.status)}</strong>${t.error?`<p>${esc(t.error.message)}</p>`:''}<div>${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询原任务</button>`:''}${t.canConfirm?`<button data-wf-confirm-task="${esc(t.id)}">核对并提交</button>`:''}${!t.submissionAttempted&&!['preparing','submitting'].includes(t.status)?`<button data-wf-cancel="${esc(t.id)}">取消未提交记录</button>`:''}</div></article>`).join('');
}
export function quickShotPanel(o){
 const {result,job,index,assets,selection,apiBase,rows,refIndex=null,busy}=o,shot=result.shots[index];if(!shot)return removedShotControls(result);
 const cards=referenceCards({...job,result},shot,assets,selection,apiBase),path=`shots.${index}`;
 const frame=r=>{const image=r?.revision||r?.historyRevision;return image?`<img src="${esc(assetURL(apiBase,image.assetId,image.id,true))}" alt="${r.revision?'':'历史'}镜头 ${shotNumber(r.index)}">${!r.revision?'<small>原图 · 待核对</small>':''}`:'<span class="quick-frame-empty">画面待补</span>';};
 const row=rows.find(r=>r.shot.id===shot.id),pins=uniqueReferencePins(job,result,assets,selection,shot),pinCount=pins.filter((p,i)=>p.revisionId&&!shot.references[i].revisionId).length;
 const refs=cards.map((c,ri)=>`<article class="quick-reference"><button type="button" data-quick-reference="${ri}" aria-expanded="${refIndex===ri}">${c.src||c.historySrc?`<img src="${esc(c.src||c.historySrc)}" alt="${esc(c.name)}">`:'<span class="quick-frame-empty">待补图</span>'}<b>${esc(c.name)}</b><small>${c.pinned?(c.src?'已固定版本':'原版本待核对'):c.versions.length===1?'可固定当前已选图':c.versions.length>1?'请选择版本':'待制作 / 选用'}</small></button><button data-quick-supplement="${ri}">${c.src?'调整素材':c.historySrc?'核对素材':'补齐素材'}</button></article>`).join('');
 const ref=shot.references[refIndex],asset=result.assets.find(a=>a.id===ref?.assetId),card=cards[refIndex];
 const chooser=card?`<section class="quick-reference-picker"><div class="wf-section-title"><h4>${esc(card.name)}</h4><button data-quick-reference-close>收起</button></div><label>剧情状态<select data-reference-state-change="${refIndex}" data-reference-shot="${index}">${(asset?.states||[]).filter(s=>s.sceneIds.includes(shot.sceneId)).map(s=>`<option value="${esc(s.id)}" ${s.id===ref.stateId?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label><div class="image-choice-grid">${card.versions.map(r=>imageChoice({src:assetURL(apiBase,r.assetId,r.id,true),name:r.modelLabel||'已选素材',caption:r.id.slice(-6),selected:r.id===ref.revisionId,previewId:r.id,choose:'用于本镜',action:{'data-quick-pin':r.id,'data-quick-ref-index':refIndex}})).join('')||'<p>尚无符合当前制作依据的已选版本。已有原图仍保留，可以核对素材或美术标准。</p>'}</div></section>`:'';
 return `${shotStructureControls(result,index)}${removedShotControls(result)}<div class="quick-shot-nav"><button data-quick-shot="${index-1}" ${index===0?'disabled':''} aria-label="上一镜">← 上一镜</button><span>镜头 ${shotNumber(index)} / ${result.shots.length}</span><button data-quick-shot="${index+1}" ${index>=result.shots.length-1?'disabled':''} aria-label="下一镜">下一镜 →</button></div><div class="quick-continuity-strip" aria-label="前后镜头连续性">${[index-1,index,index+1].filter(i=>result.shots[i]).map(i=>{const r=rows.find(r=>r.shot.id===result.shots[i].id);return `<button data-quick-shot="${i}" aria-pressed="${i===index}">${frame(r)}<span>${i===index?'当前':i<index?'上一镜':'下一镜'} · ${shotNumber(i)}</span></button>`;}).join('')}</div><div class="quick-shot-content"><div class="quick-shot-image" data-quick-shot-media>${(row?.revision||row?.historyRevision)?`<button data-image-tools="${esc((row.revision||row.historyRevision).id)}" aria-label="修改镜头 ${shotNumber(index)} 图片">${frame(row)}<span>点击图片调整</span></button>`:`<div class="quick-frame-empty">${row?.historyRevisionId?'制作依据已变化，可查看原版本':'画面待补'}</div>`}<div class="wf-actions"><button data-quick-generate="${index}">${row?.revision?'生成新版本':'生成分镜图'}</button>${row?.historyRevisionId?`<button data-wf-review="${esc(row.historyRevisionId)}">所有版本</button>`:''}</div>${row?.task?compactTasks([row.task]):''}</div>
 <div class="quick-shot-fields">${field('镜头目的',path+'.purpose',shot.purpose,{rows:1,max:400})}${referenceField('画面与动作',path+'.beat',shot,result,800)}${field('画面构图',path+'.framing',shot.framing,{rows:2,max:500})}${dialogueEditor(job,shot,index)}<section><div class="wf-section-title"><h4>本镜参考</h4>${pinCount?`<button data-quick-pin-all>固定 ${pinCount} 张明确参考</button>`:''}</div><div class="quick-reference-strip">${refs}</div>${chooser}</section><details><summary>首尾状态、完整提示词与原文疑点</summary>${field('开始状态',path+'.startState',shot.startState)}${field('结束状态',path+'.endState',shot.endState)}${referenceField('分镜图要求',path+'.imagePrompt',shot,result,3000)}${(job.validationIssues||[]).filter(i=>i.path.startsWith(path+'.')).map(i=>`<p class="wf-note wf-error">${esc(i.message)}${i.sourceText?'<br>原文：'+esc(i.sourceText):''}</p>`).join('')}<button data-quick-full-editor="${index}">展开完整镜头与原文编辑</button></details></div></div><footer class="canvas-drawer-footer quick-shot-footer"><span data-wf-production-draft-status>${o.dirty?'修改待保存':'已保存到项目'}</span><div class="wf-actions">${o.dirty?'<button data-wf-action="production-review-discard">恢复上次保存的方案</button>':''}<button data-wf-action="production-review-save" ${busy||job.stale?'disabled':''}>保存修改</button><button class="primary" data-quick-save-generate="${index}" ${busy||job.stale?'disabled':''}>保存并准备生成</button></div></footer>`;
}
export function sharedDirectionPanel({result,selected,note='',busy}){
 const ids=new Set(selected),rows=result.shots.map((s,index)=>({s,index})).filter(r=>ids.has(r.s.id));
 return `<form data-wf-form="shared-direction"><p>给所选镜头补充共同画面要求；原有剧情、人物和参考保留。</p><label>共同修改要求<textarea name="note" rows="4" maxlength="1500" required placeholder="例如：统一为冷蓝色夜景，保留各镜人物、动作和构图。">${esc(note)}</textarea></label><details open><summary>影响范围 · ${rows.length} 镜</summary>${rows.map(({s,index})=>`<article><strong>镜头 ${shotNumber(index)} · ${esc(s.purpose)}</strong><p>${esc(s.imagePrompt)}</p></article>`).join('')}</details><button type="submit" class="primary" ${busy||!rows.length?'disabled':''}>将共同要求加入这 ${rows.length} 镜草稿</button><small>下一步保存并核对，可再选择本批要生成的镜头。不会自动收费重抽。</small></form>`;
}
