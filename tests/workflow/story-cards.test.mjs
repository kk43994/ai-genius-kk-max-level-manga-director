import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {storyCards} from '../../frontend/workflow/story-cards.js';
import {analysisPanel} from '../../frontend/workflow/analysis.js';

const fixture=JSON.parse(readFileSync(new URL('../../docs/screenplay-analysis-v1.example.json',import.meta.url)));
test('story cards join actual cast and verbatim dialogue by scene, preserve source data',()=>{
  const result=structuredClone(fixture.result);
  result.scenes.push({...result.scenes[0],id:'scene_2',title:'后续场次',order:2,presentCharacterIds:[],mentionedCharacterIds:['char_lin']});
  result.scenes.reverse();
  const before=JSON.stringify(result),html=storyCards(result);
  assert.ok(html.indexOf('书店门口交信')<html.indexOf('后续场次'));
  const second=html.split('id="story-scene-1"')[1].split('</article>')[0];
  assert.match(second,/仅被提及：林舟/);
  assert.doesNotMatch(second,/story-person-chip|这封信，是留给你的/);
  for(const line of result.dialogues)assert.ok(html.includes(line.text));
  assert.match(html,/人物示意/);assert.doesNotMatch(html,/原文未说明|<img /);
  assert.equal(JSON.stringify(result),before);
});
test('only eligible selected frames decorate their own scene; rejected or pending rows are ignored',()=>{
  const row={shot:{sceneId:'scene_1'},ready:true,index:0,revision:{id:'rev_1',assetId:'asset_1'}};
  const html=storyCards(fixture.result,{shots:[row,{...row,ready:false,revision:{id:'pending',assetId:'asset_1'}},{...row,shot:{sceneId:'other'},revision:{id:'wrong',assetId:'asset_1'}}],apiBase:'/asset-lab/api/v1'});
  assert.match(html,/已选分镜 · 1 张/);assert.match(html,/\/asset-lab\/api\/v1\/assets\/asset_1\/thumbnail\?revisionId=rev_1/);
  assert.doesNotMatch(html,/revisionId=pending|revisionId=wrong|人物示意/);
});
test('linked dialogue warnings remain visible on collapsed scene and open details retain correction paths',()=>{
  const html=storyCards(fixture.result,{issues:[{path:'dialogues.0.text'}]});
  assert.match(html,/story-card-flagged/);assert.match(html,/story-line-flagged/);
  assert.match(html,/data-wf-analysis-record="dialogues.0"/);
  assert.match(html,/data-wf-analysis-record="scenes.0"/);
  assert.match(html,/data-wf-source="1"/);
});
test('script text is escaped in cards, names, metadata and relationship labels',()=>{
  const result=structuredClone(fixture.result);
  result.characters[0].name='<img src=x onerror=x>';
  result.scenes[0].title='<script>alert(1)</script>';
  result.dialogues[0].text='<svg onload=x>';
  const html=storyCards(result);
  assert.doesNotMatch(html,/<script>|<img src=x|<svg onload/);
  assert.match(html,/&lt;svg onload=x&gt;/);
});
test('results lead with cards while source editing remains collapsed and source-addressable',()=>{
  const html=analysisPanel({script:{filename:'example.txt',text:fixture.sourceText},analysis:{id:'ana',status:'ready',result:fixture.result,completedCalls:1},enabled:true,connected:true});
  assert.ok(html.indexOf('story-board')<html.indexOf('data-analysis-details'));
  assert.match(html,/<details class="story-analysis-details" data-analysis-details >/);
  assert.match(html,/data-analysis-record="characters.0"/);
  assert.match(html,/data-wf-analysis-field="characters.0.name"/);
});

test('first analysis fills a fixed story framework without a shot plan or image task',()=>{
 const result=structuredClone(fixture.result);result.dialogues.push({...result.dialogues[0],id:'unassigned',eventId:null,text:'尚未关联事件的原文。'});
 const before=JSON.stringify(result),html=storyCards(result);
 const beats=html.match(/<article class="story-beat"[\s\S]*?<\/article>/g)||[];
 assert.equal(beats.length,result.events.length+1);
 for(const line of result.dialogues)assert.equal(beats.filter(card=>card.includes(line.text)).length,1,'every source line has one framework slot');
 assert.match(html,/剧情框架已铺开/);assert.match(html,/画面稍后补充/);
 assert.doesNotMatch(html,/data-story-node="shot:|生成分镜图|<img /);
 assert.match(html,/data-wf-analysis-record="events.0"/);
 assert.equal(JSON.stringify(result),before);
});
