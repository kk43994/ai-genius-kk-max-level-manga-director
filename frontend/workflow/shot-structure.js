// User-invoked editing only: keep original dialogue IDs and stable first shot.
export const numberShots = shots => shots.map((shot,index)=>({...shot,order:index+1}));
export function removeBlankShot(result,index){
 const next=structuredClone(result),shot=next.shots[index];
 if(!shot||shot.dialogueIds.length||shot.purpose!=='补充镜头 · 请编辑动作与构图')return next;
 next.shots=numberShots(next.shots.filter((_,i)=>i!==index));return next;
}
export function dialogueSeconds(dialogues, ids){
 const text=ids.map(id=>dialogues.find(d=>d.id===id)?.text||'').join('');
 return Math.max(3,Math.ceil(text.replace(/[\s\p{P}]/gu,'').length/4+1.5));
}
export function splitShot(result,index,dialogues,newId){
 const next=structuredClone(result),shot=next.shots[index];
 if(!shot||shot.dialogueIds.length<2)return next;
 const parts=shot.dialogueIds.map((id,n)=>({...structuredClone(shot),id:n?newId():shot.id,
   purpose:(shot.purpose+` · 台词段 ${n+1}`).slice(0,400),dialogueIds:[id],
   durationSeconds:Math.min(60,dialogueSeconds(dialogues,[id]))}));
 next.shots.splice(index,1,...parts);next.shots=numberShots(next.shots);return next;
}
export function addShot(result,index,newId){
 const next=structuredClone(result),shot=next.shots[index];if(!shot)return next;
 next.shots.splice(index+1,0,{...structuredClone(shot),id:newId(),purpose:'补充镜头 · 请编辑动作与构图',dialogueIds:[],durationSeconds:4});
 next.shots=numberShots(next.shots);return next;
}
