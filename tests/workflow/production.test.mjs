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
 assert.equal(referenceCards(job,shot,[{...assets[0],revisions:[{...revision,stage:'style'}]}],selection,'/api/v1')[0].src,null);
 const pinned={...shot,references:[{...shot.references[0],revisionId:'missing'}]};
 assert.equal(referenceCards(job,pinned,assets,selection,'/api/v1')[0].src,null,'missing pin never falls back to newer image');
});
test('source dialogue stays exact and OS is labeled distinctly',()=>{
 assert.equal(dialogueText(job,shot)[0].text,'<不要执行脚本>');
 assert.equal(dialogueText(job,shot)[0].label,'甲 · 内心独白');
});
test('preview is honest about missing pictures and escapes model output',()=>{
 const html=previewFrame(job,0,{selection});
 assert.match(html,/文字图板预演/);assert.match(html,/&lt;人物&gt;/);assert.doesNotMatch(html,/<不要执行脚本>/);
 const panel=productionPanel({script:{id:'script'},analysis:{status:'ready'},job,models:[],assets:[],selection,apiBase:'/api/v1'});
 assert.match(panel,/制作流水线/);assert.match(panel,/保存修改/);
 assert.doesNotMatch(panel,/<textarea/);
 const editor=productionPanel({script:{id:'script'},job,models:[],selection,view:{inspector:'shots',index:0}});
 assert.match(editor,/分镜静帧提示词/);assert.match(editor,/视频动作提示词/);
 const preview=productionPanel({script:{id:'script'},job,models:[],selection,view:{inspector:'preview'}});
 assert.match(preview,/不是生成的视频/);
});


test('minor validation failures expose all work and offer manual corrections',()=>{
 const draftJob={...job,status:'needs_review',result:null,draftResult:job.result,bindings:[],validationIssues:[{code:'source_quote',path:'assets.0.evidence.0',label:'人物引用',message:'核对引用',sourceText:'原文 <不能执行>',startLine:1,endLine:1}]};
 const html=productionPanel({script:{id:'script'},job:draftJob,models:[],selection});
 assert.match(html,/查看物料/);assert.match(html,/查看镜头/);
 assert.match(html,/1 处待核对/);
 const issuePanel=productionPanel({script:{id:'script'},job:draftJob,models:[],selection,view:{inspector:'issues'}});
 assert.match(issuePanel,/采用右侧原文/);assert.match(issuePanel,/原文 &lt;不能执行&gt;/);
 const handoff=productionPanel({script:{id:'script'},job:draftJob,models:[],selection,view:{inspector:'handoff'}});
 assert.match(handoff,/data-wf-action="production-plan" disabled/);
 assert.match(previewFrame(draftJob,0,{selection}),/看清信封/);
});


test('canvas keeps all assets, shots and preview on one surface with real links',async()=>{
 const {boardLayout}=await import('../../frontend/workflow/production-board.js');
 const result=structuredClone(job.result);result.shots.push({...shot,id:'s2'});
 const layout=boardLayout(result);
 assert.equal(layout.nodes.filter(n=>n.kind==='assets').length,1);
 assert.equal(layout.nodes.filter(n=>n.kind==='shots').length,2);
 assert.equal(layout.edges.filter(e=>e.kind==='reference').length,2);
 assert.equal(layout.edges.filter(e=>e.kind==='sequence').length,1);
 assert.equal(layout.edges.filter(e=>e.kind==='output').length,1);
 const html=productionPanel({script:{id:'script'},job:{...job,result},models:[],selection,view:{inspector:'shots',index:0}});
 assert.equal((html.match(/data-board-viewport /g)||[]).length,1);
 assert.match(html,/查看物料/);assert.match(html,/查看镜头 002/);assert.match(html,/打开图板预演/);
 assert.match(html,/board-edge reference is-active/);
 assert.equal((html.match(/data-wf-production-field="shots\.0\.purpose"/g)||[]).length,1);
 assert.doesNotMatch(html,/data-wf-production-field="shots\.1\.purpose"/);
 assert.doesNotMatch(html,/role="tablist"/);
});

test('canvas drawer renders preview controls and only selected eligible storyboard images',()=>{
 const shotRevision={...revision,id:'shot-picture',assetId:'shot-media',entityId:'shot-entity',stage:'storyboard'};
 const readyJob={...job,shotBindings:[{shotId:'s1',entityId:'shot-entity'}]};
 const o={script:{id:'script'},job:readyJob,phase:'canvas',view:{inspector:'preview'},assets:[{id:'shot-media',entityId:'shot-entity',active:true,revisions:[shotRevision]}],selection,coverage:{entities:[{shotId:'s1',designCurrent:true}],exportRevisionIds:['shot-picture']}};
 const html=productionPanel(o);assert.match(html,/播放预演/);assert.match(html,/alt="已选分镜 1"/);assert.match(html,/回到当前镜头/);assert.doesNotMatch(html,/data-board-viewport/);
 const pending=structuredClone(o);pending.assets[0].revisions[0].review='pending';assert.doesNotMatch(productionPanel(pending),/alt="已选分镜 1"/);
});
