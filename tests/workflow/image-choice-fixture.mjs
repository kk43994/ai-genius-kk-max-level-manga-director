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
 if(path==='/image-models')return {defaultModelId:'fixture-image',models:[{id:'fixture-image',name:'合成图片模型'}]};
 if(path.startsWith('/image-models?'))return {verified:true,settingsSchema:{properties:{},required:[]}};
 if(path.startsWith('/libtv-assets?'))return path.includes('assetId=')?{id:'library',name:'素材库示意图',version:1,images:[{index:0,preview:'/tests/ui/synthetic-assets.svg'}]}:{items:[{id:'library',name:'素材库示意图'}]};
 if(path==='/projects/project/library-references'){log('IMPORT library image '+body.imageIndex);return {revision:assets.at(-1).revisions[0]};}
 if(path.startsWith('/assets/')&&path.endsWith('/reviews')){
  const asset=assets.find(a=>a.id===path.split('/')[2]),r=asset.revisions.find(r=>r.id===body.revisionId);
  r.review=body.decision;r.reviewHistory.push({decision:body.decision,note:body.note,at:new Date().toISOString()});asset.version++;log(`REVIEW ${r.id}: ${r.review}`);return {assetVersion:asset.version,revision:structuredClone(r)};
 }
 if(path==='/production-jobs/production/review'){job.result=body.result;job.reviewVersion++;log('SAVE '+JSON.stringify(job.result.shots[0].references));return structuredClone(job);}
 throw Error('合成环境禁止此请求：'+path);
}};
// Only fixture image URLs are replaced with an explicitly synthetic illustration.
new MutationObserver(()=>root.querySelectorAll('img').forEach(img=>{if(img.getAttribute('src')?.startsWith('/api/v1/'))img.src='/tests/ui/synthetic-assets.svg';})).observe(root,{childList:true,subtree:true});
const app=mount({root,api,storage,session:{tenant:{id:'tenant'},selection:{...owner,revision:1},features:{imageGeneration:false}}});
await app.ready;
