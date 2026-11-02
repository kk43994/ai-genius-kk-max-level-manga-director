import test from 'node:test';
import assert from 'node:assert/strict';
import {analysisDraft,analysisDraftAfterSave,analysisReviewControls} from '../../frontend/workflow/analysis-edit.js';

const job={reviewVersion:2,resultHash:'original-source',result:{characters:[{id:'person',name:'原名'}]}};
test('analysis save retains later input and rebases the next save without changing the source',()=>{
 const submitted=analysisDraft(job),current=structuredClone(submitted);
 current.result.characters[0].name='保存等待时改名';
 const saved={...job,reviewVersion:3,resultHash:'returned-source'};
 const pending=analysisDraftAfterSave(submitted,current,saved);
 assert.equal(pending.result.characters[0].name,'保存等待时改名');
 assert.equal(pending.expectedVersion,3);assert.equal(pending.expectedResultHash,'returned-source');
 pending.result.characters[0].name='继续改名';
 assert.equal(current.result.characters[0].name,'保存等待时改名');
 assert.equal(job.result.characters[0].name,'原名');
 assert.equal(analysisDraftAfterSave(submitted,structuredClone(submitted),saved),null);
 assert.equal(analysisDraftAfterSave(pending,structuredClone(pending),{...saved,reviewVersion:4}),null);
});
test('raw analysis edits remain visible when the acknowledged result becomes structured',()=>{
 const submitted={...analysisDraft(job),raw:JSON.stringify(job.result)},current={...submitted,raw:'{"characters":['};
 const saved={...job,reviewVersion:3,structuredDraft:true};
 const pending=analysisDraftAfterSave(submitted,current,saved);
 assert.equal(pending.raw,current.raw);assert.equal(pending.expectedVersion,3);
 const html=analysisReviewControls(saved,pending,true);
 assert.match(html,/data-wf-analysis-json/);assert.match(html,/&quot;characters&quot;/);
 assert.match(html,/data-wf-action="analysis-review-discard" disabled/);
});
