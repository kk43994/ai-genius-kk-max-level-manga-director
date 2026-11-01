import test from 'node:test';
import assert from 'node:assert/strict';
import {canAutoCollect,nextCollection,collectionDelay,collectionOwnerKey} from '../../frontend/workflow/collection.js';
const task=(extra={})=>({id:'task-a',createdAt:'2026-11-01',status:'queued',submissionAttempted:true,canRecover:true,providerReceipt:{taskId:'original-receipt'},...extra});
test('known receipts collect without depending on selected account, guide or workflow drafts',()=>{
 for(const status of ['queued','running','submitted','downloading','submitting'])assert.ok(canAutoCollect(task({status})));
 assert.ok(canAutoCollect(task({status:'needs_attention',error:{code:'DELIVERY_UNCONFIRMED'}})));
 assert.ok(canAutoCollect(task({status:'needs_attention',error:{code:'SUBMISSION_UNKNOWN'}})));
 assert.equal(nextCollection([task()],new Map(),100).task.id,'task-a');
});
test('no new generation, unknown receipt, auth failure, ownership conflict or completed task can auto-collect',()=>{
 for(const patch of [{submissionAttempted:false},{canRecover:false},{providerReceipt:{nodeId:'node'}},
   {status:'completed'},{status:'failed'},{status:'cancelled'},{status:'draft'},{status:'blocked_authorization'},
   {status:'needs_attention',error:{code:'PROVIDER_RECEIPT_MISMATCH'}},{status:'needs_attention',error:{code:'WORKFLOW_VERSION_CHANGED'}}])assert.equal(canAutoCollect(task(patch)),false);
});
test('collection is fair across tasks and transient failures back off',()=>{
 const attempts=new Map([['task-a',{due:50000}]]);
 const selected=nextCollection([task(),task({id:'task-b'})],attempts,1000);
 assert.equal(selected.task.id,'task-b');assert.equal(selected.due,9000);
 assert.equal(collectionDelay(task()),8000);assert.equal(collectionDelay(task({status:'needs_attention'})),30000);
});
test('account read outage cools down all original tasks of that owner but not another owner',()=>{
 const first=task({ownership:{tenantId:'t',providerAccountId:'a',spaceId:'s'},status:'needs_attention',error:{code:'PROVIDER_ACCOUNT_READ_UNAVAILABLE'}});
 const second={...first,id:'task-b'}, other={...first,id:'task-c',ownership:{...first.ownership,providerAccountId:'b'}};
 const attempts=new Map([[collectionOwnerKey(first),{due:61000}],[other.id,{due:2000}]]);
 assert.ok(canAutoCollect(first)); assert.equal(collectionDelay(first),60000);
 assert.equal(nextCollection([first,second],attempts,1000).due,61000);
 assert.equal(nextCollection([first,second,other],attempts,1000).task.id,'task-c');
 assert.equal(canAutoCollect({...first,providerReceipt:{}}),false);
});

test('a completed task with a not-yet-visible asset keeps refreshing until images arrive',async()=>{
 const {needsAssetRefresh}=await import('../../frontend/workflow/collection.js');
 const completed=task({status:'completed',outputs:[{revisionId:'r1'},{revisionId:'r2'}]});
 assert.ok(needsAssetRefresh([completed],[]));
 assert.ok(needsAssetRefresh([completed],[{revisions:[{id:'r1'}]}]));
 assert.equal(needsAssetRefresh([completed],[{revisions:[{id:'r1'},{id:'r2'}]}]),false);
 assert.equal(needsAssetRefresh([task()],[]),false);
});
