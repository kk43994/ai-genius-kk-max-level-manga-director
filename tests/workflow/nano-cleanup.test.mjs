import test from 'node:test';
import assert from 'node:assert/strict';
import {nanoModels,selectedNanoModel,nanoCleanupSource,NANO_CLEANUP_MARKER} from '../../frontend/workflow/nano-cleanup.js';
import {versionPicker} from '../../frontend/workflow/version-picker.js';
const catalog={items:[{id:'image',name:'Lib Image 2.5 Pro'},{id:'nano-pro',name:'Nano Banana Pro'},{id:'nano-2',name:'Nano Banana 2'}]};
const owner={providerAccountId:'a',spaceId:'s'};
const original={id:'original',assetId:'asset',entityId:'shot',stage:'storyboard',status:'ready',review:'approved',ownership:owner,sourceRevisionIds:[],reviewHistory:[]};
const seed={id:'seed',provenance:{kind:'image_edit',revisionId:original.id}};
const clean={...original,id:'clean',prompt:NANO_CLEANUP_MARKER,review:'pending',sourceRevisionIds:['seed']};
const assets=[{id:'asset',name:'合成镜头',revisions:[original,clean]},{id:'input',referenceOnly:true,revisions:[seed]}];
const job={status:'ready',shotBindings:[{shotId:'s1',entityId:'shot'}]};

test('Nano selection uses official catalog IDs, respects user choice, never falls back to Image2',()=>{
 assert.deepEqual(nanoModels(catalog).items.map(m=>m.id),['nano-pro','nano-2']);
 assert.equal(selectedNanoModel({},catalog).id,'nano-2');
 assert.equal(selectedNanoModel({modelId:'nano-pro'},catalog).id,'nano-pro');
 assert.equal(selectedNanoModel({}, {items:[catalog.items[0]]}),null);
 assert.equal(selectedNanoModel({},null),null);
});
test('repeat cleanup resolves the original source, and broken or foreign lineage cannot be washed again',()=>{
 assert.equal(nanoCleanupSource(clean,assets),original);
 const again={...clean,id:'again',sourceRevisionIds:['seed2']};
 const seed2={id:'seed2',provenance:{kind:'image_edit',revisionId:clean.id}};
 assert.equal(nanoCleanupSource(again,[...assets,{revisions:[seed2,again]}]),original);
 assert.equal(nanoCleanupSource(clean,[assets[0]]),null);
 for(const patch of [{stage:'asset'},{assetId:'other'},{entityId:'other'},{ownership:{...owner,spaceId:'other'}}]){
  assert.equal(nanoCleanupSource(clean,[{revisions:[{...original,...patch},seed]}]),null);
 }
 assert.equal(nanoCleanupSource(clean,[{revisions:[clean,{...seed,provenance:{kind:'image_edit',revisionId:clean.id}}]}]),null);
});
test('Nano form pins original, keeps parameters collapsed, and never enables submission without a verified Nano model',()=>{
 const args={asset:assets[0],revision:original,allAssets:assets,job,selection:owner,apiBase:'/api/v1',mode:'nano',reroll:true,catalog};
 let html=versionPicker({...args,contracts:{'nano-2':{verified:true,schema:{properties:{}}}}});
 assert.match(html,/data-version-nano="original"/);
 assert.match(html,/洗图参考原图 V1/);
 assert.match(html,/补充清理要求（可选）/);
 assert.match(html,/<details class="version-options">/);
 assert.match(html,/<option value="nano-2" selected>/);
 assert.doesNotMatch(html,/<option value="image"/);
 assert.match(html,/<button type="submit" class="primary" >准备 Nano 洗图/);
 html=versionPicker({...args,catalog:{items:[catalog.items[0]]},contracts:{image:{verified:true,schema:{properties:{}}}}});
 assert.match(html,/当前目录没有可用的 Nano 模型/);
 assert.match(html,/<button type="submit" class="primary" disabled>准备 Nano 洗图/);
 html=versionPicker({...args,catalog:null,error:'请先完成官方授权'});
 assert.doesNotMatch(html,/当前目录没有可用的 Nano 模型/);
 assert.match(html,/请先完成官方授权/);
});
