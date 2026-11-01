import test from 'node:test';
import assert from 'node:assert/strict';
import {promptPanel, promptIssue, usablePrompt} from '../../frontend/workflow/prompts.js';
const entity={id:'entity',name:'仓库',version:1};
const job={id:'prompt',entityId:'entity',entityVersion:1,styleVersion:1,status:'ready',model:'GVLM 3.1',completedCalls:1,
  result:{usable:true,summary:'仓库夜间室内',scriptFacts:[{detail:'室内',evidence:{startLine:1,endLine:1,quote:'仓库 夜 内'}}],
    creativeChoices:['混凝土地面'],uncertainties:['原文未写建筑材质'],variants:[],exclusions:['不添加人物'],
    prompts:{style:'<script>原文</script> 夜间室内仓库空镜，窗外雷电。'}}};
test('source facts, visual choices and actual stage prompt are distinct and escaped',()=>{
  const html=promptPanel({job,entity,stage:'style',enabled:true,connected:true});
  for(const name of ['剧本事实','视觉设计选择','尚未明确的信息','仓库 夜 内','混凝土地面','本阶段完整提示词'])assert.ok(html.includes(name));
  assert.ok(!html.includes('<script>'));assert.match(html,/使用这份提示词/);
});
test('unfinished and ambiguous original requests have no paid retry button',()=>{
  for(const status of ['running','unknown_submission']){
    const html=promptPanel({job:{...job,status,result:null,canRefresh:true},entity,stage:'style'});
    assert.doesNotMatch(html,/data-wf-action="prompt-generate"/);
    assert.match(html,/data-wf-action="prompt-refresh"/);
    if(status==='running')assert.match(html,/<progress/);
    else assert.doesNotMatch(html,/<progress/);
  }
});
test('stale or unusable AI cannot overwrite draft or proceed; explicit manual entry remains possible',()=>{
  const draft={prompt:'完整的剧本提示词',promptJobId:'prompt'};
  assert.equal(promptIssue({draft,job,entity,styleVersion:1}),'');
  for(const bad of [{...job,stale:true},{...job,result:{...job.result,usable:false}},{...job,entityVersion:2}]){
    assert.ok(promptIssue({draft,job:bad,entity,styleVersion:1}));
  }
  assert.equal(usablePrompt({...job,stale:true}),false);
  assert.equal(promptIssue({draft:{...draft,manualPrompt:true},entity,styleVersion:1}),'');
  assert.ok(promptIssue({draft:{prompt:'请填写希望采用的视觉风格。',manualPrompt:true},entity}));
});
