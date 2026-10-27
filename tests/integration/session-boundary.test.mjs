import test from 'node:test';
import assert from 'node:assert/strict';
import {createSessionBoundary,inspectWorkspaceDrafts,saveWorkspaceDrafts} from '../../scripts/browser/session-boundary.mjs';

test('rotation waits for existing writes and blocks new business writes but allows confirmation',async()=>{
  let finish;const calls=[];
  const boundary=createSessionBoundary({request:async(path,options)=>{
    calls.push({path,options});if(path==='/session')return {session:{id:'old'}};
    if(path==='/projects')return new Promise(resolve=>finish=resolve);return {};
  }});
  await boundary.api.request('/session');
  const pending=boundary.api.request('/projects',{method:'POST'});
  let frozen=false;const freezing=boundary.freeze().then(value=>{frozen=true;return value;});
  await assert.rejects(boundary.api.request('/drafts/browser',{method:'PUT'}),{code:'WORKSPACE_CONTEXT_CHANGED'});
  assert.equal(frozen,false);finish({id:'saved-in-old'});await pending;const resume=await freezing;
  await boundary.api.request('/workspace-intents/intent/confirm',{method:'POST'});
  assert.equal(calls.at(-1).options.expectedSessionId,'old');resume();assert.equal(boundary.frozen,false);
});

test('new session in the same tenant retires old responses and never relabels old requests',async()=>{
  let session='old',finish;const calls=[];let detected=0;
  const boundary=createSessionBoundary({request:async(path,options)=>{
    calls.push({path,options});if(path==='/session')return {session:{id:session},tenant:{id:'same-tenant'}};
    return new Promise(resolve=>finish=resolve);
  }},{onChanged:()=>detected++});
  await boundary.api.request('/session');const pending=boundary.api.request('/projects');
  session='new';await boundary.api.request('/session');finish({items:[{id:'old-context'}]});
  await assert.rejects(pending,{code:'WORKSPACE_CONTEXT_CHANGED'});
  await assert.rejects(boundary.api.request('/projects',{method:'POST'}),{code:'WORKSPACE_CONTEXT_CHANGED'});
  assert.equal(detected,1);assert.equal(calls.length,3);assert.equal(calls[1].options.expectedSessionId,'old');
});

test('owner inspection ignores its own confirmation state and saving rejects concurrent typing',async()=>{
  let flushed=0;
  const workflow={getState:()=>({busy:false,saveError:''}),flushDrafts:async()=>flushed++};
  const drafts={hasPending:()=>false,save:async({force})=>({saved:!force,savedDrafts:[]})};
  assert.deepEqual(inspectWorkspaceDrafts({workflow,drafts}),{hasUnsavedChanges:false,items:[]});
  await assert.rejects(saveWorkspaceDrafts({workflow,drafts}),/新输入/);assert.equal(flushed,1);
  assert.equal(inspectWorkspaceDrafts({workflow,drafts,pendingWrites:1}).hasUnsavedChanges,true);
});
