import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';
const fixture=await fetch('/docs/screenplay-analysis-v1.example.json').then(r=>r.json());
const root=document.getElementById('workflow-root'),owner={providerAccountId:'synthetic-account',spaceId:'synthetic-space'};
const project={id:'project',name:'书店来信 · 流水线合成验收',scriptIds:['script'],version:1,artStudies:Object.fromEntries(['character','scene','trial'].map(role=>[role,{entityId:'study-'+role,name:role}]))};
const analysis={id:'analysis',status:'ready',reviewVersion:0,resultHash:'synthetic',result:fixture.result,completedCalls:1,validationIssues:[],ownership:owner,message:'合成分析已返回'};
const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
const drafts=new DraftStore(storage,'fixture-pipeline','/api/v1');drafts.set('selectedProject','project');drafts.set('page','plan');
const assets=[],tasks=new Map(),plan={version:1,styleVersion:1,entities:[],stylePrompt:''};let production=null,serial=0;
const log=m=>document.getElementById('fixture-log').textContent+='\n'+m;
const addAsset=(id,category,name)=>{let a=assets.find(a=>a.entityId===id);if(!a){a={id:'archive-'+id,entityId:id,name,category,active:true,version:1,revisions:[]};assets.push(a);plan.entities.push({id,category,name,origin:'manual',version:1});plan.version++;}return a;};
const prepare=(a,body,stage)=>{
 const id='synthetic-task-'+(++serial),response={task:{id,entityId:a.entityId,version:1,recipe:body.recipe||'image25_style',status:'prepared',canConfirm:true,ownership:owner,sourceRevisionIds:body.sourceRevisionIds||[]},confirmation:{token:'synthetic',summary:{count:body.settings.count||1,modelKey:body.modelId,prompt:body.prompt}},cost:{state:'known',amount:0,unit:'synthetic'}};
 tasks.set(id,{a,body,stage,response});log('PREPARE '+a.name+' · '+body.modelId);return structuredClone(response);
};
function buildProduction(){
 const material=(id,name,category)=>({id,name,category,design:'简洁线条，独立身份与中性服装',creativeChoices:[],evidence:[],states:[{id:'base',name:'书店相见',sceneIds:[fixture.result.scenes[0].id],description:'基础剧情状态',imagePrompt:'清楚展示本对象的基础外观与结构，简洁背景。'}]});
 const rows=[material('person','林舟','character'),material('place','旧书店门口','scene'),material('prop','信封','prop')];
 return {id:'production',status:'ready',reviewVersion:1,editVersion:0,bindingVersion:1,ownership:owner,validationIssues:[],characters:fixture.result.characters,dialogues:fixture.result.dialogues,
  result:{aspectRatio:'9:16',styleBible:'细线条，柔和暖色',assets:rows,scenePlans:[],uncertainties:[],shots:[{id:'shot-1',sceneId:fixture.result.scenes[0].id,order:1,purpose:'递出信封',beat:'林舟递出信封。',framing:'中景',camera:'固定',performance:'手势克制',sound:'环境音',startState:'信封在林舟手里',endState:'信封递到对方面前',imagePrompt:'林舟在书店门口递出信封，保持所有参考外观',videoPrompt:'',durationSeconds:4,dialogueIds:[fixture.result.dialogues[0].id],evidence:[],continuity:['信封位置连续'],references:rows.map(a=>({assetId:a.id,stateId:'base'}))}]},
  bindings:rows.flatMap(a=>[...(a.category==='character'?[{assetId:a.id,stateId:'__character_master__',entityId:a.id+'-master',saved:true,legacyCandidates:[{entityId:'study-character',name:'人物风格试做样板'}]}]:a.category==='scene'?[{assetId:a.id,stateId:'__scene_master__',entityId:a.id+'-master',saved:true,legacyCandidates:[{entityId:'study-scene',name:'场景风格试做样板'}]}]:[]),{assetId:a.id,stateId:'base',entityId:a.id+'-base',saved:true}]),shotBindings:[]};
}
const api={request:async(path,options={})=>{
 const b=options.body;
 if(path==='/projects')return {items:[project]};if(path==='/projects/project')return structuredClone(project);
 if(path==='/workflow/capabilities')return {scriptAnalysis:true,analysis:{models:[{id:'synthetic-text',name:'合成文本模型'}],defaultModelId:'synthetic-text'}};
 if(path.endsWith('/plan'))return structuredClone(plan);
 if(path.endsWith('/assets'))return structuredClone({items:assets,coverage:{total:assets.length,ready:assets.filter(a=>a.revisions.some(r=>r.review==='approved')).length,entities:(production?.result.shots||[]).map(s=>({shotId:s.id,designCurrent:true})),exportRevisionIds:assets.flatMap(a=>a.revisions.filter(r=>r.stage==='storyboard'&&r.review==='approved').map(r=>r.id))}});
 if(path.endsWith('/bundles')||path.endsWith('/prompts'))return {items:[]};
 if(path.startsWith('/tasks?'))return {items:[...tasks.values()].map(t=>structuredClone(t.response.task))};
 if(path.endsWith('/scripts/script'))return {id:'script',text:fixture.sourceText,characters:fixture.sourceText.length,filename:'合成来信.txt'};
 if(path.endsWith('/analysis'))return {analysis:structuredClone(analysis)};
 if(path.endsWith('/production')){if(options.method==='POST'){production=buildProduction();log('PRODUCTION framework filled');}return options.method==='POST'?structuredClone(production):{analysis:structuredClone(production)};}
 if(path==='/production-jobs/production')return structuredClone(production);
 if(path==='/image-models')return {items:[{id:'fixture-pro',name:'Lib Image 2.5 Pro'},{id:'fixture-mj',name:'MJ V8.1'},{id:'fixture-nano',name:'Nano Banana 2'}]};
 if(path.startsWith('/image-models?'))return {verified:true,schema:{properties:{count:{type:'integer',enum:[1,2,4]},ratio:{type:'string',enum:['16:9','9:16','2:3','1:1']}},required:[]}};
 if(path.endsWith('/art-studies/prepare')){
  const a=addAsset('study-'+b.role,b.role==='character'?'character':'scene',b.role+'样板');
  return prepare(a,{...b,sourceRevisionIds:Object.values(b.samples||{}).map(r=>r.revisionId)},'style');
 }
 if(path.endsWith('/art-direction')){
  const all=assets.flatMap(a=>a.revisions),samples=Object.fromEntries(Object.entries(b.samples).map(([k,v])=>{const r=all.find(r=>r.id===v.revisionId);if(r?.review!=='approved')throw Error('先选用样板');return [k,{...v,assetId:r.assetId,prompt:r.prompt,sourceRevisionIds:r.sourceRevisionIds}];}));
  if(Object.keys(samples).length!==3)throw Error('三项试做未齐');
  project.artDirection={version:(project.artDirection?.version||0)+1,valid:true,...samples.character,notes:b.notes,samples};log('STANDARD confirmed');return structuredClone(project.artDirection);
 }
 if(path.startsWith('/assets/')&&path.endsWith('/reviews')){
  const a=assets.find(a=>a.id===path.split('/')[2]),r=a.revisions.find(r=>r.id===b.revisionId);
  if(b.decision==='approved')a.revisions.filter(v=>v.stage===r.stage&&v.id!==r.id&&v.review==='approved').forEach(v=>v.review='superseded');
  r.review=b.decision;r.reviewHistory.push({decision:b.decision,note:b.note,at:new Date().toISOString()});a.version++;log('PICK '+r.id);return {revision:structuredClone(r),assetVersion:a.version};
 }
 if(path==='/production-jobs/production/bindings'){const binding=production.bindings.find(r=>r.assetId===b.assetId&&r.stateId===b.stateId);Object.assign(binding,{entityId:b.entityId,linked:true,saved:true,name:assets.find(a=>a.entityId===b.entityId).name});production.bindingVersion++;log('BIND '+b.assetId);return structuredClone(production);}
 if(path.endsWith('/prompt-recipes')){const r=assets.flatMap(a=>a.revisions).find(r=>r.id===b.revisionId);project.promptRecipes??=[];project.promptRecipes.push({...b,id:'recipe-'+project.promptRecipes.length,status:'single',modelLabel:r.modelLabel,settings:r.settings,evidence:[{revisionId:r.id}]});project.promptRecipeVersion=(project.promptRecipeVersion||0)+1;log('RECIPE saved');return structuredClone(project.promptRecipes.at(-1));}
 if(path==='/production-jobs/production/review'){production.result=b.result;production.reviewVersion++;log('SAVE production');return structuredClone(production);}
 if(path==='/production-jobs/production/images/prepare'){
  const shot=production.result.shots.find(s=>s.id===b.shotId),m=production.result.assets.find(a=>a.id===b.assetId),binding=production.bindings.find(r=>r.assetId===b.assetId&&r.stateId===b.stateId);
  const a=addAsset(shot?'shot-entity':binding.entityId,shot?'shot':m.category,shot?'分镜 001':m.name);
  if(shot&&!production.shotBindings.length)production.shotBindings.push({shotId:shot.id,entityId:a.entityId,saved:true});
  return prepare(a,b,shot?'storyboard':b.recipe==='image25_style'?'style':'asset');
 }
 if(path.startsWith('/tasks/')&&path.endsWith('/submit')){
  const t=tasks.get(path.split('/')[2]),{a,body,stage,response}=t;
  for(let i=0;i<(body.settings.count||1);i++){a.revisions.push({id:response.task.id+'-'+i,assetId:a.id,entityId:a.entityId,stage,status:'ready',review:'pending',ownership:owner,sha256:'synthetic-'+serial,createdAt:new Date().toISOString(),sourceRevisionIds:response.task.sourceRevisionIds,prompt:body.prompt,settings:body.settings,modelLabel:body.modelId,reviewHistory:[],width:600,height:400});}
  response.task={...response.task,status:'completed',canConfirm:false};log('RETURN pending '+a.name);return {task:structuredClone(response.task)};
 }
 throw Error('合成验收未支持：'+path);
}};
new MutationObserver(()=>root.querySelectorAll('img').forEach(img=>{if(img.getAttribute('src')?.startsWith('/api/v1/'))img.src='/tests/ui/synthetic-assets.svg';})).observe(root,{childList:true,subtree:true});
const app=mount({root,api,storage,session:{tenant:{id:'fixture-pipeline'},selection:{...owner,revision:1},features:{imageGeneration:true}}});
await app.ready;

// Deterministic completed state for preview/layout regression, explicitly separate
// from the interactive generation route above. Never sent to a real server.
document.getElementById('fixture-completed').onclick=async()=>{
 production=buildProduction();assets.length=0;plan.entities.length=0;tasks.clear();
 const a=addAsset('shot-entity','shot','合成分镜 001');
 a.revisions.push({id:'seed-shot',assetId:a.id,entityId:a.entityId,stage:'storyboard',status:'ready',review:'approved',ownership:owner,sha256:'synthetic-seed',createdAt:new Date().toISOString(),sourceRevisionIds:[],prompt:'合成图板',settings:{},reviewHistory:[],width:600,height:400});
 production.shotBindings=[{shotId:'shot-1',entityId:a.entityId,saved:true}];
 log('FIXTURE completed preview loaded; not a generation result');
 await app.refresh();
};
