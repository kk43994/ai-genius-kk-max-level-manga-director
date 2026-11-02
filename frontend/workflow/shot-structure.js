import {escapeHTML as esc} from './model.js';
import {dialogueLines} from './dialogue-editor.js';
// User-invoked editing only: keep original dialogue IDs and stable first shot.
export const numberShots = shots => shots.map((shot,index)=>({...shot,order:index+1}));
export function removeBlankShot(result,index){
 const next=structuredClone(result),shot=next.shots[index];
 if(!shot||shot.dialogueIds.length||shot.dialogueAdditions?.some(d=>!d.deleted)||shot.purpose!=='补充镜头 · 请编辑动作与构图')return next;
 next.shots=numberShots(next.shots.filter((_,i)=>i!==index));return next;
}
export function removeShot(result,index){
 const next=structuredClone(result),shot=next.shots[index];if(!shot)return next;
 next.shotOrder=next.shotOrder||next.shots.map(s=>s.id);next.removedShots=[...(next.removedShots||[]),shot];next.shots.splice(index,1);next.shots=numberShots(next.shots);return next;
}
export function restoreShot(result,id){
 const next=structuredClone(result),shot=next.removedShots?.find(s=>s.id===id);if(!shot)return next;
 next.shots.push(shot);const ranks=new Map((next.shotOrder||[]).map((id,i)=>[id,i]));next.shots.sort((a,b)=>(ranks.get(a.id)??a.order)-(ranks.get(b.id)??b.order));
 next.shots=numberShots(next.shots);next.removedShots=next.removedShots.filter(s=>s.id!==id);if(!next.removedShots.length){delete next.removedShots;delete next.shotOrder;}return next;
}
export function shotStructureControls(result,index){
 return `<div class="wf-actions"><button data-shot-add="${index}">＋ 添加镜头</button><button data-shot-remove="${index}">删除本镜</button></div>`;
}
export function dialogueSeconds(dialogues, ids){
 const text=ids.map(id=>dialogues.find(d=>d.id===id)?.text||'').join('');
 return Math.max(3,Math.ceil(text.replace(/[\s\p{P}]/gu,'').length/4+1.5));
}
export function splitShot(result,index,dialogues,newId){
 const next=structuredClone(result),shot=next.shots[index];
 if(!shot)return next;const lines=dialogueLines({dialogues},shot);if(lines.length<2)return next;
 const sourceIds=new Set(shot.dialogueIds),parts=lines.map((line,n)=>({...structuredClone(shot),id:n?newId():shot.id,
   purpose:(shot.purpose+` · 台词段 ${n+1}`).slice(0,400),dialogueIds:sourceIds.has(line.id)?[line.id]:[],
   dialogueOverrides:(shot.dialogueOverrides||[]).filter(d=>d.id===line.id),
   dialogueAdditions:(shot.dialogueAdditions||[]).filter(d=>d.id===line.id),
   durationSeconds:Math.min(60,dialogueSeconds([line],[line.id]))}));
 for(const part of parts)delete part.dialogueOrder;
 const removedSources=(shot.dialogueOverrides||[]).filter(d=>d.deleted);
 parts[0].dialogueIds.push(...removedSources.map(d=>d.id));parts[0].dialogueOverrides.push(...removedSources);
 parts[0].dialogueAdditions.push(...(shot.dialogueAdditions||[]).filter(d=>d.deleted));
 if(next.shotOrder)next.shotOrder.splice(next.shotOrder.indexOf(shot.id),1,...parts.map(s=>s.id));
 next.shots.splice(index,1,...parts);next.shots=numberShots(next.shots);return next;
}
export function addShot(result,index,newId){
 const next=structuredClone(result),shot=next.shots[index];if(!shot)return next;
 next.shots.splice(index+1,0,{...structuredClone(shot),id:newId(),purpose:'补充镜头 · 请编辑动作与构图',dialogueIds:[],dialogueOverrides:[],dialogueAdditions:[],dialogueOrder:[],durationSeconds:4});
 if(next.shotOrder)next.shotOrder.splice(next.shotOrder.indexOf(shot.id)+1,0,next.shots[index+1].id);
 next.shots=numberShots(next.shots);return next;
}

export function removedShotControls(result){
 return result.removedShots?.length?`<details class="removed-shots"><summary>已删除 ${result.removedShots.length} 镜 · 可恢复</summary>${result.removedShots.map(s=>`<p>原镜头 ${s.order} <button data-shot-restore="${esc(s.id)}">恢复镜头</button></p>`).join('')}</details>`:'';
}
