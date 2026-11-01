// Each group retains its own receipt. A rejection never cancels sibling reads
// and never invents a new key for an uncertain submission.
import {belongsToSelection} from './model.js';

export function missingStoryboardShots({job,result,assets=[],tasks=[],selection},referenceCards){
 if(!job||job.stale||job.status!=='ready')return [];
 return result.shots.flatMap((shot,index)=>{
  const binding=(job.shotBindings||[]).find(b=>b.shotId===shot.id);
  // Existing tasks (including failed/unknown) must be dealt with individually.
  // A bulk click must never silently redraw or retry a paid submission.
  if(binding?.changed||tasks.some(t=>t.entityId===binding?.entityId&&t.status!=='cancelled'))return [];
  const library=assets.find(a=>a.active&&a.entityId===binding?.entityId);
  if(library?.revisions.some(r=>r.stage==='storyboard'&&belongsToSelection(r,job.ownership||selection)))return [];
  const refs=referenceCards({...job,result},shot,assets,selection,'/api/v1');
  return refs.length&&refs.every(r=>r.pinned&&r.src&&!r.changed)?[{shot,index}]:[];
 }).slice(0,8);
}

export function batchSize(value){
 const n=Number(value||1);
 if(!Number.isInteger(n)||n<1||n>8)throw new Error('每批请选择 1 至 8 组。');
 return n;
}
export async function parallelGroups(items,action,limit=3){
 const results=new Array(items.length);let next=0;
 await Promise.all(Array.from({length:Math.min(limit,items.length)},async()=>{
  while(next<items.length){const i=next++;try{results[i]={status:'fulfilled',value:await action(items[i],i)};}catch(reason){results[i]={status:'rejected',reason};}}
 }));
 return results;
}
