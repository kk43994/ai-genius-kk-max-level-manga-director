import test from 'node:test';
import assert from 'node:assert/strict';
import {timelineAt,referenceCards,dialogueText,previewFrame,productionPanel} from '../../frontend/workflow/production.js';
const shot={id:'s1',order:1,durationSeconds:5,purpose:'看清信封',framing:'中景',beat:'交接',performance:'停顿',camera:'固定',sound:'风声',dialogueIds:['d1'],evidence:[],continuity:[],references:[{assetId:'character',stateId:'wet'}]};
const job={id:'prd_a',status:'ready',totalCalls:1,completedCalls:1,message:'ready',result:{aspectRatio:'9:16',assets:[{id:'character',category:'character',name:'<人物>',design:'设计',creativeChoices:[],evidence:[],states:[{id:'wet',name:'浇湿',description:'湿衣',imagePrompt:'参考'}]}],shots:[shot],styleBible:'<风格>',uncertainties:[],scenePlans:[]},bindings:[{assetId:'character',stateId:'wet',entityId:'e1',saved:true}],dialogues:[{id:'d1',text:'<不要执行脚本>',speakerId:'c1',kind:'inner_monologue'}],characters:[{id:'c1',name:'甲'}],editVersion:0};
const selection={providerAccountId:'a',spaceId:'s'};
const revision={id:'r1',stage:'asset',status:'ready',review:'approved',createdAt:'2026-11-01',ownership:selection};
test('timeline uses real duration boundaries and clamps end',()=>{
 const shots=[{durationSeconds:5},{durationSeconds:8}];
 assert.equal(timelineAt(shots,4.99).index,0);assert.equal(timelineAt(shots,5).index,1);assert.equal(timelineAt(shots,20).end,13);
});
test('reference images require approval, current state and exact owner',()=>{
 const assets=[{id:'asset1',entityId:'e1',active:true,revisions:[revision]}];
 assert.match(referenceCards(job,shot,assets,selection,'/asset-lab/api/v1')[0].src,/thumbnail/);
 for(const patch of [{review:'pending'},{review:'changes_requested'},{status:'stale'},{ownership:{providerAccountId:'other',spaceId:'s'}}]){
  assert.equal(referenceCards(job,shot,[{...assets[0],revisions:[{...revision,...patch}]}],selection,'/api/v1')[0].src,null);
 }
 assert.equal(referenceCards({...job,stale:true},shot,assets,selection,'/api/v1')[0].src,null);
 assert.equal(referenceCards({...job,bindings:[{...job.bindings[0],changed:true}]},shot,assets,selection,'/api/v1')[0].src,null);
});
test('source dialogue stays exact and OS is labeled distinctly',()=>{
 assert.equal(dialogueText(job,shot)[0].text,'<不要执行脚本>');
 assert.equal(dialogueText(job,shot)[0].label,'甲 · 内心独白');
});
test('preview is honest about missing pictures and escapes model output',()=>{
 const html=previewFrame(job,0,{selection});
 assert.match(html,/文字图板预演/);assert.match(html,/&lt;人物&gt;/);assert.doesNotMatch(html,/<不要执行脚本>/);
 const panel=productionPanel({script:{id:'script'},analysis:{status:'ready'},job,models:[],assets:[],selection,apiBase:'/api/v1'});
 assert.match(panel,/保存分镜调整/);assert.match(panel,/分镜静帧提示词/);assert.match(panel,/视频动作提示词/);assert.match(panel,/不是生成的视频/);
});
