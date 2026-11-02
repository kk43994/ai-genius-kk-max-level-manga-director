import {escapeHTML as esc} from './model.js';

export const dialogueKinds={dialogue:'对白',inner_monologue:'内心独白',narration:'旁白',voiceover:'画外音',offscreen:'画外对白',system_voice:'系统音',unknown:'待确认'};
export function dialogueLines(job,shot,{includeDeleted=false}={}){
 const names=new Map((job.characters||[]).map(c=>[c.id,c.name]));
 const rows=(shot.dialogueIds||[]).map(id=>{
  const source=(job.dialogues||[]).find(d=>d.id===id);if(!source)return null;
  const edit=shot.dialogueOverrides?.find(d=>d.id===id&&d.origin==='manual');
  return {...source,...edit,sourceText:source.text,sourceSpeakerId:source.speakerId,sourceSpeakerLabel:source.speakerLabel,sourceKind:source.kind,edited:Boolean(edit)};
 }).filter(Boolean).concat((shot.dialogueAdditions||[]).filter(d=>d.origin==='manual').map(d=>({...d,added:true,edited:true})));
 const order=shot.dialogueOrder||rows.map(d=>d.id),rank=new Map(order.map((id,i)=>[id,i]));
 return rows.filter(d=>includeDeleted||!d.deleted).sort((a,b)=>(rank.get(a.id)??999)-(rank.get(b.id)??999)).map(d=>({...d,label:`${names.get(d.speakerId)||d.speakerLabel||'未署名'} · ${dialogueKinds[d.kind]||'待确认'}`,sourceLabel:d.added?'人工新增':`${names.get(d.sourceSpeakerId)||d.sourceSpeakerLabel||'未署名'} · ${dialogueKinds[d.sourceKind]||'待确认'}`}));
}
export function editDialogue(job,shot,id,patch){
 const next=structuredClone(shot),keys=['text','speakerId','speakerLabel','kind','deleted'];
 const safe=Object.fromEntries(Object.entries(patch).filter(([k])=>keys.includes(k)));
 const addition=next.dialogueAdditions?.find(d=>d.id===id);
 if(addition){Object.assign(addition,safe);return next;}
 const source=(job.dialogues||[]).find(d=>d.id===id);if(!source||!next.dialogueIds.includes(id))return next;
 const old=next.dialogueOverrides?.find(d=>d.id===id)||{},merged={id,text:source.text,origin:'manual',...old,...safe};
 const changed=keys.some(k=>k==='deleted'?Boolean(merged.deleted):Object.hasOwn(merged,k)&&merged[k]!==source[k]);
 const rows=(next.dialogueOverrides||[]).filter(d=>d.id!==id);if(changed)rows.push(merged);
 if(rows.length)next.dialogueOverrides=rows;else delete next.dialogueOverrides;
 return next;
}
export function restoreDialogue(shot,id){
 const next=structuredClone(shot),added=next.dialogueAdditions?.find(d=>d.id===id);
 if(added){delete added.deleted;return next;}
 const rows=(next.dialogueOverrides||[]).filter(d=>d.id!==id);if(rows.length)next.dialogueOverrides=rows;else delete next.dialogueOverrides;return next;
}
export function addDialogue(shot,id){
 const next=structuredClone(shot);next.dialogueAdditions=[...(next.dialogueAdditions||[]),{id,text:'',speakerId:null,speakerLabel:'',kind:'dialogue',origin:'manual'}];
 if(next.dialogueOrder)next.dialogueOrder.push(id);return next;
}
export function moveDialogue(job,shot,id,delta){
 const next=structuredClone(shot),all=dialogueLines(job,shot,{includeDeleted:true}),ids=all.filter(d=>!d.deleted).map(d=>d.id),index=ids.indexOf(id),to=index+delta;
 if(index<0||to<0||to>=ids.length)return next;[ids[index],ids[to]]=[ids[to],ids[index]];next.dialogueOrder=[...ids,...all.filter(d=>d.deleted).map(d=>d.id)];return next;
}
export function dialogueEditor(job,shot,index){
 const all=dialogueLines(job,shot,{includeDeleted:true}),lines=all.filter(d=>!d.deleted),deleted=all.filter(d=>d.deleted);
 const attr=d=>`data-quick-dialogue="${esc(d.id)}" data-quick-shot-index="${index}"`;
 return `<section class="quick-dialogues"><div class="wf-section-title"><h4>角色台词</h4><button type="button" data-quick-dialogue-add="${index}">＋ 添加台词</button></div>${lines.map((d,i)=>`<article class="quick-dialogue-row" data-dialogue-row="${esc(d.id)}"><div class="quick-dialogue-meta"><label>说话人<select ${attr(d)} data-dialogue-field="speakerId" aria-label="第 ${i+1} 句说话人"><option value="" ${!d.speakerId?'selected':''}>自填 / 未署名</option>${(job.characters||[]).map(c=>`<option value="${esc(c.id)}" ${c.id===d.speakerId?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><label>台词类型<select ${attr(d)} data-dialogue-field="kind" aria-label="第 ${i+1} 句台词类型">${Object.entries(dialogueKinds).map(([key,label])=>`<option value="${key}" ${key===d.kind?'selected':''}>${label}</option>`).join('')}</select></label></div>${!d.speakerId?`<label>说话人名称<input ${attr(d)} data-dialogue-field="speakerLabel" maxlength="100" value="${esc(d.speakerLabel||'')}" placeholder="可填写新角色名、旁白或系统"></label>`:''}<label class="sr-only" for="dialogue-text-${esc(d.id)}">第 ${i+1} 句台词内容</label><textarea id="dialogue-text-${esc(d.id)}" rows="3" maxlength="4000" ${attr(d)} data-dialogue-field="text" aria-label="第 ${i+1} 句台词内容">${esc(d.text)}</textarea><div class="quick-dialogue-actions"><span>${d.added?'人工新增':d.edited?'已人工修改':'剧本台词'}</span><button type="button" data-dialogue-move="${esc(d.id)}" data-dialogue-delta="-1" data-quick-shot-index="${index}" ${i===0?'disabled':''} aria-label="上移第 ${i+1} 句">↑</button><button type="button" data-dialogue-move="${esc(d.id)}" data-dialogue-delta="1" data-quick-shot-index="${index}" ${i===lines.length-1?'disabled':''} aria-label="下移第 ${i+1} 句">↓</button><button type="button" data-dialogue-delete="${esc(d.id)}" data-quick-shot-index="${index}" aria-label="删除第 ${i+1} 句台词">删除</button></div>${!d.added?`<details><summary>查看原句与识别结果</summary><p>${esc(d.sourceLabel)}<br>${esc(d.sourceText)}</p>${d.edited?`<button type="button" data-quick-dialogue-reset="${esc(d.id)}" data-quick-shot-index="${index}">恢复这一句</button>`:''}</details>`:''}</article>`).join('')||'<p class="wf-muted">本镜暂无台词，可以添加。</p>'}${deleted.length?`<details class="quick-deleted-dialogues"><summary>已删除 ${deleted.length} 句 · 可恢复</summary>${deleted.map(d=>`<p>${esc(d.label)}：${esc(d.text)} <button type="button" data-dialogue-undelete="${esc(d.id)}" data-quick-shot-index="${index}">恢复台词</button></p>`).join('')}</details>`:''}</section>`;
}
