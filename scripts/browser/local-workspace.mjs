/** The browser can request/consume a handoff, never approve its destination. */
export function mountLocalWorkspace({anchor,api,saveDrafts,beforeSwitch,onSwitched,reload}) {
  const doc=anchor.ownerDocument;
  const trigger=doc.createElement('button');trigger.type='button';trigger.className='lab-button';
  trigger.textContent='切换本机工作区';anchor.before(trigger);
  const dialog=doc.createElement('dialog');dialog.className='integration-account-dialog';
  dialog.setAttribute('aria-label','切换本机工作区');
  dialog.innerHTML='<h2>切换本机工作区</h2><p>当前草稿会先保存，目标工作区由这台电脑本地确认。两个工作区的项目和素材分别保留。</p><p data-local-switch-status role="status" aria-live="polite">准备后，在本机确认需要打开的项目。</p><progress aria-label="等待本机确认工作区" hidden></progress><div class="wf-actions"><button type="button" data-local-switch-start>保存草稿并准备切换</button><button type="button" data-local-switch-check hidden>检查本机确认</button><button type="button" data-local-switch-confirm hidden></button><button type="button" data-local-switch-close>暂不切换</button><button type="button" data-local-switch-reload hidden>重新载入工作台</button></div>';
  doc.body.append(dialog);
  const status=dialog.querySelector('[data-local-switch-status]'),bar=dialog.querySelector('progress');
  const start=dialog.querySelector('[data-local-switch-start]'),check=dialog.querySelector('[data-local-switch-check]');
  const confirm=dialog.querySelector('[data-local-switch-confirm]'),close=dialog.querySelector('[data-local-switch-close]');
  const reloadButton=dialog.querySelector('[data-local-switch-reload]');
  let intent=null,busy=false,timer=null,uncertain=false;
  function render() {
    start.hidden=Boolean(intent);check.hidden=!intent||uncertain;
    confirm.hidden=intent?.status!=='approved'||uncertain;confirm.textContent=`进入「${intent?.projectName||''}」工作区`;
    for(const button of [start,check,confirm,close])button.disabled=busy||uncertain;
    bar.hidden=intent?.status!=='pending'||uncertain;reloadButton.hidden=!uncertain;
    if(intent)dialog.dataset.localSwitchId=intent.id;else delete dialog.dataset.localSwitchId;
  }
  async function refresh() {
    if(!intent||busy||uncertain)return;
    busy=true;render();
    try {
      intent=await api.request(`/local-workspace-intents/${encodeURIComponent(intent.id)}`);
      status.textContent=intent.status==='approved'?`已在本机确认目标：${intent.projectName}。点击下方按钮进入，当前工作区会保留。`:'正在等待本机确认目标工作区…';
    } catch(error) {clearInterval(timer);status.textContent=error.message;bar.hidden=true;}
    finally {busy=false;render();}
  }
  trigger.addEventListener('click',()=>{if(!dialog.open)dialog.showModal();});
  start.addEventListener('click',async()=>{
    if(busy)return;busy=true;render();status.textContent='正在保存当前工作区的草稿…';
    try {
      const saved=await saveDrafts();if(!saved.saved)throw new Error('有新的编辑内容，请保存后再切换。');
      intent=await api.request('/local-workspace-intents',{method:'POST',body:{confirmLocalSwitch:true}});
      status.textContent='草稿已保存，正在等待本机确认目标工作区…';
      clearInterval(timer);timer=setInterval(refresh,2500);
    } catch(error) {status.textContent=error.message;}
    finally {busy=false;render();}
  });
  check.addEventListener('click',refresh);
  confirm.addEventListener('click',async()=>{
    if(busy||intent?.status!=='approved')return;busy=true;clearInterval(timer);render();
    let frozen=false;
    try {
      const saved=await saveDrafts();if(!saved.saved)throw new Error('有新的编辑内容，请保存后再切换。');
      const reference=saved.savedDrafts?.find(item=>item.collection==='drafts'&&item.id==='browser_drafts_v1');
      if(!reference)throw new Error('当前草稿尚未收到保存确认。');
      await beforeSwitch();frozen=true;
      const result=await api.request(`/local-workspace-intents/${encodeURIComponent(intent.id)}/confirm`,
        {method:'POST',body:{expectedVersion:intent.version,savedDraftVersion:reference.version}});
      if(result.switched!==true)throw new Error('切换结果尚未确认。');
      status.textContent=`已切换到 ${result.projectName}，正在载入…`;await onSwitched(result);
    } catch(error) {
      uncertain=frozen;
      status.textContent=frozen?'切换结果需要重新核对。当前草稿已经保存，请重新载入工作台。':error.message;
    } finally {busy=false;render();}
  });
  close.addEventListener('click',async()=>{
    if(busy||uncertain)return;busy=true;clearInterval(timer);render();
    try {
      if(intent&&['pending','approved'].includes(intent.status))await api.request(`/local-workspace-intents/${encodeURIComponent(intent.id)}/cancel`,{method:'POST',body:{}});
      intent=null;dialog.close();status.textContent='准备后，在本机确认需要打开的项目。';
    } catch(error) {status.textContent=error.message;}
    finally {busy=false;render();}
  });
  dialog.addEventListener('cancel',event=>{event.preventDefault();close.click();});
  reloadButton.addEventListener('click',reload);
  return {unmount(){clearInterval(timer);trigger.remove();dialog.remove();}};
}
