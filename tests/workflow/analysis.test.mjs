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
  assert.match(html,/共 2 次调用/);assert.match(html,/16,000/);
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
