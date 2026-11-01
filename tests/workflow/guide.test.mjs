import test from 'node:test';
import assert from 'node:assert/strict';
import {nextAction, prepareIdentity} from '../../frontend/workflow/guide.js';
const selected = {providerAccountId:'account-a',spaceId:'space-a',revision:1};
function state(){return {project:{id:'p',scriptIds:['s'],version:1}, plan:{version:1,styleVersion:1,entities:[{id:'e',name:'旅人',category:'character',version:1}]},assets:[],tasks:[],bundles:[],selection:selected};}
const revision = (stage,review='approved',id=stage) => ({id,stage,review,status:'ready',ownership:selected,sourceRevisionIds:[],reviewHistory:[]});
function withImages(...revisions){return {...state(),assets:[{active:true,entityId:'e',revisions}]};}
function task(extra={}){return {id:'task',entityId:'e',recipe:'mj_style',status:'draft',ownership:selected,sourceRevisionIds:[],workflowSnapshot:{entityVersion:1,styleVersion:1},createdAt:'2026-10-28T00:00:00Z',...extra};}
test('script draft requires review, then account selection, before preparing',()=>{
 const data=state(); data.plan.needsReview=true; assert.equal(nextAction(data).kind,'plan');
 delete data.plan.needsReview; data.selection=null; assert.equal(nextAction(data).kind,'connect');
 data.selection=selected; const step=nextAction(data); assert.equal(step.kind,'prompt'); assert.equal(step.spec.settings.count,1); assert.equal(step.spec.prompt,undefined);
});
test('each stage pauses for review and Nano always uses Image2',()=>{
 assert.equal(nextAction(withImages(revision('style','pending'))).kind,'review');
 const asset=nextAction(withImages(revision('style'))); assert.equal(asset.spec.recipe,'image2_asset'); assert.deepEqual(asset.spec.sourceRevisionIds,['style']);
 const nano=nextAction(withImages(revision('style'),revision('asset'))); assert.equal(nano.spec.recipe,'nano_refine'); assert.deepEqual(nano.spec.sourceRevisionIds,['asset']);
 assert.equal(nextAction(withImages(revision('style'),revision('asset'),revision('refine','pending'))).kind,'review');
});
test('lost or in-flight receipts block duplicates even after plan edits',()=>{
 const data=state(); data.plan.entities[0].version=2;
 data.tasks=[task({submissionAttempted:true,status:'submitting',canRecover:false})]; assert.equal(nextAction(data).kind,'blocked');
 data.tasks[0].canRecover=true; assert.equal(nextAction(data).kind,'recover');
});
test('unknown task listing is fail closed',()=>{assert.equal(nextAction({...state(),taskError:'offline'}).kind,'blocked');});
test('saved drafts reconfirm, failed tasks do not silently retry',()=>{
 const data=state();data.tasks=[task({canConfirm:true})];assert.equal(nextAction(data).kind,'confirm');
 data.tasks=[task({status:'failed',error:{message:'provider offline'}})];assert.equal(nextAction(data).kind,'blocked');
});
test('explicitly cancelled unsubmitted preparation permits a new identity',async()=>{
 const data=state();data.tasks=[task({status:'cancelled',canConfirm:false,submissionAttempted:false})];
 const next=nextAction(data);assert.equal(next.kind,'prompt');assert.equal(next.cancelledTaskId,'task');
 assert.notEqual(await prepareIdentity(next.spec,1),await prepareIdentity(next.spec,1,{cancelledTaskId:next.cancelledTaskId}));
 data.tasks[0].submissionAttempted=true;assert.equal(nextAction(data).kind,'blocked');
});
test('other account media cannot become references or be treated as missing',()=>{
 const other={...revision('style'),ownership:{...selected,providerAccountId:'other'}};
 assert.equal(nextAction(withImages(other)).kind,'connect');
});
test('repair request follows explicit review and references original upstream',()=>{
 const rejected=revision('refine','changes_requested','rejected');rejected.reviewHistory=[{at:'2026-10-28T01:00:00Z'}];
 const next=nextAction(withImages(revision('style'),revision('asset'),rejected));
 assert.equal(next.spec.repairOfRevisionId,'rejected');assert.deepEqual(next.spec.sourceRevisionIds,['asset']);
});
test('only current reviewed set may use an existing archive',()=>{
 const data=withImages(revision('style'),revision('asset'),revision('refine'));
 assert.equal(nextAction(data).kind,'archive');
 data.bundles=[{id:'b',planVersion:1,revisionIds:['asset','refine','style']}];assert.equal(nextAction(data).kind,'download');
 data.assets[0].revisions[2].id='new-refine';assert.equal(nextAction(data).kind,'archive');
});
test('prepare id survives refresh and changes for actual changed input or selection',async()=>{
 const spec=nextAction(state()).spec;
 assert.equal(await prepareIdentity(spec,1),await prepareIdentity(structuredClone(spec),1));
 assert.notEqual(await prepareIdentity(spec,1),await prepareIdentity(spec,2));
 assert.notEqual(await prepareIdentity(spec,1,{entityVersion:1}),await prepareIdentity(spec,1,{entityVersion:2}));
 assert.notEqual(await prepareIdentity(spec,1),await prepareIdentity({...spec,prompt:spec.prompt+'change'},1));
});
