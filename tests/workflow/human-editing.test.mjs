import test from 'node:test';
import assert from 'node:assert/strict';
import {dialogueLines,editDialogue,addDialogue,moveDialogue,restoreDialogue,dialogueEditor} from '../../frontend/workflow/dialogue-editor.js';
import {newAnalysisRecord,recordReferences,analysisRecordPanel} from '../../frontend/workflow/analysis-records.js';
import {analysisField} from '../../frontend/workflow/analysis-edit.js';
import {removeShot,restoreShot,addShot,removeBlankShot,splitShot} from '../../frontend/workflow/shot-structure.js';
const job={characters:[{id:'a',name:'甲'},{id:'b',name:'乙'}],dialogues:[{id:'d1',text:'原句一',speakerId:'a',kind:'dialogue'},{id:'d2',text:'原句二',speakerId:'b',kind:'dialogue'}]};
const shot={id:'s1',order:1,sceneId:'scene1',dialogueIds:['d1','d2']};
test('human metadata, delete, restore and source text stay independent',()=>{
 let changed=editDialogue(job,shot,'d1',{speakerId:'b',kind:'inner_monologue',text:'改写'});
 assert.equal(dialogueLines(job,changed)[0].label,'乙 · 内心独白');assert.equal(job.dialogues[0].text,'原句一');
 changed=editDialogue(job,changed,'d2',{deleted:true});assert.equal(dialogueLines(job,changed).length,1);
 assert.deepEqual(restoreDialogue(changed,'d1').dialogueOverrides,[{id:'d2',text:'原句二',origin:'manual',deleted:true}]);
 assert.match(dialogueEditor(job,changed,0),/第 1 句说话人/);
});
test('added speech sorts around deleted source rows without losing identities',()=>{
 let s=editDialogue(job,shot,'d2',{deleted:true});s=addDialogue(s,'new1');s=editDialogue(job,s,'new1',{text:'新句',speakerLabel:'路人'});
 s=moveDialogue(job,s,'d1',1);assert.deepEqual(dialogueLines(job,s).map(d=>d.id),['new1','d1']);assert.deepEqual(new Set(s.dialogueOrder),new Set(['new1','d1','d2']));
 const result={shots:[s]};assert.equal(addShot(result,0,()=> 's2').shots[1].dialogueAdditions.length,0);
 assert.equal(removeBlankShot({shots:[{...s,dialogueIds:[],purpose:'补充镜头 · 请编辑动作与构图'}]},0).shots.length,1);
});
test('normal shot removal restores exact contents and reorders remaining shots',()=>{
 const r={shots:[shot,{...shot,id:'s2',order:2},{...shot,id:'s3',order:3,sceneId:'scene2'}]};
 const deleted=removeShot(r,1);assert.deepEqual(deleted.shots.map(s=>s.order),[1,2]);assert.equal(deleted.removedShots[0].id,'s2');
 assert.deepEqual(restoreShot(deleted,'s2'),r);
 let empty=r;for(let i=0;i<3;i++)empty=removeShot(empty,0);assert.equal(empty.shots.length,0);assert.equal(restoreShot(empty,'s1').shots[0].id,'s1');
 empty=restoreShot(restoreShot(restoreShot(empty,'s3'),'s1'),'s2');assert.deepEqual(empty,r);
});
test('analysis additions contain placeholders, references are reported without cascading deletion',()=>{
 const r={characters:[{id:'a',name:'甲'}],scenes:[{id:'s',title:'场',order:1,presentCharacterIds:['a']}],events:[],dialogues:[],locations:[],times:[],uncertainties:[]};
 assert.equal(newAnalysisRecord('characters','new',r).status,'unknown');assert.equal(newAnalysisRecord('dialogues','new',r).speakerId,null);
 r.events.push({id:'event',summary:'a 和甲都只是自由文字，不代表已绑定角色'});
 assert.deepEqual(recordReferences(r,'a').map(x=>x.id),['s']);
 assert.match(analysisField('missing','dialogues.0.speakerId',undefined,r),/关联已缺失/);
 assert.match(analysisField([],'characters.0.appearance',undefined,r),/添加外貌/);
 assert.match(analysisRecordPanel({job:{result:r},group:'characters',recordId:'a'}),/删除这条角色/);
 r.dialogues=Array.from({length:8},(_,i)=>({id:`line${i}`,speakerId:'a',text:`关联台词${i}`}));
 const panel=analysisRecordPanel({job:{result:r},group:'characters',recordId:'a',pendingDelete:'a'});
 assert.match(panel,/找到 9 条已建立的关联/);assert.match(panel,/查看其余 3 处关联/);assert.match(panel,/关联台词7/);
});

test('splitting follows human speech order, keeps deleted source and does not duplicate additions',()=>{
 let s=editDialogue(job,shot,'d2',{deleted:true});s=addDialogue(s,'new1');s=editDialogue(job,s,'new1',{text:'新句'});s=moveDialogue(job,s,'new1',-1);
 const r=splitShot({shots:[{...s,purpose:'镜头'}]},0,job.dialogues,()=> 'newshot');
 assert.deepEqual(r.shots.map(s=>dialogueLines(job,s).map(d=>d.id)),[['new1'],['d1']]);
 assert.deepEqual(r.shots.flatMap(s=>s.dialogueIds).sort(),['d1','d2']);assert.equal(r.shots[0].dialogueAdditions.length,1);
});
