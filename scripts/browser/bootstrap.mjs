import {createApiClient, ApiError} from '../api-client.js';
import {mount as mountShell} from '../shell/index.js';
import {mount as mountAccounts} from '../accounts/index.js';
import {mount as mountWorkflow} from '../asset-lab.js';
import {mount as mountUpdates} from '../updates/index.js';
import {DraftCoordinator} from './drafts.mjs';
import {mountLocalWorkspace} from './local-workspace.mjs';
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
const balanceButton=document.createElement('button');balanceButton.type='button';balanceButton.className='lab-button integration-account-trigger';balanceButton.textContent='查询余额';balanceButton.disabled=true;
accountButton.before(balanceButton);
balanceButton.addEventListener('click',()=>{openAccounts();const quota=accountRoot.querySelector('[data-view="quota"]');quota?.scrollIntoView({block:'center'});accountRoot.querySelector('[data-action="quota"]')?.focus();void accounts?.queryQuota();});
accountDialog.addEventListener('close',()=>accountButton.focus());
let readOnly = false, activeDownloads = 0, pendingWrites = 0, switchingWorkspace=false;
let workflow, accounts, drafts, shell, session, updates, localWorkspace;
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
  const downloading = options.responseType === 'blob';
  if (downloading) activeDownloads++;
  try { return await boundary.api.request(path,options); }
  finally { if(write) pendingWrites--; if(downloading) activeDownloads--; }
}};

async function saveDraft() {
  await workflow?.flushDrafts(); await accounts?.flush();
  return drafts.save({force:true});
}
save.addEventListener('click', () => saveDraft().then(result => {
  display(result.saved ? '草稿已保存到当前工作区。' : '刚才的草稿已保存，最新输入仍在保存中。');
}).catch(error => display(error.message)));

const running = new Set(['preparing','submitting','submitted','queued','running','downloading']);
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
  if(!root.childElementCount){const pending=document.createElement('p');pending.textContent='正在读取任务状态…';const bar=document.createElement('progress');bar.setAttribute('aria-label','正在读取任务状态');root.replaceChildren(pending,bar);}
  try {
    const allTasks = await listAllTasks(), projectId=workflow?.getState().projectId;
    const tasks=allTasks.filter(task=>!projectId||task.projectId===projectId).sort((a,b)=>a.createdAt.localeCompare(b.createdAt)); root.replaceChildren();
    const count = tasks.filter(task=>running.has(task.status)).length;
    document.getElementById('taskCount').textContent = String(count);
    const note = document.createElement('p'); note.className='integration-task-note';
    note.textContent = tasks.length ? `共 ${tasks.length} 个任务，${count} 个正在处理。` : '还没有任务。准备或生成后的记录会保留在这里。';
    root.append(note);
    for (const task of tasks.slice(-20).reverse()) {
      const item=document.createElement('div'); item.className='integration-task';
      const label=document.createElement('strong'); label.textContent=({mj_style:'MJ 风格',image2_asset:'Image2 资产',nano_refine:'Nano 精修',storyboard_image:'分镜图'}[task.recipe]||task.recipe)+' · '+({draft:'待确认',preparing:'准备中',submitting:'正在提交',submitted:'已提交，等待生成',queued:'排队中',running:'生成中',downloading:'收取中',completed:'文件已收取',needs_attention:'待处理',blocked_authorization:'需原账号授权',failed:'失败',cancelled:'已取消',unknown_submission:'提交状态待核验'}[task.status] || task.status);
      const owner=document.createElement('small'); owner.textContent=(task.ownership.accountLabelAtCreation || task.ownership.providerAccountId)+' / '+(task.ownership.spaceNameAtCreation || task.ownership.spaceId);
      item.append(label,owner);
      const open=document.createElement('button');open.textContent=task.status==='completed'?'查看返回图片':'定位任务档案';open.addEventListener('click',()=>{shell.closePanel('activity');events.dispatchEvent(new CustomEvent('workflow:open-task',{detail:{task}}));});item.append(open);
      if(running.has(task.status)){const bar=document.createElement('progress');bar.setAttribute('aria-label','任务处理中，等待实际结果');bar.style.width='100%';item.append(bar);}
      const time=document.createElement('small');time.textContent='最近状态：'+new Date(task.updatedAt).toLocaleTimeString();item.append(time);
      if(task.error?.message){const error=document.createElement('p');error.textContent=task.error.message;item.append(error);}
      if(task.canRecover) {const button=document.createElement('button');button.textContent='查询原任务并收取';button.addEventListener('click',async()=>{button.disabled=true;try{await api.request(`/tasks/${encodeURIComponent(task.id)}/recover`,{method:'POST',body:{expectedVersion:task.version}});events.dispatchEvent(new CustomEvent('tasks:changed'));}catch(error){display(error.message);}finally{button.disabled=false;}});item.append(button);}
      root.append(item);
    }
  } catch(error) {root.textContent='任务状态暂时无法读取；刷新更新将保持锁定。';}
}

// ZIP fetches go through the authenticated transport and are counted until body receipt.
document.addEventListener('click', async event => {
  const link=event.target.closest('a[href]'); if(!link || link.hasAttribute('data-wf-download') || event.defaultPrevented || event.button!==0) return;
  const url=new URL(link.href);
  if(url.origin!==location.origin || !url.pathname.startsWith(config.apiBase+'/') || !(/\/projects\/[^/]+\/export$/.test(url.pathname)||/\/bundles\/[^/]+\/content$/.test(url.pathname))) return;
  event.preventDefault();
  try {
    const blob=await api.request(url.pathname.slice(config.apiBase.length)+url.search,{responseType:'blob'});
    const object=URL.createObjectURL(blob), anchor=document.createElement('a'); anchor.href=object;anchor.download='资产实验室交付包.zip';document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(object),60000);
  } catch(error) {display(error.message);}
},true);

events.addEventListener('release:changed', event=>{
  if(event.detail.compatibleNow===false){readOnly=true;document.body.dataset.readOnly='true';display('页面与服务版本不兼容，当前处于只读状态；输入可继续保留为草稿。');}
  else if(event.detail.compatibleNow===true && readOnly){readOnly=false;delete document.body.dataset.readOnly;drafts?.onState(drafts);}
});
events.addEventListener('shell:action',event=>{
  if(event.detail.action==='connect'){event.preventDefault();openAccounts();}
  if(event.detail.action==='manual-plan')shell.setView({workspaceState:'ready'});
  if(event.detail.action==='help'){
    event.preventDefault();const dialog=document.getElementById('shell-info-dialog');
    document.getElementById('shell-info-title').textContent='使用资产实验室';
    const body=document.getElementById('shell-info-body');body.replaceChildren();
    for(const text of ['粘贴剧本或导入 TXT、Markdown、DOCX，点击开始制作。原文保存后由 AI 分析人物、场景、时间、地点、事件和台词，核对后整理制作清单。',
      '工作区主所有者用于找回本站资料；创作账号与个人、团队空间用于明确新任务归属。切换选择不会改动历史任务。',
      '制作顺序是剧本分析 → MJ 风格探索与确认 → Image2 规范资产 → 导演编排 → 审核交付。Nano 是资产内的可选精修；返修始终追溯原始 Image2。',
      '下载只包含已审核的成果。更新页面会先保存草稿，处理中的任务或下载会阻止刷新。',
      config.mode==='local-client'
        ? session?.features?.imageGeneration
          ? '首次连接读取账号信息；制作需要在账号管理中另行开启创作权限。点击确认后才会使用 LibTV 积分生成图片；视频生成仍暂停。'
          : '首次连接读取账号信息。本次启动尚未启用图片生成，剧本和草稿可以正常保存；视频生成仍暂停。'
        : '当前为集成预览，可以整理项目与保存草稿。官方连接、收费生成和视频尚未开放。']){
      const paragraph=document.createElement('p');paragraph.textContent=text;body.append(paragraph);
    }
    if(!dialog.open)dialog.showModal();
  }
});
events.addEventListener('workflow:connect',()=>openAccounts());
events.addEventListener('provider-accounts:changed',event=>{
  const items=event.detail.items || [], connected=items.some(item=>item.authorization?.state==='connected');
  shell.setView({connectionState:connected?'connected':'disconnected'});
  const trigger=document.getElementById('local-libtv-status');
  if(trigger)trigger.textContent=connected?'LibTV 已连接':'连接 LibTV';
});
events.addEventListener('tasks:changed',()=>void refreshTasks());
events.addEventListener('workflow:tasks-refreshed',()=>void refreshTasks());

function reloadWorkspace() {
  switchingWorkspace=true;drafts?.destroy();workflow?.unmount();accounts?.unmount();updates?.unmount();localWorkspace?.unmount();
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
  if(config.mode==='local-client') {
    const authorize=document.createElement('button');authorize.type='button';authorize.id='local-libtv-status';authorize.className='lab-button integration-account-trigger';authorize.textContent='正在读取 LibTV 状态';
    accountButton.before(authorize);
    authorize.addEventListener('click',()=>openAccounts());
  }
  await Promise.all([accounts.ready,workflow.ready,refreshTasks()]);
  balanceButton.disabled=false;
  if(config.mode==='local-client') {
    localWorkspace=mountLocalWorkspace({anchor:accountRoot,api,saveDrafts:saveDraft,
      beforeSwitch:()=>workspaceRecoveryHooks().beforeSessionRotation(),
      onSwitched:()=>{boundary.hold();reloadWorkspace();},reload:reloadWorkspace});
  }
  const connectionStatus=document.getElementById('local-libtv-status');
  if(connectionStatus)connectionStatus.textContent=accounts.hasConnectedAccount()?'LibTV 已连接':'连接 LibTV';
  drafts.onState(drafts);
  if(workflow.getState().projectId || Object.keys(drafts.snapshot().workflow).some(key=>key==='new-project'||key.startsWith('plan:'))) shell.setView({workspaceState:'ready'});
  document.querySelectorAll('#workflow-root,#account-root').forEach(root=>{
    for(const type of ['input','change']) root.addEventListener(type,()=>queueMicrotask(()=>drafts.changed()));
  });
  document.getElementById('update-root').replaceChildren();
  if(config.mode==='local-client') {
    const root=document.getElementById('update-root');
    const note=document.createElement('p');note.textContent='本地工作台 '+currentBuild.version+' · 支持剧本初稿拆解；首次制作需连接 LibTV 并授予创作权限；图片结果逐步审核与保存。';
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
