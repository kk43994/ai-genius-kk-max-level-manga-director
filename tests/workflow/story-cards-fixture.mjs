import {mount} from '../../frontend/workflow/controller.js';
import {DraftStore} from '../../frontend/workflow/model.js';
const fixture=await fetch('/docs/screenplay-analysis-v1.example.json').then(r=>r.json());
const owner={providerAccountId:'synthetic-account',spaceId:'synthetic-space'};
const project={id:'project',name:'书店来信 · 卡片交互验收',scriptIds:['script'],version:1};
const analysis={id:'analysis',status:'ready',reviewVersion:0,resultHash:'synthetic',result:fixture.result,completedCalls:1,validationIssues:[],ownership:owner,message:'合成分析已返回'};
const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};
const drafts=new DraftStore(storage,'fixture-story','/api/v1');drafts.set('selectedProject','project');drafts.set('page','plan');
const log=message=>document.getElementById('fixture-log').textContent=message;
const api={request:async(path,options={})=>{
  if(path==='/projects')return {items:[project]};
  if(path==='/projects/project')return project;
  if(path==='/workflow/capabilities')return {scriptAnalysis:true,analysis:{models:[]}};
  if(path.endsWith('/plan'))return {version:1,entities:[],stylePrompt:''};
  if(path.endsWith('/assets'))return {items:[],coverage:{total:0,ready:0}};
  if(path.endsWith('/bundles')||path.endsWith('/prompts')||path.startsWith('/tasks?'))return {items:[]};
  if(path.endsWith('/scripts/script'))return {id:'script',text:fixture.sourceText,characters:fixture.sourceText.length,filename:'合成来信.txt'};
  if(path.endsWith('/analysis'))return {analysis:structuredClone(analysis)};
  if(path.endsWith('/production'))return {analysis:null};
  if(path==='/analyses/analysis/review'){
    analysis.result=options.body.result;analysis.reviewVersion++;analysis.manuallyEdited=true;
    log('已保存手动修改；AI 调用仍为 1 次；姓名：'+analysis.result.characters[0].name);
    return structuredClone(analysis);
  }
  throw Error('合成验收不支持此操作：'+path);
}};
const app=mount({root:document.getElementById('workflow-root'),api,storage,session:{tenant:{id:'fixture-story'},selection:owner,features:{imageGeneration:false}}});
await app.ready;
