import {createApiClient, ApiError} from '../api-client.js';
import {mount as mountShell} from '../shell/index.js';
import {mount as mountAccounts} from '../accounts/index.js';
import {mount as mountWorkflow} from '../asset-lab.js';
import {mount as mountUpdates} from '../updates/index.js';
import {DraftCoordinator} from './drafts.mjs';
import {createSessionBoundary,inspectWorkspaceDrafts,saveWorkspaceDrafts} from './workspace-context.mjs';

const config = JSON.parse(document.getElementById('asset-lab-config').textContent);
const currentBuild = JSON.parse(document.getElementById('asset-lab-build').textContent);
const events = new EventTarget();
const transport = createApiClient(config);
// Account management is a panel; keep the production canvas in the first viewport.
const accountRoot = document.getElementById('account-root');
const accountButton = document.createElement('button'); accountButton.type='button';accountButton.className='lab-button integration-account-trigger';accountButton.textContent='管理工作区与账号';
accountButton.setAttribute('aria-haspopup','dialog');accountButton.setAttribute('aria-controls','integration-account-dialog');
accountRoot.before(accountButton);
const accountDialog=document.createElement('dialog');accountDialog.id='integration-account-dialog';accountDialog.className='integration-account-dialog';accountDialog.setAttribute('aria-label','工作区与 LibTV 账号');
const closeAccounts=document.createElement('button');closeAccounts.type='button';closeAccounts.className='lab-button integration-account-close';closeAccounts.textContent='关闭账号面板';
accountDialog.append(closeAccounts,accountRoot);document.body.append(accountDialog);
const openAccounts=()=>{if(!accountDialog.open)accountDialog.showModal();};
accountButton.addEventListener('click',openAccounts);closeAccounts.addEventListener('click',()=>accountDialog.close());
accountDialog.addEventListener('close',()=>accountButton.focus());
let readOnly = false, activeDownloads = 0, pendingWrites = 0, switchingWorkspace=false;
let workflow, accounts, drafts, shell, session, updates;
const status = document.createElement('div'); status.className = 'integration-notice'; status.setAttribute('role','status');
const save = document.createElement('button'); save.type='button'; save.textContent='保存当前草稿';
const message = document.createElement('span'); status.append(message, save);
document.getElementById('update-root').before(status);
function display(messageText) { message.textContent = messageText; }
function freezeEditing(value) {
  for(const id of ['workflow-root','task-root','update-root','warehouseList','importScript','scriptSelect']) {
    const node=document.getElementById(id);if(node)node.inert=value;
  }
  save.disabled=value;
}
const boundary=createSessionBoundary(transport,{onChanged:()=>{drafts?.pause();freezeEditing(true);}});
const api = {...boundary.api, async request(path, options = {}) {
  const write = !['GET','HEAD'].includes((options.method || 'GET').toUpperCase());
  if (readOnly && write && path !== '/drafts/browser') throw new ApiError('页面版本需要更新；请先保存草稿，再刷新。',{code:'CLIENT_VERSION_INCOMPATIBLE'});
  if (write) pendingWrites++;
  try { return await boundary.api.request(path,options); }
  finally { if(write) pendingWrites--; }
}};

async function saveDraft() {
  await workflow?.flushDrafts(); await accounts?.flush();
  return drafts.save({force:true});
}
save.addEventListener('click', () => saveDraft().then(result => {
  display(result.saved ? '草稿已保存到当前工作区。' : '刚才的草稿已保存，最新输入仍在保存中。');
}).catch(error => display(error.message)));

const running = new Set(['preparing','submitting','queued','running','downloading']);
async function listAllTasks() {
  const rows = []; let cursor = null; const seen = new Set();
  do {
    const value = await api.request('/tasks' + (cursor ? '?cursor='+encodeURIComponent(cursor) : ''));
    rows.push(...value.items); cursor = value.nextCursor;
    if (cursor && seen.has(cursor)) throw new Error('任务列表尚未完整读取');
    seen.add(cursor);
  } while(cursor);
  return rows;
}
async function safety() {
  const tasks = await listAllTasks();
  const state = workflow.getState();
  return {hasUnsavedChanges:boundary.frozen || accounts.getDirtyState().ownerActive || accounts.getDirtyState().authorizationActive || drafts.hasPending() || pendingWrites > 0 || state.busy || Boolean(state.saveError),
    activeTasks:tasks.filter(task => running.has(task.status)).length, activeDownloads};
}
async function refreshTasks() {
  const root = document.getElementById('task-root');
  try {
    const tasks = await listAllTasks(); root.replaceChildren();
    const count = tasks.filter(task=>running.has(task.status)).length;
    document.getElementById('taskCount').textContent = String(count);
    const note = document.createElement('p'); note.className='integration-task-note';
    note.textContent = tasks.length ? `共 ${tasks.length} 个任务，${count} 个正在处理。` : '还没有任务。准备或生成后的记录会保留在这里。';
    root.append(note);
    for (const task of tasks.slice(-20).reverse()) {
      const item=document.createElement('div'); item.className='integration-task';
      const label=document.createElement('strong'); label.textContent=task.recipe+' · '+({draft:'待确认',preparing:'准备中',submitting:'正在提交',queued:'排队中',running:'生成中',downloading:'收取中',completed:'文件已收取',needs_attention:'待处理',blocked_authorization:'需原账号授权',failed:'失败',cancelled:'已取消',unknown_submission:'提交状态待核验'}[task.status] || task.status);
      const owner=document.createElement('small'); owner.textContent=(task.ownership.accountLabelAtCreation || task.ownership.providerAccountId)+' / '+(task.ownership.spaceNameAtCreation || task.ownership.spaceId);
      item.append(label,owner);
      if(task.error?.message){const error=document.createElement('p');error.textContent=task.error.message;item.append(error);}
      if(task.canRecover) {const button=document.createElement('button');button.textContent='查询原任务并收取';button.addEventListener('click',async()=>{button.disabled=true;try{await api.request(`/tasks/${encodeURIComponent(task.id)}/recover`,{method:'POST',body:{expectedVersion:task.version}});events.dispatchEvent(new CustomEvent('tasks:changed'));}catch(error){display(error.message);}finally{button.disabled=false;}});item.append(button);}
      root.append(item);
    }
  } catch(error) {root.textContent='任务状态暂时无法读取；刷新更新将保持锁定。';}
}

// ZIP fetches go through the authenticated transport and are counted until body receipt.
document.addEventListener('click', async event => {
  const link=event.target.closest('a[href]'); if(!link || event.defaultPrevented || event.button!==0) return;
  const url=new URL(link.href);
  if(url.origin!==location.origin || !url.pathname.startsWith(config.apiBase+'/') || !(/\/projects\/[^/]+\/export$/.test(url.pathname)||/\/bundles\/[^/]+\/content$/.test(url.pathname))) return;
  event.preventDefault(); activeDownloads++;
  try {
    const blob=await api.request(url.pathname.slice(config.apiBase.length)+url.search,{responseType:'blob'});
    const object=URL.createObjectURL(blob), anchor=document.createElement('a'); anchor.href=object;anchor.download='资产实验室交付包.zip';document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(object),60000);
  } catch(error) {display(error.message);} finally{activeDownloads--;}
},true);

events.addEventListener('release:changed', event=>{
  if(event.detail.compatibleNow===false){readOnly=true;document.body.dataset.readOnly='true';display('页面与服务版本不兼容，当前处于只读状态；输入可继续保留为草稿。');}
  else if(event.detail.compatibleNow===true && readOnly){readOnly=false;delete document.body.dataset.readOnly;drafts?.onState(drafts);}
});
events.addEventListener('shell:action',event=>{
  if(event.detail.action==='connect'){event.preventDefault();openAccounts();if(config.mode==='local-client')void accounts?.authorize();}
  if(event.detail.action==='manual-plan')shell.setView({workspaceState:'ready'});
  if(event.detail.action==='help'){
    event.preventDefault();const dialog=document.getElementById('shell-info-dialog');
    document.getElementById('shell-info-title').textContent='使用资产实验室';
    const body=document.getElementById('shell-info-body');body.replaceChildren();
    for(const text of ['先创建项目，导入 TXT、Markdown 或 DOCX 剧本，也可以手工建立角色、场景和道具清单。',
      '工作区主所有者用于找回本站资料；创作账号与个人、团队空间用于明确新任务归属。切换选择不会改动历史任务。',
      '制作顺序是 MJ 风格 → Image2 资产 → Nano 精修。每一步先审核，再使用已确认版本继续；返修始终追溯原始 Image2。',
      '下载只包含已审核的成果。更新页面会先保存草稿，处理中的任务或下载会阻止刷新。',
      config.mode==='local-client'?'本地版可点击“授权 LibTV”连接自己的账号。当前仅读取账号信息，收费生成和视频尚未开放。':'当前为集成预览，可以整理项目与保存草稿。官方连接、收费生成和视频尚未开放。']){
      const paragraph=document.createElement('p');paragraph.textContent=text;body.append(paragraph);
    }
    if(!dialog.open)dialog.showModal();
  }
});
events.addEventListener('provider-accounts:changed',event=>{
  const items=event.detail.items || []; shell.setView({connectionState:items.some(item=>item.authorization?.state==='connected')?'connected':'disconnected'});
});
events.addEventListener('tasks:changed',()=>void refreshTasks());

function reloadWorkspace() {
  switchingWorkspace=true;drafts?.destroy();workflow?.unmount();accounts?.unmount();updates?.unmount();
  location.assign(config.publicBasePath);
}
function workspaceRecoveryHooks() {
  return {
    enabled:session?.features?.workspaceOwnerAuthorization===true,
    inspectDrafts:async()=>inspectWorkspaceDrafts({workflow,drafts,pendingWrites}),
    // Do not call accounts.flush here: its owner dialog is currently saving.
    saveDrafts:()=>saveWorkspaceDrafts({workflow,drafts}),
    async beforeSessionRotation() {
      if(activeDownloads)throw new Error('文件正在收取，请完成后再切换工作区。');
      drafts.pause();freezeEditing(true);
      try {
        const resume=await boundary.freeze();
        return async()=>{resume();if(!boundary.frozen){drafts.resume();freezeEditing(false);}};
      } catch(error) {
        if(!boundary.frozen){drafts.resume();freezeEditing(false);}
        throw error;
      }
    },
    async onSessionRotated({session:next,preserveUnsavedInputs=false}) {
      boundary.hold();drafts.pause();freezeEditing(true);
      if(!preserveUnsavedInputs){reloadWorkspace();return;}
      // Retain old-tenant input locally and visibly; never write it with the new Cookie.
      await workflow.flushDrafts();
      const previous=JSON.parse(localStorage.getItem(drafts.accountKey)||'null') || {};
      previous.draft=accounts.getDraftSelection();localStorage.setItem(drafts.accountKey,JSON.stringify(previous));
      accounts.unmount();updates?.unmount();if(accountDialog.open)accountDialog.close();
      display('会话已在别处改变。本页输入已保留在原工作区的浏览器草稿中；请核对后载入当前工作区。');
      const button=document.createElement('button');button.type='button';button.textContent='保留本页草稿并载入当前工作区';
      button.addEventListener('click',reloadWorkspace,{once:true});status.append(button);
      accountButton.disabled=true;
      // The owner module is unmounted, so it cannot emit events into the retained editor.
    },
    async bootstrapSession() {
      // Freeze old requests before intentionally creating an empty anonymous workspace.
      drafts?.pause();freezeEditing(true);boundary.hold();
      return transport.bootstrapAnonymousSession();
    },
  };
}

try {
  session=await api.request('/session');
  shell=mountShell({root:document,events,session});
  drafts=new DraftCoordinator({api,storage:localStorage,tenantId:session.tenant.id,apiBase:config.apiBase,onState:state=>{
    if(readOnly) return;
    display(state.error || (state.hasPending() ? '草稿待保存到当前工作区…' : '当前草稿已保存到工作区。'));
    const label=document.getElementById('saveStatus'); if(label)label.textContent=state.error?'草稿待处理':state.hasPending()?'正在保存草稿':'草稿已保存';
  }});
  await drafts.load();
  accounts=mountAccounts({root:document.getElementById('account-root'),api,events,session,publicBasePath:config.publicBasePath,workspaceRecovery:workspaceRecoveryHooks(),localClient:config.mode==='local-client'});
  drafts.readAccountDraft=()=>accounts.getDraftSelection();
  workflow=mountWorkflow({root:document.getElementById('workflow-root'),api,events,session,...config,storage:drafts.adapter});
  await Promise.all([accounts.ready,workflow.ready]);
  if(config.mode==='local-client') {
    const authorize=document.createElement('button');authorize.type='button';authorize.className='lab-button integration-account-trigger';authorize.textContent='授权 LibTV';
    accountButton.before(authorize);
    authorize.addEventListener('click',()=>{openAccounts();void accounts.authorize();});
  }
  drafts.onState(drafts);
  if(workflow.getState().projectId || Object.keys(drafts.snapshot().workflow).some(key=>key==='new-project'||key.startsWith('plan:'))) shell.setView({workspaceState:'ready'});
  document.querySelectorAll('#workflow-root,#account-root').forEach(root=>{
    for(const type of ['input','change']) root.addEventListener(type,()=>queueMicrotask(()=>drafts.changed()));
  });
  await refreshTasks();
  document.getElementById('update-root').replaceChildren();
  if(config.mode==='local-client') {
    const root=document.getElementById('update-root');
    const note=document.createElement('p');note.textContent='本地连接预览 '+currentBuild.version+' · 仅开放 LibTV 账号读取，生成和自动安装更新尚未开放。';
    const stop=document.createElement('button');stop.type='button';stop.textContent='退出本地工作台';
    stop.addEventListener('click',async()=>{
      stop.disabled=true;
      try {
        const saved=await saveDraft();const safe=await safety();
        if(saved?.saved!==true||safe.hasUnsavedChanges||safe.activeTasks||safe.activeDownloads)throw new Error('请先完成保存、授权或运行中的任务，再退出。');
        await api.request('/local-runtime/stop',{method:'POST',body:{}});
        switchingWorkspace=true;drafts.destroy();workflow.unmount();accounts.unmount();freezeEditing(true);
        root.inert=false;
        note.textContent='本地工作台已退出。再次双击启动即可继续。';
        display(note.textContent);
      } catch(error){display(error.message);stop.disabled=false;}
    });
    root.append(note,stop);
  } else {
    updates=mountUpdates({root:document.getElementById('update-root'),api,events,session,currentBuild,getSafetyState:safety,saveDraft,publicBasePath:config.publicBasePath});
  }
  window.addEventListener('beforeunload',event=>{if(!switchingWorkspace && (drafts.hasPending() || pendingWrites || activeDownloads)){event.preventDefault();event.returnValue='';}});
  if(!drafts.conflict) void drafts.save().catch(()=>{});
} catch(error) {
  display(error.message || '工作区暂时无法载入，请稍后重试。'); save.disabled=true;
  document.getElementById('workflow-root').textContent='工作区未能载入，现有数据未被替换。';
  if(error.code==='SESSION_REQUIRED') {
    display('本站会话已失效。原工作区数据仍保留；建立新的临时工作区不会恢复或合并旧内容。');
    const button=document.createElement('button');button.type='button';button.textContent='建立新的临时工作区';
    button.addEventListener('click',async()=>{
      button.disabled=true;
      try {await transport.bootstrapAnonymousSession();switchingWorkspace=true;location.assign(config.publicBasePath);}
      catch(problem){display(problem.message || '临时工作区尚未建立，请稍后重试。');button.disabled=false;}
    });status.append(button);
  }
}
