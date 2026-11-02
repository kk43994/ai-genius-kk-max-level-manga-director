import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';
const root=document.getElementById('workflow-root'),output=document.getElementById('results');
const owner={providerAccountId:'synthetic',spaceId:'personal'},project={id:'project',name:'合成总览',scriptIds:['script'],version:1};
const shot={id:'shot',sceneId:'scene',purpose:'读信',beat:'看信封',framing:'近景',durationSeconds:5,dialogueIds:[],references:[],startState:'信封在桌上',endState:'拿起信封',continuity:[]};
const job={id:'production',status:'ready',ownership:owner,characters:[],dialogues:[],result:{assets:[],shots:[shot]},bindings:[],shotBindings:[{shotId:'shot',entityId:'shot-entity'}]};
const task={id:'task',projectId:'project',entityId:'shot-entity',status:'queued',ownership:owner,canRecover:false};
const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
const drafts=new DraftStore(storage,'tenant','/api/v1');drafts.set('selectedProject','project');drafts.set('page','delivery');
let reads=0,writes=0;const assets=[];
const api={request:async(path,options={})=>{
 if(options.method&&options.method!=='GET'){writes++;throw Error('No writes in this fixture');}
 if(path==='/projects')return {items:[project]};if(path==='/projects/project')return project;
 if(path==='/workflow/capabilities')return {scriptAnalysis:false};
 if(path.endsWith('/plan'))return {entities:[],version:1};
 if(path.endsWith('/assets'))return {items:structuredClone(assets),coverage:{total:1,ready:0,entities:[{shotId:'shot',designCurrent:true}]}};
 if(path.endsWith('/bundles')||path.endsWith('/prompts'))return {items:[]};
 if(path.endsWith('/scripts/script'))return {id:'script',text:'合成',characters:2,filename:'合成.txt'};
 if(path.endsWith('/analysis'))return {analysis:null};if(path.endsWith('/production'))return {analysis:job};
 if(path.startsWith('/tasks?')){reads++;return {items:[structuredClone(task)]};}
 throw Error('Unexpected fixture read '+path);
}};
const app=mount({root,api,storage,session:{tenant:{id:'tenant'},selection:owner,features:{imageGeneration:false}}});
const results=[],check=(ok,name)=>{results.push({ok,name});output.textContent=results.map(r=>`${r.ok?'PASS':'FAIL'} ${r.name}`).join('\n');};
await app.ready;
check(root.querySelector('.overview-shot').textContent.includes('正在排队'),'初始总览显示排队状态');
check(root.ownerDocument.body.dataset.workflowPage==='plan'&&root.querySelectorAll('.wf-tabs button').length===4,'旧交付入口自动进入同一剧情画布');
root.querySelector('.overview-shot details').open=true;
const slot=root.querySelector('[data-story-node="shot:shot"]');
const position={left:slot.style.left,top:slot.style.top};
const view=root.querySelector('[data-story-stage]').style.transform;
task.status='running';
await new Promise(resolve=>setTimeout(resolve,5500));
check(reads>=2&&root.querySelector('.overview-shot').textContent.includes('正在生成'),'没有新图片时，任务变更仍刷新总览');
check(root.querySelector('.overview-shot details').open,'后台刷新保留展开的连续性内容');
check(writes===0,'总览轮询不提交生成或恢复任务');
assets.push({id:'synthetic-frame',name:'读信',active:true,entityId:'shot-entity',revisions:[{id:'candidate',assetId:'synthetic-frame',entityId:'shot-entity',stage:'storyboard',status:'ready',review:'pending',ownership:owner,createdAt:'2026-11-03',reviewHistory:[]}]});
// Keep a task active for one polling cycle; this is a simulated provider return only.
task.status='running';await new Promise(resolve=>setTimeout(resolve,5500));
const filled=root.querySelector('[data-story-node="shot:shot"]');
check(Boolean(filled.querySelector('img'))&&filled.textContent.includes('待审核'),'候选图原位补入，仍等待人工选用');
check(filled.style.left===position.left&&filled.style.top===position.top&&root.querySelector('[data-story-stage]').style.transform===view,'补图保留卡片位置与画布视角');
check(filled.querySelector('details').open,'补图保留展开的连续性说明');
check(writes===0,'自动补图只读取结果，不新增生成或选用请求');
app.unmount();document.documentElement.dataset.testStatus=results.every(r=>r.ok)?'passed':'failed';
