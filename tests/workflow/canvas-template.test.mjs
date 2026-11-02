import test from 'node:test';
import assert from 'node:assert/strict';
import {PRODUCTION_TEMPLATE,artFramework,initialMaterialCards} from '../../frontend/workflow/canvas-template.js';
import {artModel,artStudiesPanel,studyPrompt,resolvedArtSamples} from '../../frontend/workflow/art-studies.js';
import {storyWorkflowLayout} from '../../frontend/workflow/story-canvas.js';

test('fixed template leaves missing production details honest and escapes screenplay data',()=>{
 const result={characters:[{id:'a',name:'<林舟>',appearance:[{value:'白衣'}]}],locations:[{id:'place',name:'书店'}]},before=JSON.stringify(result);
 const html=initialMaterialCards(result,{});
 assert.equal((html.match(/data-story-node=/g)||[]).length,3);assert.match(html,/待整理道具/);assert.match(html,/&lt;林舟&gt;/);assert.doesNotMatch(html,/<img/);assert.equal(JSON.stringify(result),before);
 assert.equal(PRODUCTION_TEMPLATE.artSlots.length,3);assert.equal(PRODUCTION_TEMPLATE.shotFields.length,8);
 assert.equal(initialMaterialCards(result,{job:{status:'ready',result:{assets:[],shots:[]}}}),'');
});
test('layout puts art and material before scenes, preserving scene order and measured spacing',()=>{
 const input=[{id:'art:standard',height:500},{id:'material:person',height:530},{id:'scene:two'},{id:'scene:one'},{id:'shot:b',sceneId:'two'},{id:'shot:a',sceneId:'two'},{id:'asset:prop',height:510}];
 const p=storyWorkflowLayout(input);
 assert.ok(p['art:standard'].y<p['material:person'].y);assert.ok(p['material:person'].y+530<p['scene:two'].y);
 assert.ok(p['scene:two'].y<p['scene:one'].y);assert.ok(p['shot:b'].x<p['shot:a'].x);assert.equal(p['asset:prop'].y,p['material:person'].y);
});
test('legacy single style is displayed honestly without claiming all samples exist',()=>{
 const html=artFramework({project:{artDirection:{version:1,valid:true}}});
 assert.match(html,/已有单图标准继续沿用/);assert.equal((html.match(/data-placeholder=/g)||[]).length,3);
});
test('MJ is selected only from official catalog and trial keeps default production model',()=>{
 const catalog={items:[{id:'mj-real',name:'MJ V8.1'},{id:'pro',name:'Lib Image 2.5 Pro'}]};
 assert.equal(artModel('character',catalog).id,'mj-real');assert.equal(artModel('scene',catalog).id,'mj-real');assert.equal(artModel('trial',catalog),null);assert.equal(artModel('character',{items:[]}),undefined);
});
test('standard confirmation rejects unselected, missing and replaced trial references in UI',()=>{
 const rows=['character','scene','trial'].map((role,i)=>({id:role,assetId:role,sha256:'h',review:'approved',status:'ready',sourceRevisionIds:i===2?['character','scene']:[]}));
 const bundle={samples:Object.fromEntries(rows.map(r=>[r.id,{revisionId:r.id,sha256:'h'}]))},o={role:'standard',project:{},assets:[{revisions:rows}],bundle,apiBase:'/api/v1'};
 assert.equal(Object.keys(resolvedArtSamples(bundle,{},o.assets)).length,3);
 assert.match(artStudiesPanel(o),/class="primary" >确认这套/);
 rows[2].sourceRevisionIds=['old-character','scene'];assert.match(artStudiesPanel(o),/请用当前人物和场景重新试镜/);assert.match(artStudiesPanel(o),/class="primary" disabled/);
 rows[0].review='pending';assert.equal(Object.keys(resolvedArtSamples(bundle,{},o.assets)).length,2);
});
test('study prompts use selected facts and keep identity distinct from project style',()=>{
 const facts={characters:[{id:'a',name:'甲'},{id:'b',name:'乙',identity:{value:'书店老板'}}]};
 const prompt=studyPrompt('character',facts,'character:b');assert.match(prompt,/乙。书店老板/);assert.match(prompt,/不复制此人的脸/);assert.doesNotMatch(prompt,/甲/);
});
