import test from 'node:test';
import assert from 'node:assert/strict';
import {generationContext,generationGallery,generationInspector,MASTER_STATE_ID} from '../../frontend/workflow/production-generation.js';
import {bindingPicker} from '../../frontend/workflow/production-bindings.js';
const owner={providerAccountId:'a',spaceId:'s'};
const revision=(id,stage)=>({id,stage,assetId:'library',createdAt:'2026-11-01',status:'ready',review:'pending',ownership:owner});
test('candidate galleries are stage-specific and do not imply pending approval',()=>{
 const html=generationGallery([revision('style1','style'),revision('asset1','asset')],'/api/v1',{stage:'asset',category:'character'});
 assert.doesNotMatch(html,/style1/);assert.match(html,/asset1/);assert.match(html,/保留这版状态多视图/);assert.match(html,/待人工审核/);
 const mixed=generationGallery([{...revision('old','asset'),status:'stale'},revision('current','asset')],'/api/v1',{stage:'asset',category:'character'});
 const split=mixed.indexOf('<details');
 assert.ok(split>0);assert.match(mixed.slice(0,split),/current/);assert.doesNotMatch(mixed.slice(0,split),/data-creator-keep="old"/);
 assert.match(mixed.slice(split),/查看历史版本（1）/);assert.match(mixed.slice(split),/data-creator-keep="old" disabled/);
});
test('the candidate picture selects and its separate zoom control only previews',()=>{
 const html=generationGallery([revision('candidate','style')],'/api/v1',{stage:'style',category:'character',direction:true});
 const buttons=[...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)];
 const pick=buttons.find(b=>b[1].includes('data-creator-keep'));
 assert.match(pick[1],/type="button"/);assert.match(pick[1],/aria-pressed="false"/);
 assert.match(pick[1],/选用此张作为人物形象/);assert.doesNotMatch(pick[1],/disabled|data-wf-review/);
 assert.match(pick[2],/<img /);assert.match(pick[2],/点击选用/);assert.doesNotMatch(pick[2],/<button/);
 const zoom=buttons.find(b=>b[1].includes('data-wf-review'));
 assert.match(zoom[1],/放大查看/);assert.doesNotMatch(zoom[1],/data-creator-keep|disabled/);
 assert.equal(buttons.filter(b=>b[1].includes('data-creator-keep')).length,1);
 // Setting the whole show's style is a separate explicit action.
 assert.equal(buttons.filter(b=>b[1].includes('data-creator-direction')).length,1);
 assert.doesNotMatch(pick[1],/data-creator-direction/);
});
test('only current approved candidates have selection feedback and cannot be approved twice',()=>{
 const chosen={...revision('selected','asset'),review:'approved'};
 const html=generationGallery([chosen],'/api/v1',{stage:'asset',category:'character',master:true});
 assert.match(html,/data-selected="true"/);assert.match(html,/aria-pressed="true" data-creator-keep="selected" disabled/);
 assert.match(html,/已选用/);
 const stale=generationGallery([{...chosen,status:'stale'}],'/api/v1',{stage:'asset'});
 assert.doesNotMatch(stale,/data-selected="true"|aria-pressed="true"/);
 assert.match(stale,/data-creator-keep="selected" disabled/);assert.match(stale,/历史版本/);
 const zoom=stale.match(/<button[^>]*data-wf-review="selected"[^>]*>/)[0];assert.doesNotMatch(zoom,/disabled/);
});
test('image selection preserves stage-specific decisions and a blocked selection still permits preview',()=>{
 for(const [stage,category,master,label] of [
  ['asset','character',true,'确认这版人物主多视图'],['asset','character',false,'保留这版状态多视图'],
  ['asset','scene',false,'保留这版场景多视图'],['asset','prop',false,'保留这张道具图'],
  ['storyboard',null,false,'保留这张分镜图'],['refine',null,false,'保留这版精修图']]){
  const html=generationGallery([revision('candidate',stage)],'/api/v1',{stage,category,master,busy:true});
  const pick=html.match(/<button[^>]*data-creator-keep="candidate"[^>]*>/)[0];
  assert.ok(pick.includes(label));assert.match(pick,/disabled/);
  assert.doesNotMatch(html.match(/<button[^>]*data-wf-review="candidate"[^>]*>/)[0],/disabled/);
  assert.doesNotMatch(html,/data-creator-direction=/);
 }
});
test('standard prompts distinguish people, scenes and props from the film aspect ratio',()=>{
 for(const [category,required] of [['character','头部特写'],['scene','反打视图'],['prop','白底正视图']]){
  const asset={id:'a',category,name:'物料',design:'设计',states:[{id:'base',imagePrompt:'依据原文'}]};
  const c=generationContext({result:{assets:[asset],styleBible:'统一',aspectRatio:'9:16'},job:{bindings:[]},view:{kind:'assets',index:0,stage:'asset'}});
  assert.match(c.prompt,new RegExp(required));assert.equal(c.mode.recipe,'image25_asset');
 }
});
test('all creation stages select models independently from workflow lineage',()=>{
 const options={result:{assets:[{id:'a',category:'character',name:'角色',states:[]}]},job:{status:'ready',bindings:[]},view:{kind:'assets',index:0,stage:'style'}};
 assert.equal(generationContext(options).mode.recipe,'image25_style');
 assert.equal(generationContext(options).mode.modelId,'Lib Image 2.5 Pro');
 options.generationDraft={modelId:'mj-official'};
 assert.equal(generationContext(options).mode.recipe,'image25_style');
 assert.equal(generationContext(options).mode.modelId,'mj-official');
 assert.match(generationInspector(options),/name="modelId"/);
 options.view.stage='asset';
 assert.equal(generationContext(options).mode.recipe,'image25_asset');
 assert.match(generationInspector(options),/name="modelId"/);
});
test('existing images require explicit linking and unsafe names are escaped',()=>{
 const job={bindings:[{assetId:'a',stateId:'s',saved:false,legacyCandidates:[{entityId:'old',name:'<script>'}]}],ownership:owner};
 const html=bindingPicker({job,asset:{id:'a',name:'A'},state:{id:'s',name:'Base'},assets:[],apiBase:'/api/v1'});
 assert.match(html,/确认适用，关联此档案/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test('asset defaults lead with the current subject and do not duplicate the confirmed show bible',()=>{
 const options={result:{assets:[{id:'room',name:'空庭院',category:'scene',design:'石墙与木门',states:[{id:'day',imagePrompt:'无人物的白天空庭院'}]}],styleBible:'旧风格人物说明'},job:{bindings:[]},view:{kind:'assets',index:0,stage:'style'},project:{artDirection:{notes:'其他角色穿白衣'}}};
 const c=generationContext(options);
 assert.match(c.prompt,/^本次制作对象：空庭院/);
 assert.match(c.prompt,/无人物的白天空庭院/);
 assert.doesNotMatch(c.prompt,/其他角色穿白衣|旧风格人物说明/);
});
test('state assets require the same character approved master, while style exploration has no state selector',()=>{
 const result={assets:[{id:'hero',category:'character',states:[{id:'rain',name:'雨中'}]}]};
 const job={status:'ready',ownership:owner,bindings:[{assetId:'hero',stateId:MASTER_STATE_ID,entityId:'master',saved:true},
  {assetId:'hero',stateId:'rain',entityId:'rain',saved:false},{assetId:'other',stateId:MASTER_STATE_ID,entityId:'other',saved:true}]};
 const assets=[{entityId:'master',name:'主角主多视图',active:true,revisions:[{...revision('master-image','asset'),entityId:'master',review:'approved'},
   {...revision('identity','style'),entityId:'master',review:'approved'},revision('pending','asset')]},
  {entityId:'other',active:true,revisions:[{...revision('foreign','asset'),entityId:'other',review:'approved'}]}];
 const options={result,job,view:{kind:'assets',index:0,stage:'asset',characterLayer:'state'},assets,selection:owner};
 const c=generationContext(options);
 assert.deepEqual(c.sources.map(r=>r.id),['master-image']);assert.equal(c.sources[0].sourceName,'主角主多视图');
 assert.equal(c.binding.entityId,'rain');assert.equal(c.library,undefined);assert.equal(c.mode.label,'生成此状态多视图');
 const styleOptions={...options,view:{...options.view,stage:'style'}};
 assert.equal(generationContext(styleOptions).state.id,MASTER_STATE_ID);
 assert.doesNotMatch(generationInspector(styleOptions),/data-board-generation-state/);
 const master=generationContext({...options,view:{...options.view,characterLayer:'master'}});
 assert.deepEqual(master.sources.map(r=>r.id),['identity']);assert.equal(master.mode.label,'生成人物主多视图');
 job.bindings[0].changed=true;
 assert.equal(generationContext(options).sources.length,0);
 assert.match(generationInspector(options),/请先生成并确认人物主多视图/);
});

test('only a verified upload-only failure offers a fresh preparation key',()=>{
 const result={assets:[{id:'hero',category:'character',states:[{id:'rain',name:'雨中'}]}]};
 const options={result,job:{status:'ready',bindings:[{assetId:'hero',stateId:MASTER_STATE_ID,entityId:'master'}]},
  view:{kind:'assets',index:0,stage:'asset'},assets:[],tasks:[{entityId:'master',status:'failed',error:{code:'REFERENCE_UPLOAD_FAILED'}}]};
 assert.match(generationInspector(options),/data-generation-reroll/);
 assert.match(generationInspector(options),/重新准备本次生成/);
 options.tasks[0].error.code='REFERENCE_PREFLIGHT_REJECTED';
 assert.match(generationInspector(options),/data-generation-reroll/);
 assert.match(generationInspector(options),/重新准备本次生成/);
 options.tasks[0].status='needs_attention';options.tasks[0].error.code='SUBMISSION_UNKNOWN';
 assert.doesNotMatch(generationInspector(options),/data-generation-reroll/);
 options.tasks=[{...options.tasks[0],status:'failed',createdAt:'2026-01-01T00:00:00Z',error:{code:'REFERENCE_UPLOAD_FAILED',message:'old-upload-error'}},
  {entityId:'master',status:'submitting',createdAt:'2026-01-02T00:00:00Z'}];
 assert.doesNotMatch(generationInspector(options),/old-upload-error|重新准备本次生成/);
});

test('storyboard generation carries source start state and continuity without jumping to the end state',()=>{
 const shot={id:'s1',imagePrompt:'单幅人物近景，角色抬眼。',framing:'脸部近景，另一人物在画外右侧。',startState:'人物仍在地面，手脚被绑。',endState:'镜末被救起站立。',continuity:['没有椅子，不能变成坐椅。','保持湿发和同一衬衫。'],references:[]};
 const context=generationContext({result:{shots:[shot],assets:[]},job:{},view:{kind:'shots',index:0,stage:'storyboard'}});
 assert.match(context.prompt,/单幅人物近景/);assert.match(context.prompt,/脸部近景/);
 assert.match(context.prompt,/人物仍在地面，手脚被绑/);assert.match(context.prompt,/没有椅子/);
 assert.doesNotMatch(context.prompt,/镜末被救起站立/);
 const html=generationInspector({result:{shots:[shot],assets:[]},job:{status:'ready'},view:{kind:'shots',index:0,stage:'storyboard'},generationDraft:{prompt:'保留手工草稿'},apiBase:'/api/v1'});
 assert.match(html,/data-generation-use-saved/);assert.match(html,/>保留手工草稿<\/textarea>/);
});


test('verified partial delivery permits downstream creation without hiding unresolved submissions',()=>{
 const options={result:{assets:[{id:'prop',category:'prop',name:'道具',states:[{id:'base'}]}]},
  job:{status:'ready',ownership:owner,bindings:[{assetId:'prop',stateId:'base',entityId:'e',saved:true}]},
  view:{kind:'assets',index:0,stage:'asset'},project:{artDirection:{valid:true}},
  generationDraft:{modelId:'pro'},imageContracts:{pro:{verified:true}},
  assets:[{entityId:'e',active:true,revisions:[{...revision('source','style'),review:'approved'}]}],
  tasks:[{id:'partial',entityId:'e',status:'needs_attention',providerReceipt:{id:'original'},outputs:[{revisionId:'source'}],error:{code:'PARTIAL_DELIVERY',message:'已收取 3/4 张'},canRecover:true}]};
 const submit=html=>html.match(/<button class="primary" type="submit"[^>]*>/)[0];
 assert.doesNotMatch(submit(generationInspector(options)),/disabled/);
 assert.match(generationInspector(options),/已收取 3\/4 张/);
 assert.match(generationInspector(options),/data-wf-recover="partial"/);
 options.tasks.push({entityId:'e',status:'unknown_submission'});
 assert.match(submit(generationInspector(options)),/disabled/);
 options.tasks.pop();options.tasks[0].providerReceipt=null;
 assert.match(submit(generationInspector(options)),/disabled/);
});
