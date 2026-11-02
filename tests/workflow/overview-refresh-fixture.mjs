import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';
const root=document.getElementById('workflow-root'),output=document.getElementById('results');
const owner={providerAccountId:'synthetic',spaceId:'personal'},project={id:'project',name:'合成总览',scriptIds:['script'],version:1};
const shot={id:'shot',sceneId:'scene',purpose:'读信',beat:'看信封',framing:'近景',durationSeconds:5,dialogueIds:[],references:[],startState:'信封在桌上',endState:'拿起信封',continuity:[]};
const job={id:'production',status:'ready',ownership:owner,characters:[],dialogues:[],result:{assets:[],shots:[shot]},bindings:[],shotBindings:[{shotId:'shot',entityId:'shot-entity'}]};
const task={id:'task',projectId:'project',entityId:'shot-entity',status:'queued',ownership:owner,canRecover:false};
const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
const drafts=new DraftStore(storage,'tenant','/api/v1');drafts.set('selectedProject','project');drafts.set('page','delivery');
let reads=0,writes=0;
const api={request:async(path,options={})=>{
 if(options.method&&options.method!=='GET'){writes++;throw Error('No writes in this fixture');}
 if(path==='/projects')return {items:[project]};if(path==='/projects/project')return project;
 if(path==='/workflow/capabilities')return {scriptAnalysis:false};
 if(path.endsWith('/plan'))return {entities:[],version:1};
 if(path.endsWith('/assets'))return {items:[],coverage:{total:1,ready:0,entities:[{shotId:'shot',designCurrent:true}]}};
 if(path.endsWith('/bundles')||path.endsWith('/prompts'))return {items:[]};
 if(path.endsWith('/scripts/script'))return {id:'script',text:'合成',filename:'合成.txt'};
 if(path.endsWith('/analysis'))return {analysis:null};if(path.endsWith('/production'))return {analysis:job};
 if(path.startsWith('/tasks?')){reads++;return {items:[structuredClone(task)]};}
 throw Error('Unexpected fixture read '+path);
}};
const app=mount({root,api,storage,session:{tenant:{id:'tenant'},selection:owner,features:{imageGeneration:false}}});
const results=[],check=(ok,name)=>{results.push({ok,name});output.textContent=results.map(r=>`${r.ok?'PASS':'FAIL'} ${r.name}`).join('\n');};
await app.ready;
check(root.querySelector('.overview-shot').textContent.includes('正在排队'),'初始总览显示排队状态');
root.querySelector('.overview-shot details').open=true;
task.status='needs_attention';
await new Promise(resolve=>setTimeout(resolve,5500));
check(reads>=2&&root.querySelector('.overview-shot').textContent.includes('原任务待查询'),'没有新图片时，任务变更仍刷新总览');
check(root.querySelector('.overview-shot details').open,'后台刷新保留展开的连续性内容');
check(writes===0,'总览轮询不提交生成或恢复任务');
app.unmount();document.documentElement.dataset.testStatus=results.every(r=>r.ok)?'passed':'failed';
