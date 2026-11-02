import test from 'node:test';
import assert from 'node:assert/strict';
import {rememberedSettings,uniqueReferencePins,addSharedDirection,affectedRevisions,quickShotPanel,compactTasks} from '../../frontend/workflow/in-place.js';
import {selectedStoryboardShots} from '../../frontend/workflow/generation-batch.js';
import {dialogueText,referenceCards} from '../../frontend/workflow/production.js';
const owner={providerAccountId:'account',spaceId:'space'};
const rev=(id,extra={})=>({id,stage:'asset',status:'ready',review:'approved',ownership:owner,createdAt:'2026-11-03',...extra});
test('remembering settings cannot carry a subject, reference, seed, receipt or account',()=>{
 assert.deepEqual(rememberedSettings({modelId:'m',groups:'2','param:count':'4','param:ratio':'16:9','param:seed':'12',prompt:'old subject',sourceRevisionId:'old',prepareKey:'paid',spaceId:'other'}),{modelId:'m',groups:'2','param:count':'4','param:ratio':'16:9'});
});
test('unambiguous reference fill preserves explicit pins and does not guess between versions',()=>{
 const assets=[{id:'archive',entityId:'entity',active:true,revisions:[rev('master')]}],result={assets:[{id:'person',name:'甲',states:[{id:'base',name:'基础'}]}]},job={result,status:'ready',ownership:owner,bindings:[{assetId:'person',stateId:'base',entityId:'entity',saved:true}]};
 const shot={references:[{assetId:'person',stateId:'base'}]};
 assert.equal(uniqueReferencePins(job,result,assets,owner,shot)[0].revisionId,'master');assert.equal(shot.references[0].revisionId,undefined);
 assets[0].revisions.push(rev('refined',{stage:'refine'}));assert.equal(uniqueReferencePins(job,result,assets,owner,shot)[0].revisionId,undefined);
 shot.references[0].revisionId='historical';assert.equal(uniqueReferencePins(job,result,assets,owner,shot)[0].revisionId,'historical');
 delete shot.references[0].revisionId;assets[0].revisions.forEach(r=>r.ownership={...owner,spaceId:'other'});assert.equal(uniqueReferencePins(job,result,assets,owner,shot)[0].revisionId,undefined);
});
test('batch direction only changes explicit shots; overflow is atomic and IDs must exist',()=>{
 const result={shots:[{id:'one',imagePrompt:'first',references:['a']},{id:'two',imagePrompt:'second',references:['b']}]};
 const changed=addSharedDirection(result,['two'],'冷蓝夜景');assert.deepEqual(changed.shots[0],result.shots[0]);assert.match(changed.shots[1].imagePrompt,/冷蓝夜景/);assert.equal(result.shots[1].imagePrompt,'second');assert.deepEqual(changed.shots[1].references,['b']);
 assert.throws(()=>addSharedDirection(result,['missing'],'change'));assert.throws(()=>addSharedDirection(result,['two','two'],'change'));assert.throws(()=>addSharedDirection(result,['one'],'x'.repeat(3000)));assert.equal(result.shots[0].imagePrompt,'first');
});
test('impact includes transitive descendants without duplicates and excludes unrelated objects',()=>{
 const assets=[{active:true,name:'甲',revisions:[rev('master'),rev('state',{sourceRevisionIds:['master']}),rev('shot',{sourceRevisionIds:['state']}),rev('other',{sourceRevisionIds:[]})]}];
 assert.deepEqual(affectedRevisions(assets,['master']).map(r=>r.id),['state','shot']);
});
test('human dialogue edit is labeled and source preserved; unbound edits cannot inject speech',()=>{
 const job={characters:[{id:'a',name:'甲'}],dialogues:[{id:'d',speakerId:'a',kind:'dialogue',text:'原句'}]},shot={dialogueIds:['d'],dialogueOverrides:[{id:'d',text:'改写',origin:'manual'},{id:'foreign',text:'injected',origin:'manual'}]};
 const lines=dialogueText(job,shot);assert.equal(lines.length,1);assert.equal(lines[0].text,'改写');assert.equal(lines[0].sourceText,'原句');assert.equal(lines[0].edited,true);assert.equal(job.dialogues[0].text,'原句');
});
test('explicit new-version batch allows completed images but never unresolved receipts',()=>{
 const job={status:'ready',shotBindings:[{shotId:'one',entityId:'entity'}]},result={shots:[{id:'one'}]},refs=()=>[{pinned:true,src:'image'}];
 for(const status of ['completed','cancelled'])assert.equal(selectedStoryboardShots({job,result,tasks:[{entityId:'entity',status}]},refs).length,1);
 for(const status of ['prepared','running','failed','unknown_submission','needs_attention'])assert.equal(selectedStoryboardShots({job,result,tasks:[{entityId:'entity',status}]},refs).length,0);
 assert.equal(selectedStoryboardShots({job,result},()=>[{pinned:false,src:'image'}]).length,0);
});
test('recoverable task exposes original lookup and escapes provider errors without fake percentages',()=>{
 const html=compactTasks([{id:'one',status:'needs_attention',submissionAttempted:true,canRecover:true,error:{message:'<script>unsafe</script>'}}]);
 assert.match(html,/查询原任务/);assert.doesNotMatch(html,/取消未提交|<script>|100%/);assert.match(html,/&lt;script&gt;/);
});

test('historical pinned references remain visible but cannot be reused automatically',()=>{
 const assets=[{id:'archive',entityId:'entity',active:true,revisions:[rev('old',{status:'stale'})]}],result={assets:[{id:'person',name:'甲',states:[{id:'base',name:'基础'}]}]},job={result,status:'ready',ownership:owner,bindings:[{assetId:'person',stateId:'base',entityId:'entity',saved:true}]};
 const shot={references:[{assetId:'person',stateId:'base',revisionId:'old'}]};
 const card=referenceCards(job,shot,assets,owner,'/api/v1')[0];assert.equal(card.src,null);assert.equal(card.versions.length,0);assert.match(card.historySrc,/revisionId=old/);assert.equal(card.historyRevisionId,'old');
 assets[0].revisions[0].ownership={...owner,spaceId:'other'};assert.equal(referenceCards(job,shot,assets,owner,'/api/v1')[0].historySrc,null);
});
