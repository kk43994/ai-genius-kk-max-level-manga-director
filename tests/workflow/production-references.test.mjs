import test from 'node:test';
import assert from 'node:assert/strict';
import {assetToken,referenceLabel,readableText,storedText,linkedText,bindReference,removeReference,referencePicker,appendManualProp} from '../../frontend/workflow/production-references.js';
const result={assets:[{id:'hero',name:'顾声声',category:'character',states:[{id:'wet',name:'被绑湿身',sceneIds:['s1']},{id:'home',name:'日常',sceneIds:['s2']}]},{id:'chair',name:'椅子',category:'prop',states:[{id:'base',name:'木椅',sceneIds:['s1']}]}]};
const shot=()=>({id:'s01',sceneId:'s1',beat:'',imagePrompt:'',videoPrompt:'',references:[]});
test('references store stable IDs while users read names, including duplicate names',()=>{
 const s=shot();bindReference(s,result.assets[0],'wet');bindReference(s,result.assets[1],'base');
 const canonical=assetToken('hero')+'被绑在'+assetToken('chair')+'上，皱着眉头。';
 assert.equal(storedText(readableText(canonical,result,s),result,s),canonical);
 const renamed=structuredClone(result);renamed.assets[0].name='顾声声新名称';
 assert.match(readableText(canonical,renamed,s),/顾声声新名称/);
 const duplicate=structuredClone(result);duplicate.assets[1].name='顾声声';
 assert.match(referenceLabel(duplicate,s,'hero'),/001/);assert.match(referenceLabel(duplicate,s,'chair'),/002/);
 assert.equal(storedText('顾声声和〔未知物料〕',result,s),'顾声声和〔未知物料〕');
});
test('binding updates one state, clears old image pin, rejects wrong scene',()=>{
 const s=shot();assert.equal(bindReference(s,result.assets[0],'home'),false);
 assert.equal(bindReference(s,result.assets[0],'wet'),true);s.references[0].revisionId='old';
 assert.equal(bindReference(s,result.assets[0],'wet'),true);assert.equal(s.references.length,1);assert.equal(s.references[0].revisionId,'old');
 const asset=structuredClone(result.assets[0]);asset.states.push({id:'hurt',name:'受伤',sceneIds:['s1']});
 bindReference(s,asset,'hurt');assert.equal(s.references[0].revisionId,undefined);
 s.beat=assetToken('hero');assert.equal(removeReference(s,'hero'),false);
 s.beat='普通文字';assert.equal(removeReference(s,'hero'),true);assert.equal(s.references.length,0);
});
test('clickable references escape hostile text and picker only offers applicable states',()=>{
 const s=shot();bindReference(s,result.assets[0],'wet');
 const html=linkedText('<script>'+assetToken('hero'),result,s);
 assert.match(html,/&lt;script&gt;/);assert.match(html,/data-board-reference-open="0"/);
 const picker=referencePicker(result,s,'shots.0.beat');assert.match(picker,/椅子/);assert.doesNotMatch(picker,/日常/);
});

test('new props retain manual provenance and connect only to the current shot',()=>{
 const r=structuredClone(result);r.shots=[{...shot(),evidence:[{quote:'原文使用场次',startLine:1,endLine:1}]}];
 const prop=appendManualProp(r,0,{id:'prop_manual',name:'椅子',design:'旧木椅',prompt:'一把旧木椅，四条直腿，深棕木纹，完整展示结构，背景干净。'});
 assert.equal(prop.origin,'manual');assert.equal(prop.category,'prop');assert.equal(r.shots[0].references.at(-1).assetId,'prop_manual');
 assert.deepEqual(prop.states[0].sceneIds,['s1']);assert.notEqual(prop.evidence,r.shots[0].evidence);
 assert.equal(appendManualProp(r,0,{id:'bad',name:'未完成',design:'',prompt:''}),null);
});
