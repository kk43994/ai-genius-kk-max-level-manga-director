import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';
const root=document.getElementById('workflow-root'),output=document.getElementById('results');
const owner={providerAccountId:'fixture-account',spaceId:'fixture-space'};
const project={id:'project',name:'合成审核项目',scriptIds:[],version:1};
const entity={id:'entity',name:'合成道具',category:'prop',version:1};
const revision={id:'revision',assetId:'asset',entityId:entity.id,stage:'style',status:'ready',review:'pending',sha256:'synthetic',ownership:owner,reviewHistory:[],sourceRevisionIds:[]};
const asset={id:'asset',entityId:entity.id,name:entity.name,active:true,version:1,revisions:[revision]};
const task={id:'task',projectId:project.id,entityId:entity.id,recipe:'mj_style',status:'draft',canConfirm:true,version:1,ownership:owner,sourceRevisionIds:[],createdAt:new Date().toISOString(),updatedAt:new Date().toISOString()};
const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
const drafts=new DraftStore(storage,'tenant','/api/v1');drafts.set('page','review');drafts.set('selectedProject',project.id);drafts.set('selectedEntity',entity.id);
let submitResolve,reviewResolve,submits=0,reviews=0,projectReads=0;
const api={request:async(path,options={})=>{
 if(path==='/projects'){projectReads++;return {items:[project]};}
 if(path==='/projects/project')return project;
 if(path==='/workflow/capabilities')return {scriptAnalysis:false};
 if(path.endsWith('/plan'))return {version:1,styleVersion:1,entities:[entity]};
 if(path.endsWith('/assets'))return structuredClone({items:[asset],coverage:{total:1,ready:0}});
 if(path.endsWith('/bundles')||path.endsWith('/prompts'))return {items:[]};
 if(path.startsWith('/tasks?'))return {items:[structuredClone(task)]};
 if(path==='/tasks/task/confirm')return {task:structuredClone(task),confirmation:{token:'synthetic',summary:{count:1,modelKey:'fixture',prompt:'合成提示词'}}};
 if(path==='/tasks/task/submit'){submits++;await new Promise(r=>submitResolve=r);task.status='queued';task.canConfirm=false;return {task:structuredClone(task)};}
 if(path==='/assets/asset/reviews'){reviews++;await new Promise(r=>reviewResolve=r);revision.review=options.body.decision;revision.reviewHistory.push({decision:revision.review,note:options.body.note,at:new Date().toISOString()});asset.version++;return {assetVersion:asset.version,revision:structuredClone(revision)};}
 throw new Error('Unexpected synthetic request '+path);
}};
const results=[],tick=()=>new Promise(r=>setTimeout(r,0));
function check(ok,name){results.push({ok,name});output.textContent=results.map(r=>`${r.ok?'PASS':'FAIL'} ${r.name}`).join('\n');}
const app=mount({root,api,storage,session:{tenant:{id:'tenant'},selection:{...owner,revision:1},features:{imageGeneration:true}}});
await app.ready;await tick();
root.querySelector('[data-wf-confirm-task]').click();await tick();
root.querySelector('[data-wf-action="submit-task"]').click();await tick();
check(submits===1&&root.querySelector('[data-wf-action="submit-task"]').disabled,'仅启动一条合成生成请求');
root.querySelector('[data-wf-review]').click();await tick();
check(!root.querySelector('[data-wf-action="approve"]').disabled,'生成尚未返回时审核按钮可用');
const note=root.querySelector('[data-wf-review-note]');note.value='合成审核意见';note.dispatchEvent(new Event('input',{bubbles:true}));
const readsBefore=projectReads;root.querySelector('[data-wf-action="approve"]').click();await tick();
check(root.querySelector('[data-wf-action="approve"]').disabled&&root.querySelector('[data-wf-action="reject"]').disabled,'审核保存期间阻止重复决定');
root.querySelector('[data-wf-action="approve"]').click();await tick();check(reviews===1,'重复点击没有第二次审核');
reviewResolve();await tick();await tick();
check(revision.review==='approved'&&!root.querySelector('[data-review-detail]'),'审核结果已刷新且关闭原审核框');
check(projectReads===readsBefore,'审核仅刷新资产，不重载全项目');
check(submits===1&&root.textContent.includes('正在提交这批图片'),'审核完成保留原提交，未重复生成');
submitResolve();await tick();await tick();await tick();
check(submits===1&&root.textContent.includes('已处理 1 组提交'),'原提交正常结束并保留结果');
app.unmount();document.documentElement.dataset.testStatus=results.every(r=>r.ok)?'passed':'failed';
