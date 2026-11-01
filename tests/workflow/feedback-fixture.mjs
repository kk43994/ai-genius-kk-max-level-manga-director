import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';

// No network APIs or real credentials. Timers intentionally use wall-clock time.
const root=document.getElementById('workflow-root'), output=document.getElementById('results');
const owner={providerAccountId:'fixture-account',spaceId:'fixture-space',accountLabelAtCreation:'合成账号',spaceNameAtCreation:'仅界面测试'};
const project={id:'fixture-project',name:'合成回归项目',scriptIds:['fixture-script'],version:1};
const entity={id:'fixture-entity',name:'测试旅人',category:'character',description:'合成角色',version:1};
const plan={version:1,styleVersion:1,stylePrompt:'黑白',entities:[entity]};
const task={id:'fixture-task',projectId:project.id,entityId:entity.id,recipe:'mj_style',status:'running',
  submissionAttempted:true,canRecover:true,canConfirm:false,ownership:owner,version:1,sourceRevisionIds:[],
  providerReceipt:{projectId:'fixture-remote-project',taskId:'fixture-original-task'},
  createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),workflowSnapshot:{entityVersion:1,styleVersion:1}};
const values=new Map(), storage={getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)};
const drafts=new DraftStore(storage,'fixture-tenant','/api/v1');
drafts.set('page','style');drafts.set('selectedProject',project.id);drafts.set('selectedEntity',entity.id);drafts.set(`flow:${project.id}`,true);
let reads=0, recoveries=0, progressObserved=false;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const api={request:async(path)=>{
  if(path==='/workflow/capabilities')return {scriptAnalysis:false,localScriptExtraction:false};
  if(path.endsWith('/prompts'))return {items:[]};
  if(path.endsWith('/analysis'))return {analysis:null};
  if(path==='/projects')return {items:[project]};
  if(path==='/projects/'+project.id)return project;
  if(path.endsWith('/production'))return {analysis:null};
  if(path.endsWith('/plan'))return plan;
  if(path.endsWith('/assets'))return {items:[],coverage:{total:1,ready:0,complete:false}};
  if(path.endsWith('/bundles'))return {items:[]};
  if(path.startsWith('/tasks?')){reads++;return {items:[structuredClone(task)]};}
  if(path.endsWith('/scripts/fixture-script'))return {id:'fixture-script',filename:'测试.txt',characters:8,text:'角色：测试旅人'};
  if(path==='/tasks/fixture-task/recover'){
    recoveries++;progressObserved=Boolean(root.querySelector('[data-wf-operation] progress'));
    await delay(2000);task.updatedAt=new Date().toISOString();task.version++;return {task:structuredClone(task)};
  }
  throw new Error('Unexpected fixture request: '+path);
}};
const results=[];
function check(ok,name){results.push({ok,name});output.textContent=results.map(r=>`${r.ok?'PASS':'FAIL'} ${r.name}`).join('\n');}
const app=mount({root,api,storage,session:{tenant:{id:'fixture-tenant'},selection:{...owner,revision:1},features:{imageGeneration:false}}});
await app.ready;
// Initial model discovery also finishes before testing background task refresh.
await delay(0);
root.querySelector('details').open=true;
const input=root.querySelector('textarea[name="prompt"]');input.value='正在编辑的剧本设定';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();input.setSelectionRange(3,5);
await delay(5500);
check(reads>=2,'运行中的任务在 5 秒后读取新状态');
check(root.querySelector('textarea[name="prompt"]')===input&&document.activeElement===input&&input.selectionStart===3&&input.selectionEnd===5,
  '后台刷新保留原输入节点、焦点和选区');
check(input.value==='正在编辑的剧本设定','后台刷新保留尚未提交的输入');
await delay(5200);
check(recoveries===1,`5 秒轮询没有推迟 8 秒原任务查询，且只查询一次（实际 ${recoveries} 次，页面 ${document.visibilityState}）`);
check(!progressObserved,'自动收取不占用前台操作进度');
check(root.querySelector('textarea[name="prompt"]').value==='正在编辑的剧本设定','原任务查询完成后草稿仍保留');
check(!root.querySelector('[data-wf-operation] progress'),'请求结束后清理处理中状态');
root.querySelector('[data-wf-action="refresh"]').click();
await delay(50);
check(root.querySelector('details').open,'显式刷新后保留用户展开的编辑区');
app.unmount();
document.documentElement.dataset.testStatus=results.every(r=>r.ok)?'passed':'failed';
document.documentElement.dataset.testCount=String(results.length);
