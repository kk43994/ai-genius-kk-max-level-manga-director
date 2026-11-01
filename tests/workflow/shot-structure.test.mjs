import test from 'node:test';
import assert from 'node:assert/strict';
import {splitShot,addShot,dialogueSeconds,removeBlankShot,numberShots} from '../../frontend/workflow/shot-structure.js';

test('manual dialogue split preserves exact IDs once and all source references',()=>{
 const source={shots:[{id:'shot_1',order:1,sceneId:'s1',purpose:'揭示真相',dialogueIds:['d1','d2'],references:[{assetId:'hero',stateId:'base'}],eventIds:['e1'],durationSeconds:5},{id:'shot_2',order:2,sceneId:'s2',dialogueIds:[],durationSeconds:4}]};
 const result=splitShot(source,0,[{id:'d1',text:'一段原文'},{id:'d2',text:'更长的原文'.repeat(5)}],()=> 'new_shot');
 assert.deepEqual(result.shots.flatMap(s=>s.dialogueIds),['d1','d2']);
 assert.deepEqual(result.shots.map(s=>s.order),[1,2,3]);
 assert.equal(result.shots[0].id,'shot_1');assert.equal(result.shots[1].id,'new_shot');
 assert.deepEqual(result.shots[1].references,source.shots[0].references);
 assert.equal(source.shots.length,2);assert.ok(result.shots[1].durationSeconds>5);
});
test('adding an action shot leaves dialogue untouched and keeps scene order',()=>{
 const source={shots:[{id:'one',sceneId:'scene',order:1,dialogueIds:['exact_dialogue'],references:[],purpose:'原镜'}]};
 const result=addShot(source,0,()=> 'two');
 assert.deepEqual(result.shots.map(s=>s.dialogueIds),[['exact_dialogue'],[]]);
 assert.equal(result.shots[1].sceneId,'scene');assert.equal(source.shots.length,1);
 assert.equal(dialogueSeconds([{id:'a',text:'你，好！'}],['a']),3);
});

test('removing an accidental middle shot preserves other contents and repairs numbering',()=>{
 const source={shots:[{id:'a',sceneId:'s1',order:1,dialogueIds:['d1'],purpose:'原镜'},
 {id:'blank',sceneId:'s1',order:2,dialogueIds:[],purpose:'补充镜头 · 请编辑动作与构图'},
 {id:'b',sceneId:'s1',order:3,dialogueIds:['d2'],purpose:'后镜',references:[{assetId:'hero'}]},
 {id:'c',sceneId:'s2',order:4,dialogueIds:[],purpose:'下一场'}]};
 const edited=removeBlankShot(source,1);
 assert.deepEqual(edited.shots,numberShots([source.shots[0],source.shots[2],source.shots[3]]));
 assert.deepEqual(edited.shots.map(s=>s.order),[1,2,3]);
 assert.deepEqual(removeBlankShot(source,0),source);
 assert.equal(source.shots.length,4);assert.equal(source.shots[2].order,3);
});
