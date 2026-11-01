import test from 'node:test';
import assert from 'node:assert/strict';
import {selectedImageModel,collectImageSettings,imageModelPicker} from '../../frontend/workflow/image-models.js';
import {batchSize,parallelGroups} from '../../frontend/workflow/generation-batch.js';

const catalog={items:[{id:'official-pro',name:'Lib Image 2.5 Pro'},{id:'mj-real',name:'Style Image V8.1'}]};
const contract={verified:true,schema:{properties:{count:{type:'integer',enum:[1,2,4]},ratio:{enum:['16:9','1:1']},seed:{type:'integer'},style:{enum:['raw','default']}}}};
test('default resolves the official name to the returned ID; never aliases Lib Image',()=>{
 assert.equal(selectedImageModel({},catalog).id,'official-pro');
 assert.equal(selectedImageModel({modelId:'mj-real'},catalog).id,'mj-real');
 assert.equal(selectedImageModel({},{items:[{id:'old',name:'Lib Image'}]}).id,'Lib Image 2.5 Pro');
});
test('controls and submitted creative settings match the selected schema',()=>{
 const html=imageModelPicker({catalog,contracts:{'official-pro':contract},draft:{},ratio:'16:9'});
 assert.match(html,/official-pro" selected/);assert.match(html,/name="param:style"/);
 assert.deepEqual(collectImageSettings({'param:count':'2','param:ratio':'1:1','param:seed':'7','param:style':'raw',modelId:'official-pro'},contract),{count:2,ratio:'1:1',seed:7,style:'raw'});
 assert.throws(()=>collectImageSettings({'param:ratio':'9:16'},contract));
 assert.throws(()=>collectImageSettings({},{}));
});
test('concurrent groups keep their order, bound active submissions, and never retry failures',async()=>{
 let active=0,maximum=0;const calls=[];
 const result=await parallelGroups([0,1,2,3,4],async i=>{calls.push(i);active++;maximum=Math.max(maximum,active);await new Promise(r=>setTimeout(r,10));active--;if(i===1)throw new Error('unknown');return 'receipt-'+i;},3);
 assert.equal(maximum,3);assert.deepEqual(calls,[0,1,2,3,4]);
 assert.equal(result[1].status,'rejected');assert.equal(result[4].value,'receipt-4');
 assert.equal(batchSize('8'),8);for(const n of [0,9,1.5,'bad'])assert.throws(()=>batchSize(String(n)));
});
test('nullable official controls use ordinary typed fields',()=>{
 const nullable={verified:true,schema:{properties:{seed:{anyOf:[{type:'integer',minimum:0},{type:'null'}]},style:{type:['string','null']}}}};
 const html=imageModelPicker({catalog,contracts:{'official-pro':nullable}});
 assert.match(html,/name="param:seed"[^>]*type="number"/);assert.doesNotMatch(html,/placeholder="JSON"/);
 assert.deepEqual(collectImageSettings({'param:seed':'5','param:style':'raw'},nullable),{seed:5,style:'raw',count:1});
});
