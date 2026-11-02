export function mountLocalUpdates({root,api,saveDraft,getSafetyState,onInstalling}){
 const doc=root.ownerDocument,section=doc.createElement('section');section.setAttribute('aria-label','桌面自动更新');
 const label=doc.createElement('label'),enabled=doc.createElement('input');enabled.type='checkbox';
 label.append(enabled,' 自动检查并下载更新');
 const status=doc.createElement('span');status.setAttribute('role','status');
 const check=doc.createElement('button');check.type='button';check.textContent='检查更新';
 const install=doc.createElement('button');install.type='button';install.textContent='保存并安装更新';install.hidden=true;
 const website=doc.createElement('a');website.href='https://kk666.best/asset-lab/';website.target='_blank';website.rel='noopener';website.textContent='官方下载页';
 section.append(label,status,check,install,website);root.append(section);
 const notice=doc.createElement('aside');notice.className='local-update-notice';notice.hidden=true;
 notice.setAttribute('aria-label','发现新版本');notice.setAttribute('aria-live','polite');
 const title=doc.createElement('strong'),message=doc.createElement('p');
 const noticeInstall=doc.createElement('button');noticeInstall.type='button';noticeInstall.textContent='保存并安装新版';
 const later=doc.createElement('button');later.type='button';later.textContent='稍后提醒';
 notice.append(title,message,noticeInstall,later);root.append(notice);
 let alive=true,busy=false,timer,lastState,dismissedVersion;
 later.addEventListener('click',()=>{dismissedVersion=lastState?.latestVersion;notice.hidden=true;});
 const render=state=>{
  lastState=state;
  enabled.checked=state.enabled;enabled.disabled=busy;
  status.textContent=state.message+(state.latestVersion?' · 发布版本 '+state.latestVersion:'');
  check.disabled=busy||['checking','downloading','installing'].includes(state.status);
  install.hidden=!state.canInstall;install.disabled=busy;
  notice.hidden=!['downloading','ready'].includes(state.status)||!state.latestVersion||dismissedVersion===state.latestVersion;
  title.textContent='检测到新版本 '+(state.latestVersion||'');message.textContent=state.message;
  noticeInstall.hidden=!state.canInstall;noticeInstall.disabled=busy;
 };
 async function request(action,body){
  if(busy)return;
  busy=true;check.disabled=true;enabled.disabled=true;install.disabled=true;
  let failure;
  try{const state=await api.request('/local-runtime/update'+action,{method:'POST',body});if(alive)render(state);}
  catch(error){failure=error.message;}
  finally{busy=false;if(alive&&lastState)render(lastState);if(alive&&failure)status.textContent=failure;}
 }
 check.addEventListener('click',()=>{dismissedVersion=undefined;return request('/check',{});});
 enabled.addEventListener('change',()=>request('/settings',{enabled:enabled.checked}));
 async function installUpdate(){
  if(busy)return;busy=true;install.disabled=true;noticeInstall.disabled=true;
  try{
   const saved=await saveDraft(),safe=await getSafetyState();
   if(saved?.saved!==true||safe.hasUnsavedChanges||safe.activeTasks||safe.activeDownloads)throw new Error('请先完成保存、授权或运行中的任务，再安装更新。');
   const state=await api.request('/local-runtime/update/install',{method:'POST',body:{}});
   render(state);clearTimeout(timer);onInstalling(state.message);
  }catch(error){status.textContent=error.message;message.textContent=error.message;busy=false;install.disabled=false;noticeInstall.disabled=false;}
 }
 install.addEventListener('click',installUpdate);noticeInstall.addEventListener('click',installUpdate);
 async function refresh(){
  try{const state=await api.request('/local-runtime/update');if(alive&&!busy)render(state);}
  catch(error){if(alive)status.textContent=error.message;}
  finally{if(alive)timer=setTimeout(refresh,10000);}
 }
 void refresh();
 return {unmount(){alive=false;clearTimeout(timer);section.remove();notice.remove();}};
}
