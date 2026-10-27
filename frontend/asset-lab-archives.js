// Archive membership comes from entity identity and explicit cleanup lineage.
// Names are display labels, never cross-project merge keys.
const categories = new Set(['character','scene','prop','effect']);
const imageFile = file => typeof file==='string' && /\.(png|jpe?g|webp)$/i.test(file) && !file.includes('..') && !/^[\\/]|:/.test(file);
export function buildArchives(tasks=[], jobs=[], plans=[]){
 const taskMap=new Map(tasks.map(t=>[t.id,t])), jobMap=new Map(jobs.map(j=>[j.id,j]));
 const files=new Map();
 for(const t of tasks)if(t.generated&&imageFile(t.file)&&!files.has(t.file))files.set(t.file,t);
 const planEntity=(scope,id)=>plans.find(p=>p.scriptId===scope)?.entities?.find(e=>e.id===id);
 function identity(t,seen=new Set()){
  const c=t.catalog||{},j=jobMap.get(t.workflowJobId),scope=t.workflowScope||j?.scope;
  const category=c.category||t.entity,id=c.entityId||j?.entityId;
  if(!categories.has(category)||!id)return null;
  const definition=scope&&planEntity(scope,id);
  const own={key:JSON.stringify([scope?'script':'series',scope||c.seriesId||'legacy',category,id]),
   entityId:id,name:definition?.name||c.entityName||t.title||id,category,scope:scope||null,
   series:c.seriesTitle||'历史项目',description:definition?.description||'',variant:definition?.variant||''};
  if(scope||seen.has(t.id))return own;
  const plan=taskMap.get(t.sourceTarget),isClean=t.phase==='refine'||plan?.phase==='refine'||/clean|refin/.test(c.kind||'');
  const refs=plan?.referenceFiles;
  if(isClean&&refs?.length===1){
   const parent=files.get(refs[0]),pc=parent?.catalog;
   if(parent&&pc?.category===category&&pc.seriesId===c.seriesId&&!parent.workflowScope){
    const next=new Set(seen);next.add(t.id);return identity(parent,next)||own;
   }
  }
  return own;
 }
 const images=new Map();
 tasks.forEach((t,index)=>{
  if(!imageFile(t.file)||t.humanReview==='not_generated'||t.generationPlan||(!t.generated&&t.humanReview!=='approved'))return;
  const j=jobMap.get(t.workflowJobId);
  images.set(t.id,{...t,thumbId:t.id,sourceId:t.id,order:index,stale:!!(t.staleInput||j?.stale),job:j,
   stage:t.phase==='style'?'style':t.phase==='refine'||/clean|refin/.test(t.catalog?.kind||'')?'clean':'asset'});
 });
 for(const j of jobs){
  if(j.kind!=='image')continue;
  for(const [index,o] of (j.outputs||[]).entries()){
   if(!imageFile(o.file))continue;
   const id='result-'+o.id,existing=images.get(id),definition=planEntity(j.scope,j.entityId);
   images.set(id,{...existing,id,title:j.title,file:o.file,generated:true,humanReview:o.review,thumbId:o.id,
    sourceId:taskMap.has(id)?id:null,workflowJobId:j.id,workflowScope:j.scope,job:j,output:o,
    order:existing?.order??tasks.length+index,stale:!!j.stale,stage:j.recipe,createdAt:j.createdAt,
    catalog:{...existing?.catalog,category:j.category,entityId:j.entityId,entityName:definition?.name||j.title,
     variant:definition?.variant||existing?.catalog?.variant||'',version:existing?.catalog?.version||1}});
  }
 }
 const archives=new Map();
 for(const p of plans)for(const e of p.entities||[]){
  if(!categories.has(e.category))continue;
  const key=JSON.stringify(['script',p.scriptId,e.category,e.id]);
  archives.set(key,{key,entityId:e.id,name:e.name,category:e.category,scope:p.scriptId,series:'剧本资产',
   description:e.description||'',variant:e.variant||'',defined:true,items:[]});
 }
 for(const item of images.values()){
  const info=identity(item);if(!info)continue;
  if(!archives.has(info.key))archives.set(info.key,{...info,items:[]});
  archives.get(info.key).items.push(item);
 }
 for(const a of archives.values()){
  for(const stage of ['style','asset','clean']){
   const revisions=[...new Map(a.items.filter(t=>t.job&&t.stage===stage).map(t=>[t.job.id,t.job])).values()]
    .sort((x,y)=>String(x.createdAt).localeCompare(String(y.createdAt)));
   for(const t of a.items.filter(t=>t.job&&t.stage===stage))t.catalog={...t.catalog,version:revisions.findIndex(j=>j.id===t.job.id)+1};
  }
  a.items.sort((x,y)=>x.job&&y.job
   ? String(y.job.createdAt).localeCompare(String(x.job.createdAt))||String(x.id).localeCompare(String(y.id))
   : y.order-x.order);
  a.approved=a.items.filter(t=>t.humanReview==='approved'&&!t.stale);
  a.cover=a.approved[0]||a.items[0]||null;a.latestOrder=Math.max(-1,...a.items.map(t=>t.order));
  a.name=a.name.split(' · ')[0];
 }
 return [...archives.values()].sort((a,b)=>b.latestOrder-a.latestOrder);
}

export function assetCoverage(entities=[],jobs=[],scope){
 const rows=entities.filter(e=>categories.has(e.category)).map(e=>{
  const stages={};
  for(const recipe of ['style','asset','clean']){
   const related=jobs.filter(j=>j.scope===scope&&j.entityId===e.id&&j.category===e.category&&j.recipe===recipe&&!j.stale);
   stages[recipe]=related.some(j=>j.outputs?.some(o=>o.review==='approved'))?'approved':
    related.some(j=>['preparing','running','downloading'].includes(j.status))?'running':
    related.some(j=>j.outputs?.some(o=>o.review==='pending'))?'pending':
    related.some(j=>j.status==='needs_attention')?'needs_attention':
    related.some(j=>j.outputs?.some(o=>o.review==='changes_requested'))?'changes_requested':
    related.some(j=>j.status==='draft')?'draft':'missing';
  }
  return {...e,stages,ready:stages.asset==='approved'&&stages.clean==='approved'};
 });
 const groups=[...categories].map(category=>({category,total:rows.filter(e=>e.category===category).length,
  ready:rows.filter(e=>e.category===category&&e.ready).length})).filter(g=>g.total);
 return {rows,groups,total:rows.length,ready:rows.filter(e=>e.ready).length,missing:rows.filter(e=>!e.ready)};
}
