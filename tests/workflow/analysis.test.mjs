import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {analysisPanel,sourceView} from '../../frontend/workflow/analysis.js';
const example=JSON.parse(readFileSync(new URL('../../docs/screenplay-analysis-v1.example.json',import.meta.url)));
const script={id:'scr_fixture',filename:'<script>测试</script>.txt',characters:example.sourceText.length,text:example.sourceText};
const base={script,enabled:true,connected:true};
test('AI panel requires explicit spend confirmation and distinguishes six categories',()=>{
  const html=analysisPanel(base);
  assert.match(html,/data-wf-analysis-spend/);assert.doesNotMatch(html,/checked/);
  assert.match(html,/默认 1 次 AI 调用/);assert.match(html,/16,000/);
  assert.ok(!html.includes('<script>测试'));
});
test('ready results expose literal dialogue, source links and human review gate',()=>{
  const html=analysisPanel({...base,analysis:{id:'ana_fixture',status:'ready',completedCalls:2,message:'复核完成',result:example.result}});
  for(const name of ['角色','场景','时间','地点','事件','台词'])assert.ok(html.includes(name));
  for(const d of example.result.dialogues)assert.ok(html.includes(d.text));
  assert.match(html,/data-wf-source="\d+"/);assert.match(html,/data-wf-analysis-reviewed/);
  assert.match(html,/data-wf-action="analysis-plan"/);assert.doesNotMatch(html,/aria-label="AI 分析处理中/);
});
test('running and uncertain receipts keep status feedback and do not offer new paid request',()=>{
  for(const status of ['running','unknown_submission']){
    const html=analysisPanel({...base,analysis:{id:'ana_fixture',status,canRefresh:true,completedCalls:0,message:'等待实际回执'}});
    if(status==='running')assert.match(html,/<progress aria-label/);
    else assert.doesNotMatch(html,/<progress/);
    assert.doesNotMatch(html,/<progress[^>]*value=/);
    assert.match(html,/data-wf-action="analysis-refresh"/);assert.doesNotMatch(html,/data-wf-action="analyze"/);
  }
});
test('source text is escaped and line-addressable, oversized script cannot start',()=>{
  const html=sourceView({...script,text:'<img src=x onerror=alert(1)>\n第二行'});
  assert.doesNotMatch(html,/<img/);assert.match(html,/data-wf-line="2"/);
  assert.match(analysisPanel({...base,script:{...script,text:'字'.repeat(16001)}}),/data-wf-action="analyze" disabled/);
});
test('model selector uses provider names, preserves selection and displays pinned running model',()=>{
  const models=[{id:'aurora-3-prime',name:'GVLM 3.1'},{id:'cvlm-5.5',name:'CVLM 5.5'}];
  const html=analysisPanel({...base,models,modelId:'cvlm-5.5'});
  assert.match(html,/data-wf-analysis-model/);assert.match(html,/value="cvlm-5.5" selected/);
  assert.doesNotMatch(html,/GPT|Claude/);
  const running=analysisPanel({...base,models,modelId:'aurora-3-prime',analysis:{id:'ana',model:'CVLM 5.5',status:'running',completedCalls:0,canRefresh:true,message:'分析中'}});
  assert.match(running,/LibTV · CVLM 5.5/);assert.doesNotMatch(running,/data-wf-analysis-model/);
});
test('repair progress uses the actual call budget, never a hard-coded 3 over 2',()=>{
  const html=analysisPanel({...base,analysis:{id:'analysis',model:'GVLM 3.1',status:'reviewing',phase:'repair2',
    completedCalls:3,totalCalls:4,displayNumber:1,canRefresh:true,message:'正在修复台词分段',phaseStartedAt:new Date(Date.now()-150000).toISOString()}});
  assert.match(html,/3 \/ 4 次/);assert.doesNotMatch(html,/3 \/ 2 次/);
  assert.match(html,/编号 001/);assert.match(html,/等待时间较长/);
});

test('returned invalid analysis is shown with red issue comparison and manual save',()=>{
  const draft=structuredClone(example.result);draft.characters[0].evidence[0].quote='<bad>引用';
  const html=analysisPanel({...base,analysis:{id:'ana_fixture',status:'needs_review',completedCalls:1,structuredDraft:true,
    draftResult:draft,validationIssues:[{path:'characters.0.evidence.0.quote',code:'source_quote',label:'角色',
      returnedText:'<bad>引用',sourceText:'逐字原文',message:'引用不一致'}]}});
  assert.match(html,/analysis-flagged/);assert.match(html,/analysis-issue/);
  assert.match(html,/逐字原文/);assert.match(html,/&lt;bad&gt;引用/);assert.doesNotMatch(html,/<bad>/);
  assert.match(html,/data-wf-analysis-field="characters.0.evidence.0.quote"/);
  assert.match(html,/analysis-review-save/);assert.match(html,/analysis-use-source/);
  assert.doesNotMatch(html,/data-wf-action="open-production-plan"/);
});
