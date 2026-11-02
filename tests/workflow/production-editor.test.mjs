import test from 'node:test';
import assert from 'node:assert/strict';
import {reviewDraft,draftAfterSave,setReviewValue,valueAt} from '../../frontend/workflow/production-editor.js';
import {field,textLines} from '../../frontend/workflow/production-editor.js';
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
test('continuity notes remain a list after multiline manual editing',()=>{
 const notes=textLines(' 保持左手持物 \r\n\r\n火从门侧蔓延\n');
 assert.deepEqual(notes,['保持左手持物','火从门侧蔓延']);
 const html=field('连续性','shots.0.continuity',notes,{lines:true});
 assert.match(html,/data-production-lines/);assert.match(html,/保持左手持物\n火从门侧蔓延/);
 assert.deepEqual(textLines('   \n'),[]);
});
test('save acknowledgment only clears the exact submitted content',()=>{
 const submitted={expectedVersion:2,expectedEditVersion:1,result:{shots:[{id:'s1',beat:'已提交'}]}};
 const saved={reviewVersion:3,editVersion:2,result:structuredClone(submitted.result)};
 assert.equal(draftAfterSave(submitted,structuredClone(submitted),saved),null);
 assert.equal(draftAfterSave(submitted,null,saved),null);
 const current=structuredClone(submitted);current.result.shots[0].beat='等待期间新输入';
 const pending=draftAfterSave(submitted,current,saved);
 assert.equal(pending.result.shots[0].beat,'等待期间新输入');
 assert.equal(pending.expectedVersion,3);assert.equal(pending.expectedEditVersion,2);
 pending.result.shots[0].beat='继续修改';
 assert.equal(current.result.shots[0].beat,'等待期间新输入');
 assert.equal(saved.result.shots[0].beat,'已提交');
 assert.equal(submitted.result.shots[0].beat,'已提交');
});
test('pending draft retains new dialogue and legacy edits through consecutive saves',()=>{
 const job={reviewVersion:3,editVersion:1,result:{shots:[{id:'s1',beat:'原动作',dialogueIds:['d1']}]}};
 const submitted=reviewDraft(job,{expectedVersion:1,shots:{s1:{beat:'旧版未保存动作'}}});
 const current=structuredClone(submitted);
 current.result.shots[0].dialogueOverrides=[{id:'d1',text:'保存期间改写',origin:'manual'}];
 const saved={...job,reviewVersion:4,editVersion:2,result:submitted.result};
 const pending=draftAfterSave(submitted,current,saved);
 assert.equal(pending.result.shots[0].beat,'旧版未保存动作');
 assert.equal(pending.result.shots[0].dialogueOverrides[0].text,'保存期间改写');
 assert.equal(draftAfterSave(pending,structuredClone(pending),{...saved,reviewVersion:5,result:pending.result}),null);
});
