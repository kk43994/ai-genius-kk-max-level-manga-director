import test from 'node:test';
import assert from 'node:assert/strict';
import {generationContext,generationGallery} from '../../frontend/workflow/production-generation.js';
import {bindingPicker} from '../../frontend/workflow/production-bindings.js';
const owner={providerAccountId:'a',spaceId:'s'};
const revision=(id,stage)=>({id,stage,assetId:'library',createdAt:'2026-11-01',status:'ready',review:'pending',ownership:owner});
test('candidate galleries are stage-specific and do not imply pending approval',()=>{
 const html=generationGallery([revision('style1','style'),revision('asset1','asset')],'/api/v1',{stage:'asset',category:'character'});
 assert.doesNotMatch(html,/style1/);assert.match(html,/asset1/);assert.match(html,/保留这版四视图/);assert.match(html,/待人工审核/);
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
