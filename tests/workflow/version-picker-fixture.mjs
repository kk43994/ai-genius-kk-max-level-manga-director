import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';
const owner={providerAccountId:'synthetic-account',spaceId:'synthetic-space'},root=document.getElementById('workflow-root');
const project={id:'project',name:'看图选择 · 合成项目',scriptIds:['script'],version:1,artDirection:{version:1,valid:true,assetId:'archive-prop',revisionId:'prop-style-a',notes:'合成验收规范'}};
const material=(id,name,category)=>({id,name,category,design:'用于界面测试的合成素材',creativeChoices:[],evidence:[],states:[{id:'base',name:'基础状态',sceneIds:['scene'],description:'合成状态',imagePrompt:'合成图'}]});
const materials=[material('prop','信封','prop'),material('scene','书房','scene')];
const shot={id:'shot',sceneId:'scene',order:1,purpose:'角色发现信封',beat:'桌上放着信封。',imagePrompt:'合成镜头',videoPrompt:'',durationSeconds:4,dialogueIds:[],evidence:[],continuity:[],references:[{assetId:'prop',stateId:'base',revisionId:'prop-asset-a'}]};
const job={id:'production',status:'ready',reviewVersion:1,editVersion:0,bindingVersion:1,ownership:owner,result:{aspectRatio:'9:16',styleBible:'合成',assets:materials,shots:[shot],scenePlans:[],uncertainties:[]},bindings:materials.map(a=>({assetId:a.id,stateId:'base',entityId:a.id,saved:true})),shotBindings:[],dialogues:[],characters:[]};
const revision=(entity,stage,suffix,review='approved')=>({id:`${entity}-${stage}-${suffix}`,assetId:`archive-${entity}`,entityId:entity,stage,review,status:'ready',sha256:'synthetic',createdAt:'2026-11-02T12:00:00Z',ownership:owner,reviewHistory:[],sourceRevisionIds:[],width:600,height:600});
const assets=materials.map(a=>({id:`archive-${a.id}`,entityId:a.id,name:a.name,category:a.category,active:true,version:1,revisions:[revision(a.id,'style','a'),revision(a.id,'style','b'),revision(a.id,'asset','a'),revision(a.id,'asset','b','pending')]}));
assets.push({id:'archive-upload',entityId:'upload',name:'构图参考',active:true,referenceOnly:true,version:1,revisions:[revision('upload','asset','a','pending')]});
const preparedTasks=new Map();
const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
const drafts=new DraftStore(storage,'tenant','/api/v1');drafts.set('selectedProject','project');drafts.set('page','asset');
const log=message=>{document.getElementById('fixture-log').textContent+=`\n${message}`;};
const api={request:async(path,options={})=>{
 const body=options.body;
 if(path==='/projects')return {items:[project]};if(path==='/projects/project')return project;
 if(path==='/workflow/capabilities')return {scriptAnalysis:false};
 if(path.endsWith('/plan'))return {version:1,styleVersion:1,entities:materials.map(a=>({...a,version:1}))};
 if(path.endsWith('/assets'))return structuredClone({items:assets,coverage:{total:3,ready:2}});
 if(path.endsWith('/bundles')||path.endsWith('/prompts')||path.startsWith('/tasks?'))return {items:[]};
 if(path.endsWith('/scripts/script'))return {id:'script',text:'用于验证图片选择的合成剧本。',filename:'合成剧本.txt'};
 if(path.endsWith('/analysis'))return {analysis:{id:'analysis',status:'ready'}};
 if(path.endsWith('/production'))return {analysis:structuredClone(job)};
 if(path==='/image-models')return {defaultModelId:'fixture-image',items:[{id:'fixture-image',name:'Lib Image 2.5 Pro'}]};
 if(path.startsWith('/image-models?'))return {verified:true,schema:{properties:{count:{type:'integer',enum:[1,2,4]},ratio:{type:'string',enum:['16:9','9:16','1:1']}},required:[]}};
 if(path.startsWith('/libtv-assets?'))return path.includes('assetId=')?{id:'library',name:'素材库示意图',version:1,images:[{index:0,preview:'/tests/ui/synthetic-assets.svg'}]}:{items:[{id:'library',name:'素材库示意图'}]};
 if(path==='/projects/project/library-references'){log('IMPORT library image '+body.imageIndex);return {revision:assets.at(-1).revisions[0]};}
 if(path.startsWith('/assets/')&&path.endsWith('/reviews')){
  const asset=assets.find(a=>a.id===path.split('/')[2]),r=asset.revisions.find(r=>r.id===body.revisionId);
  if(body.decision==='approved')asset.revisions.filter(v=>v.stage===r.stage&&v.id!==r.id&&v.review==='approved').forEach(v=>v.review='superseded');
  r.review=body.decision;r.reviewHistory.push({decision:body.decision,note:body.note,at:new Date().toISOString()});asset.version++;log(`REVIEW ${r.id}: ${r.review}`);return {assetVersion:asset.version,revision:structuredClone(r)};
 }
 if(path==='/production-jobs/production/review'){job.result=body.result;job.reviewVersion++;log('SAVE '+JSON.stringify(job.result.shots[0].references));return structuredClone(job);}
 if(path==='/production-jobs/production/images/prepare'){
  if(!body.confirmEditReference||!body.editRevisionId||body.editSha256!=='synthetic')throw Error('缺少原图确认');
  const id='task-'+(preparedTasks.size+1),r=assets.flatMap(a=>a.revisions).find(r=>r.id===body.editRevisionId);
  const response={task:{id,entityId:r.entityId,version:1,recipe:body.recipe,ownership:owner,sourceRevisionIds:r.sourceRevisionIds},confirmation:{token:'synthetic',summary:{count:1,modelKey:'合成模型',prompt:body.prompt+'\n修改意见：'+body.editNote}},cost:{state:'known',amount:0,unit:'synthetic'}};
  preparedTasks.set(id,{r,response});log('PREPARE '+body.editRevisionId+' · '+body.editNote);return response;
 }
 if(path.startsWith('/tasks/')&&path.endsWith('/submit')){
  const {r,response}=preparedTasks.get(path.split('/')[2]),asset=assets.find(a=>a.id===r.assetId);
  const candidate={...structuredClone(r),id:r.id+'-new-'+asset.revisions.length,review:'pending',reviewHistory:[]};asset.revisions.push(candidate);
  log('RETURN '+candidate.id+' pending; current='+asset.revisions.find(v=>v.stage===r.stage&&v.review==='approved')?.id);return {task:{...response.task,status:'completed'}};
 }
 throw Error('合成环境禁止此请求：'+path);
}};
// Only fixture image URLs are replaced with an explicitly synthetic illustration.
new MutationObserver(()=>root.querySelectorAll('img').forEach(img=>{if(img.getAttribute('src')?.startsWith('/api/v1/'))img.src='/tests/ui/synthetic-assets.svg';})).observe(root,{childList:true,subtree:true});
const app=mount({root,api,storage,session:{tenant:{id:'tenant'},selection:{...owner,revision:1},features:{imageGeneration:true}}});
await app.ready;
