import test from 'node:test';
import assert from 'node:assert/strict';
import {generationContext,generationGallery,generationInspector,MASTER_STATE_ID} from '../../frontend/workflow/production-generation.js';
import {bindingPicker} from '../../frontend/workflow/production-bindings.js';
const owner={providerAccountId:'a',spaceId:'s'};
const revision=(id,stage)=>({id,stage,assetId:'library',createdAt:'2026-11-01',status:'ready',review:'pending',ownership:owner});
test('candidate galleries are stage-specific and do not imply pending approval',()=>{
 const html=generationGallery([revision('style1','style'),revision('asset1','asset')],'/api/v1',{stage:'asset',category:'character'});
 assert.doesNotMatch(html,/style1/);assert.match(html,/asset1/);assert.match(html,/保留这版状态多视图/);assert.match(html,/待人工审核/);
});
test('standard prompts distinguish people, scenes and props from the film aspect ratio',()=>{
 for(const [category,required] of [['character','头部特写'],['scene','反打视图'],['prop','白底正视图']]){
  const asset={id:'a',category,name:'物料',design:'设计',states:[{id:'base',imagePrompt:'依据原文'}]};
  const c=generationContext({result:{assets:[asset],styleBible:'统一',aspectRatio:'9:16'},job:{bindings:[]},view:{kind:'assets',index:0,stage:'asset'}});
  assert.match(c.prompt,new RegExp(required));assert.equal(c.mode.recipe,'image2_asset');
 }
});
test('existing images require explicit linking and unsafe names are escaped',()=>{
 const job={bindings:[{assetId:'a',stateId:'s',saved:false,legacyCandidates:[{entityId:'old',name:'<script>'}]}],ownership:owner};
 const html=bindingPicker({job,asset:{id:'a',name:'A'},state:{id:'s',name:'Base'},assets:[],apiBase:'/api/v1'});
 assert.match(html,/确认适用，关联此档案/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test('state assets require the same character approved master, while style exploration has no state selector',()=>{
 const result={assets:[{id:'hero',category:'character',states:[{id:'rain',name:'雨中'}]}]};
 const job={status:'ready',ownership:owner,bindings:[{assetId:'hero',stateId:MASTER_STATE_ID,entityId:'master',saved:true},
  {assetId:'hero',stateId:'rain',entityId:'rain',saved:false},{assetId:'other',stateId:MASTER_STATE_ID,entityId:'other',saved:true}]};
 const assets=[{entityId:'master',name:'主角主多视图',active:true,revisions:[{...revision('master-image','asset'),entityId:'master',review:'approved'},
   {...revision('identity','style'),entityId:'master',review:'approved'},revision('pending','asset')]},
  {entityId:'other',active:true,revisions:[{...revision('foreign','asset'),entityId:'other',review:'approved'}]}];
 const options={result,job,view:{kind:'assets',index:0,stage:'asset',characterLayer:'state'},assets,selection:owner};
 const c=generationContext(options);
 assert.deepEqual(c.sources.map(r=>r.id),['master-image']);assert.equal(c.sources[0].sourceName,'主角主多视图');
 assert.equal(c.binding.entityId,'rain');assert.equal(c.library,undefined);assert.equal(c.mode.label,'生成此状态多视图');
 const styleOptions={...options,view:{...options.view,stage:'style'}};
 assert.equal(generationContext(styleOptions).state.id,MASTER_STATE_ID);
 assert.doesNotMatch(generationInspector(styleOptions),/data-board-generation-state/);
 const master=generationContext({...options,view:{...options.view,characterLayer:'master'}});
 assert.deepEqual(master.sources.map(r=>r.id),['identity']);assert.equal(master.mode.label,'生成人物主多视图');
 job.bindings[0].changed=true;
 assert.equal(generationContext(options).sources.length,0);
 assert.match(generationInspector(options),/请先生成并确认人物主多视图/);
});

test('only a verified upload-only failure offers a fresh preparation key',()=>{
 const result={assets:[{id:'hero',category:'character',states:[{id:'rain',name:'雨中'}]}]};
 const options={result,job:{status:'ready',bindings:[{assetId:'hero',stateId:MASTER_STATE_ID,entityId:'master'}]},
  view:{kind:'assets',index:0,stage:'asset'},assets:[],tasks:[{entityId:'master',status:'failed',error:{code:'REFERENCE_UPLOAD_FAILED'}}]};
 assert.match(generationInspector(options),/data-generation-reroll/);
 assert.match(generationInspector(options),/重新准备本次生成/);
 options.tasks[0].status='needs_attention';options.tasks[0].error.code='SUBMISSION_UNKNOWN';
 assert.doesNotMatch(generationInspector(options),/data-generation-reroll/);
 options.tasks=[{...options.tasks[0],status:'failed',createdAt:'2026-01-01T00:00:00Z',error:{code:'REFERENCE_UPLOAD_FAILED',message:'old-upload-error'}},
  {entityId:'master',status:'submitting',createdAt:'2026-01-02T00:00:00Z'}];
 assert.doesNotMatch(generationInspector(options),/old-upload-error|重新准备本次生成/);
});
