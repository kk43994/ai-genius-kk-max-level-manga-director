import test from 'node:test';
import assert from 'node:assert/strict';
import {DraftCoordinator} from '../../scripts/browser/drafts.mjs';

function setup(record={version:0,content:{workflow:{},accountSelection:null}}) {
  const values=new Map();const storage={getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
  let resolve, calls=[];
  const api={request:async(path,options)=>{if(!options)return structuredClone(record);calls.push(options);return new Promise(r=>resolve=r);}};
  const drafts=new DraftCoordinator({api,storage,tenantId:'tenant-synthetic',apiBase:'/asset-lab/api/v1'});
  return {drafts,storage,calls,ack:version=>resolve({saved:true,version,savedDrafts:[{collection:'drafts',id:'browser_drafts_v1',version}]})};
}
test('new project and review drafts need the real server acknowledgement',async()=>{
  const f=setup();await f.drafts.load();f.storage.setItem(f.drafts.workflowKey,JSON.stringify({'new-project':{name:'未提交'},'review:r':{note:'保留'}}));
  assert.equal(f.drafts.hasPending(),true);const saving=f.drafts.save();assert.equal(f.drafts.hasPending(),true);
  f.ack(1);assert.equal((await saving).saved,true);assert.equal(f.drafts.hasPending(),false);assert.equal(f.calls[0].body.content.workflow['new-project'].name,'未提交');f.drafts.destroy();
});
test('typing while a save is in flight never becomes safe to reload',async()=>{
  const f=setup();await f.drafts.load();f.storage.setItem(f.drafts.workflowKey,JSON.stringify({'new-project':{name:'旧'}}));const saving=f.drafts.save();
  f.storage.setItem(f.drafts.workflowKey,JSON.stringify({'new-project':{name:'新'}}));f.ack(1);assert.equal((await saving).saved,false);assert.equal(f.drafts.hasPending(),true);f.drafts.destroy();
});
test('server draft restores when no browser draft exists',async()=>{
  const content={workflow:{'new-project':{name:'服务器草稿'}},accountSelection:{providerAccountId:'pa-synthetic',spaceId:'space-synthetic'}};
  const f=setup({version:4,content});await f.drafts.load();assert.deepEqual(f.drafts.snapshot(),content);assert.equal(f.drafts.hasPending(),false);f.drafts.destroy();
});
test('newer server draft conflicts preserve both copies',async()=>{
  const f=setup({version:3,content:{workflow:{'new-project':{name:'另一页面'}},accountSelection:null}});
  f.storage.setItem(f.drafts.workflowKey,JSON.stringify({'new-project':{name:'本地未保存'}}));await f.drafts.load();
  assert.equal(f.drafts.snapshot().workflow['new-project'].name,'本地未保存');await assert.rejects(f.drafts.save());assert.equal(f.calls.length,0);f.drafts.destroy();
});
test('account authorization attempts and URLs are excluded from draft persistence',async()=>{
  const f=setup();await f.drafts.load();f.storage.setItem(f.drafts.accountKey,JSON.stringify({draft:{providerAccountId:'pa',spaceId:'sp'},attempt:{authorizationUrl:'never-persist-this'}}));
  const saving=f.drafts.save();f.ack(1);await saving;assert.deepEqual(f.calls[0].body.content.accountSelection,{providerAccountId:'pa',spaceId:'sp'});assert.equal(JSON.stringify(f.calls).includes('never-persist-this'),false);f.drafts.destroy();
});
test('opening an empty customer page does not create false workspace content',async()=>{
  const f=setup();await f.drafts.load();f.storage.setItem(f.drafts.workflowKey,JSON.stringify({page:'plan',selectedProject:''}));
  f.storage.setItem(f.drafts.accountKey,JSON.stringify({draft:{providerAccountId:null,spaceId:null}}));
  assert.equal(f.drafts.hasPending(),false);assert.deepEqual(await f.drafts.save(),{saved:true,savedDrafts:[]});assert.equal(f.calls.length,0);f.drafts.destroy();
});
test('owner confirmation can request a fresh durable draft receipt',async()=>{
  const content={workflow:{'new-project':{name:'已保存草稿'}},accountSelection:null};
  const f=setup({version:4,content});await f.drafts.load();const saving=f.drafts.save({force:true});
  assert.equal(f.calls[0].body.expectedVersion,4);f.ack(5);assert.equal((await saving).savedDrafts[0].version,5);f.drafts.destroy();
});
test('live account input is saved even if optional account cache did not update',async()=>{
  const f=setup();await f.drafts.load();
  f.drafts.readAccountDraft=()=>({providerAccountId:'live-account',spaceId:'live-space'});
  assert.equal(f.storage.getItem(f.drafts.accountKey),null);assert.equal(f.drafts.hasPending(),true);
  const saving=f.drafts.save();f.ack(1);await saving;
  assert.deepEqual(f.calls[0].body.content.accountSelection,{providerAccountId:'live-account',spaceId:'live-space'});f.drafts.destroy();
});
test('paused old workspace cannot autosave with a rotated Cookie',async()=>{
  const f=setup();await f.drafts.load();f.drafts.pause();
  await assert.rejects(f.drafts.save({force:true}),/暂停提交/);assert.equal(f.calls.length,0);f.drafts.destroy();
});
test('pasted script alone counts as unsaved content before a project exists',async()=>{
 const f=setup();await f.drafts.load();f.storage.setItem(f.drafts.workflowKey,JSON.stringify({'quick-start':{text:'尚未开始的剧本',idempotencyKey:'draft-one'}}));
 assert.equal(f.drafts.hasContent(),true);assert.equal(f.drafts.hasPending(),true);
 const saving=f.drafts.save();f.ack(1);await saving;assert.equal(f.drafts.hasPending(),false);f.drafts.destroy();
});
