import test from 'node:test';
import assert from 'node:assert/strict';
import {storyCards} from '../../frontend/workflow/story-cards.js';
import {overviewShots,storyboardOverview} from '../../frontend/workflow/storyboard-overview.js';
const owner={providerAccountId:'owner',spaceId:'personal'};
function fixture(){
 const shot={id:'shot-1',sceneId:'scene-a',purpose:'接过来信',beat:'拿起信封',framing:'近景',durationSeconds:5,dialogueIds:['line-1'],references:[{assetId:'person',stateId:'rain',revisionId:'person-rain'}],startState:'信在桌上',endState:'信在右手',continuity:['右手持信'],performance:'克制',camera:'固定',sound:'雨声'};
 const job={id:'job',status:'ready',ownership:owner,characters:[{id:'person',name:'甲'}],dialogues:[{id:'line-1',speakerId:'person',kind:'inner_monologue',text:'<这封信>\n终于到了。'}],result:{assets:[{id:'person',name:'甲',category:'character',states:[{id:'rain',name:'雨中'}]},{id:'room',name:'旧书店',category:'scene',states:[{id:'night',name:'夜晚'}]}],shots:[shot,{...shot,id:'shot-2',sceneId:'scene-b',dialogueIds:[],purpose:'走向门口',references:[]}]},bindings:[{assetId:'person',stateId:'__character_master__',entityId:'master',saved:true},{assetId:'person',stateId:'rain',entityId:'rain',saved:true},{assetId:'room',stateId:'night',entityId:'room',saved:true}],shotBindings:[{shotId:'shot-1',entityId:'shot-1'},{shotId:'shot-2',entityId:'shot-2'}]};
 const revision=(id,stage='asset',review='approved')=>({id,assetId:`a-${id}`,stage,review,status:'ready',ownership:owner,createdAt:'2026-11-02'});
 const assets=['master','rain','room','shot-1','shot-2'].map((id,i)=>({id:`a-${id}`,entityId:id,active:true,revisions:[revision(['person-master','person-rain','room-night','s1-image','s2-image'][i],i>2?'storyboard':'asset',i===4?'pending':'approved')]}));
 const coverage={entities:[{shotId:'shot-1',designCurrent:true},{shotId:'shot-2',designCurrent:true}],exportRevisionIds:['s1-image']};
 return {job,assets,coverage,selection:owner,analysis:{result:{scenes:[{id:'scene-a',title:'书店内'},{id:'scene-b',title:'书店门口'}]}}};
}
test('overview puts exact source dialogue beneath the image and includes master, state and scene sheets',()=>{
 const html=storyboardOverview(fixture());
 for(const value of ['分镜总览','人物主多视图','雨中','旧书店','夜晚','角色台词','甲 · 内心独白','&lt;这封信&gt;<br>终于到了。','上一镜结束','信在右手','2 个镜头 · 1 张已保留 · 1 镜待处理'])assert.ok(html.includes(value),value);
 assert.ok(html.indexOf('alt="分镜 001"')<html.indexOf('&lt;这封信&gt;'));
 assert.ok(html.indexOf('镜头 001')<html.indexOf('镜头 002'));
 assert.doesNotMatch(html,/<这封信>/);
 assert.match(html,/data-overview-master="true"/);assert.match(html,/data-overview-shot="1"/);
 assert.match(html,/aria-label="查看本镜参考 甲 · 雨中"/);
});
test('current pending and rejected results remain visible but are never counted as kept',()=>{
 const data=fixture();let rows=overviewShots(data);assert.equal(rows[1].revision.id,'s2-image');assert.equal(rows[1].ready,false);assert.equal(rows[1].status,'pending');
 data.assets[4].revisions[0].review='changes_requested';assert.equal(overviewShots(data)[1].status,'changes_requested');
 data.assets[4].revisions[0].review='approved';assert.equal(overviewShots(data)[1].ready,false,'approval without delivery eligibility is not completion');
});
test('stale designs, stale jobs and foreign owner images never appear as current frames',()=>{
 for(const change of [d=>d.coverage.entities[0].designCurrent=false,d=>d.job.stale=true,d=>d.assets[3].revisions[0].ownership={...owner,spaceId:'other'}]){
  const data=fixture();change(data);const row=overviewShots(data)[0];assert.equal(row.revision,null);assert.equal(row.ready,false);
 }
 const data=fixture();data.job.bindings[1].changed=true;
 const html=storyboardOverview(data);assert.doesNotMatch(html,/aria-label="查看本镜参考 甲 · 雨中"/);assert.match(html,/参考待补/);
});
test('filters preserve original numbering and scene order; drafts do not change the saved view',()=>{
 const data=fixture();const pending=storyboardOverview({...data,filter:'attention'});assert.doesNotMatch(pending,/id="overview-shot-001"/);assert.match(pending,/id="overview-shot-002"/);
 const scene=storyboardOverview({...data,scene:'scene-a',unsaved:true});assert.match(scene,/id="overview-shot-001"/);assert.doesNotMatch(scene,/id="overview-shot-002"/);assert.match(scene,/这里展示已保存方案/);assert.doesNotMatch(scene,/storyboard-export/);
});
test('an unknown original generation is labeled for lookup rather than shown as never generated',()=>{
 const data=fixture();data.assets[4].revisions=[];data.tasks=[{entityId:'shot-2',status:'needs_attention',ownership:owner}];
 const html=storyboardOverview(data);assert.match(html,/原任务待查询/);assert.match(html,/查看生成任务/);
});

test('unified canvas lays every saved shot out before images, then fills the same node',()=>{
 const data=fixture();const result={characters:[],events:[],dialogues:[],...data.analysis.result};
 data.assets[3].revisions=[];data.assets[4].revisions=[];
 const before=JSON.stringify(data),empty=storyCards(result,{overview:data,shots:overviewShots(data)});
 assert.match(empty,/data-story-node="shot:shot-1"/);assert.match(empty,/data-story-node="shot:shot-2"/);
 assert.equal((empty.match(/画面待补 · 分镜与台词已保留/g)||[]).length,2);
 assert.match(empty,/&lt;这封信&gt;<br>终于到了。/);assert.match(empty,/data-story-node="asset:person:__character_master__"/);
 assert.equal(JSON.stringify(data),before,'laying cards out does not mutate jobs or create requests');
 data.assets[3].revisions=fixture().assets[3].revisions;
 const filled=storyCards(result,{overview:data,shots:overviewShots(data)});
 assert.match(filled,/data-story-node="shot:shot-1"/);assert.match(filled,/alt="分镜 001"/);assert.match(filled,/2 镜 · 1 张已选 · 1 镜待处理/);
});
test('saved shots with a removed scene remain correctable and stale versions remain reachable',()=>{
 const data=fixture();data.coverage.entities[0].designCurrent=false;data.assets[3].revisions[0].status='stale';
 const html=storyCards({characters:[],scenes:[],events:[],dialogues:[]},{overview:data,shots:overviewShots(data)});
 assert.match(html,/场次待核对/);assert.match(html,/data-story-node="shot:shot-1"/);
 assert.match(html,/data-wf-review="s1-image">历史版本/);assert.doesNotMatch(html,/alt="分镜 001"/);
 assert.doesNotMatch(html,/data-wf-analysis-record="scenes.-1"/);
});
test('unified canvas keeps unsaved edits separate and withholds export links',()=>{
 const data=fixture();data.unsaved=true;
 const html=storyCards({characters:[],...data.analysis.result},{overview:data,shots:overviewShots(data)});
 assert.match(html,/有修改尚未保存/);assert.doesNotMatch(html,/storyboard-export/);
 assert.match(html,/data-story-node="shot:shot-2"/);assert.match(html,/待审核/);
});
