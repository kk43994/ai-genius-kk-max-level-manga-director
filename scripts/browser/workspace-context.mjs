const control = path => /^\/(session(?:\?|$)|workspace-intents\/|local-workspace-intents\/|authorization-attempts\/)/.test(path);
const failure = () => Object.assign(new Error('工作区会话正在同步，原工作区请求已暂停。'),{code:'WORKSPACE_CONTEXT_CHANGED'});

/** Retire responses and writes tied to the old Cookie context before UI replacement. */
export function createSessionBoundary(transport, {onChanged=()=>{}}={}) {
  let sessionId=null, epoch=0, phase='open';
  const pending=new Set();
  const api={...transport, async request(path,options={}) {
    if(phase!=='open' && !control(path)) throw failure();
    const token=epoch;
    const promise=transport.request(path,{...options,expectedSessionId:sessionId});
    pending.add(promise);
    try {
      const result=await promise;
      if(token!==epoch) throw failure();
      if(path.split('?')[0]==='/session' && result?.session?.id) {
        if(sessionId && result.session.id!==sessionId) {
          phase='changed';epoch++;onChanged(result);
        } else sessionId=result.session.id;
      }
      return result;
    } finally {pending.delete(promise);}
  }};
  return {api,
    async freeze({timeout=10000}={}) {
      if(phase!=='open') throw failure();
      phase='frozen';const token=epoch;
      let timer;
      try {
        await Promise.race([Promise.allSettled([...pending]),new Promise((_,reject)=>{
          timer=setTimeout(()=>reject(new Error('当前请求尚未结束，请稍后再确认工作区。')),timeout);
        })]);
        if(token!==epoch) throw failure();
      } catch(error) {if(token===epoch)phase='open';throw error;}
      finally{clearTimeout(timer);}
      return ()=>{if(token===epoch && phase==='frozen')phase='open';};
    },
    hold(){phase='changed';epoch++;},
    get frozen(){return phase!=='open';},
  };
}

/** Owner inspection excludes the owner dialog's own pending/confirmation state. */
export function inspectWorkspaceDrafts({workflow,drafts,pendingWrites=0}) {
  const state=workflow?.getState();
  if(!state || !drafts) return {hasUnsavedChanges:null,items:[]};
  const items=[];
  if(drafts.hasPending())items.push({label:'项目、资产或账号选择仍有草稿等待服务器保存'});
  if(state.saveError)items.push({label:state.saveError});
  if(state.busy || pendingWrites)items.push({label:'当前工作区请求尚未结束'});
  return {hasUnsavedChanges:items.length>0,items};
}

export async function saveWorkspaceDrafts({workflow,drafts}) {
  await workflow.flushDrafts();
  const result=await drafts.save({force:true});
  if(!result.saved)throw new Error('保存期间出现了新输入，请再次保存后确认。');
  return result;
}
