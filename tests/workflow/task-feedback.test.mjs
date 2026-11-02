import test from 'node:test';
import assert from 'node:assert/strict';
import {currentTaskFeedback,isTaskFailure,taskFailureReason} from '../../frontend/workflow/task-feedback.js';
import {compactTasks} from '../../frontend/workflow/in-place.js';
import {selectedStoryboardShots} from '../../frontend/workflow/generation-batch.js';
const task=(id,status,time,extra={})=>({id,status,createdAt:`2026-11-03T00:00:0${time}Z`,projectId:'p',entityId:'asset',recipe:'image25_asset',ownership:{providerAccountId:'a',spaceId:'s'},submissionAttempted:true,canRecover:status!=='completed',remoteStatus:status,error:{message:'原因 '+id},...extra});
test('only the current failed attempt is shown, and records are not mutated',()=>{
 const rows=[task('older','failed',1),task('latest','failed',2)],before=structuredClone(rows);
 assert.deepEqual(currentTaskFeedback(rows).map(t=>t.id),['latest']);assert.deepEqual(rows,before);
 const html=compactTasks(rows);assert.match(html,/原因 latest/);assert.doesNotMatch(html,/older|取消未提交记录/);
});
test('a newer success or active attempt removes obsolete failure feedback',()=>{
 for(const status of ['completed','running','draft','cancelled']){
  const rows=[task('old','failed',1),task('new',status,2)];
  assert.deepEqual(currentTaskFeedback(rows).map(t=>t.id),['completed','cancelled'].includes(status)?[]:['new']);
 }
});
test('latest is decided by attempt creation, not a late query of an older failure',()=>{
 const old={...task('old','failed',1),updatedAt:'2026-11-03T00:00:09Z'};
 assert.deepEqual(currentTaskFeedback([old,task('new','completed',2)]),[]);
});
test('missing or tied timestamps cannot prove a failed attempt was superseded',()=>{
 const failed={entityId:'asset',status:'failed'},completed={entityId:'asset',status:'completed'};
 assert.deepEqual(currentTaskFeedback([completed,failed]),[failed]);
 assert.deepEqual(currentTaskFeedback([task('success','completed',1),task('failed','failed',1)]).map(t=>t.id),['failed']);
});
test('unknown submissions and partial deliveries stay visible even after another attempt succeeds',()=>{
 for(const status of ['needs_attention','unknown_submission','downloading','blocked_authorization']){
  const uncertain=task('original',status,1,{remoteStatus:'unknown'}),rows=[uncertain,task('new','completed',2)];
  assert.deepEqual(currentTaskFeedback(rows),[uncertain]);
 }
 const unconfirmed=task('original','failed',1,{remoteStatus:'unknown'});
 assert.equal(isTaskFailure(unconfirmed),false);
 assert.equal(currentTaskFeedback([unconfirmed,task('new','completed',2)]).length,1);
});
test('pre-submit failures are summarized while account, space and recipe scopes stay separate',()=>{
 const setup=task('setup','needs_attention',1,{submissionAttempted:false,canRecover:false});
 assert.equal(isTaskFailure(setup),true);
 assert.deepEqual(currentTaskFeedback([setup,task('new','completed',2)]),[]);
 const interrupted=task('setup','failed',1,{remoteStatus:'unknown',error:{details:{generationSubmitted:false}}});
 assert.equal(isTaskFailure(interrupted),true);
 assert.deepEqual(currentTaskFeedback([interrupted,task('new','completed',2)]),[]);
 for(const extra of [{recipe:'mj_style'},{entityId:'other'},{ownership:{providerAccountId:'a',spaceId:'other'}},{ownership:{providerAccountId:'other',spaceId:'s'}}]){
  assert.deepEqual(currentTaskFeedback([task('old','failed',1),task('new','completed',2,extra)]).map(t=>t.id),['old']);
 }
});
test('switching models in the same stage still replaces the previous failure notice',()=>{
 const old=task('old','failed',1,{recipe:'image2_asset'}),next=task('next','completed',2,{recipe:'image25_asset'});
 assert.deepEqual(currentTaskFeedback([old,next]),[]);
});
test('failure feedback states known reasons, escapes text and admits missing provider detail',()=>{
 const failure=task('bad','failed',1,{error:{message:'参考图太大 <script>invalid</script>'}});
 assert.match(compactTasks([failure]),/参考图太大 &lt;script&gt;/);assert.doesNotMatch(compactTasks([failure]),/<script>/);
 assert.match(taskFailureReason({...failure,error:null}),/未提供具体原因/);
 assert.match(taskFailureReason({...failure,error:{message:'官方原任务失败，未自动重新生成。'}}),/未提供具体原因/);
});
test('resolved old failures do not block a later explicit redraw but unresolved receipts still do',()=>{
 const job={status:'ready',shotBindings:[{shotId:'s1',entityId:'asset'}]},result={shots:[{id:'s1'}]},refs=()=>[{pinned:true,src:'image'}];
 const rows=[task('old','failed',1),task('new','completed',2)];
 assert.equal(selectedStoryboardShots({job,result,tasks:rows},refs).length,1);
 rows[0]={...rows[0],remoteStatus:'unknown'};
 assert.equal(selectedStoryboardShots({job,result,tasks:rows},refs).length,0);
});
