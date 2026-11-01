import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewDraft,setReviewValue,valueAt} from '../../frontend/workflow/production-editor.js';
test('manual editing leaves provider result intact, retains legacy edits and versions',()=>{
 const job={reviewVersion:3,editVersion:2,result:{shots:[{id:'s1',performance:'原文',durationSeconds:5}],assets:[{evidence:[{quote:'错误'}]}]}};
 const draft=reviewDraft(job,{expectedVersion:2,shots:{s1:{performance:'已改'}}});
 assert.equal(draft.expectedVersion,3);assert.equal(draft.expectedEditVersion,2);
 assert.equal(draft.result.shots[0].performance,'已改');
 assert.equal(setReviewValue(draft.result,'assets.0.evidence.0.quote','原文'),true);
 assert.equal(valueAt(draft.result,'assets.0.evidence.0.quote'),'原文');
 assert.equal(job.result.assets[0].evidence[0].quote,'错误');
 assert.equal(job.result.shots[0].performance,'原文');
 assert.equal(setReviewValue(draft.result,'__proto__.polluted',true),false);
 assert.equal(setReviewValue(draft.result,'assets.3.name','无效'),false);
});
