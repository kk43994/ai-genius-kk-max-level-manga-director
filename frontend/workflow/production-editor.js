import {escapeHTML as esc} from './model.js';

export const returnedResult = job => job?.result || job?.draftResult;
export function reviewDraft(job, legacy=null) {
  const result=structuredClone(returnedResult(job));
  if(legacy)for(const shot of result.shots)Object.assign(shot,legacy.shots?.[shot.id]||{});
  return {expectedVersion:job.reviewVersion||0,expectedEditVersion:legacy?.expectedVersion??job.editVersion??0,result};
}
// Only acknowledge the snapshot actually sent. Input remains editable while saving.
export function draftAfterSave(submitted, current, saved) {
  if(!current||JSON.stringify(current.result)===JSON.stringify(submitted.result))return null;
  return {expectedVersion:saved.reviewVersion||0,expectedEditVersion:saved.editVersion||0,result:structuredClone(current.result)};
}
export function valueAt(result,path) {
  return path.split('.').reduce((item,key)=>item&&Object.hasOwn(item,key)?item[key]:undefined,result);
}
export function setReviewValue(result,path,value) {
  const keys=path.split('.');
  if(keys.some(k=>['__proto__','constructor','prototype'].includes(k)))return false;
  const key=keys.pop(),parent=keys.reduce((item,k)=>item&&Object.hasOwn(item,k)?item[k]:undefined,result);
  if(!parent||!Object.hasOwn(parent,key))return false;
  parent[key]=value;return true;
}
export const textLines = value => String(value).split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
export function field(label,path,value,{max=2000,rows=3,number=false,ariaLabel='',lines=false}={}) {
  return `<label>${esc(label)}${number?`<input type="number" min="1" max="${max}" step="${path.endsWith('durationSeconds')?'0.5':'1'}" ${ariaLabel?`aria-label="${esc(ariaLabel)}"`:""} data-wf-production-field="${esc(path)}" value="${esc(value)}">`:rows===1&&!lines&&!String(value??'').includes('\n')?`<input type="text" maxlength="${max}" ${ariaLabel?`aria-label="${esc(ariaLabel)}"`:""} data-wf-production-field="${esc(path)}" value="${esc(value??'')}">`:`<textarea rows="${rows}" maxlength="${max}" ${lines?'data-production-lines':''} ${ariaLabel?`aria-label="${esc(ariaLabel)}"`:""} data-wf-production-field="${esc(path)}">${esc(lines?value.join('\n'):value)}</textarea>`}</label>`;
}
export function quoteEditor(items,path) {
  return items.map((item,index)=>`<div class="wf-production-quote">${field(`引用 ${index+1}`,`${path}.${index}.quote`,item.quote,{max:4000})}<div class="wf-form-grid">${field('起始行',`${path}.${index}.startLine`,item.startLine,{number:true,max:100000})}${field('结束行',`${path}.${index}.endLine`,item.endLine,{number:true,max:100000})}</div><button data-wf-source="${item.startLine}" data-wf-source-end="${item.endLine}">查看剧本原文 L${item.startLine}–${item.endLine}</button></div>`).join('');
}
export function reviewIssues(job,result) {
  const issues=job.validationIssues||[];
  if(!issues.length)return '';
  return `<details class="wf-production-issues" data-wf-production-issues><summary>核对 ${issues.length} 处问题 · 不影响查看完整结果</summary><p class="wf-muted">左侧可以直接修改；右侧是剧本原文。保存只检查内容，不调用 AI。未全部改完也可以先保存。</p>${issues.map((issue,index)=>`<article class="wf-production-issue"><h4>${esc(issue.label)}</h4><p>${esc(issue.message)}</p>${issue.message==='同一场次的镜头编号重复或顺序不连续。'?'<button data-wf-action="production-number-shots">整理镜头编号</button>':''}${issue.code==='source_quote'?`<div class="wf-production-compare"><div>${field('当前引用 · 可直接修改',issue.path+'.quote',valueAt(result,issue.path+'.quote'),{max:4000,rows:6,ariaLabel:issue.label+'的原文引用'})}<div class="wf-form-grid">${field('起始行',issue.path+'.startLine',valueAt(result,issue.path+'.startLine'),{number:true,max:100000})}${field('结束行',issue.path+'.endLine',valueAt(result,issue.path+'.endLine'),{number:true,max:100000})}</div></div><div><p><b>剧本原文 · L${issue.startLine}–${issue.endLine}</b></p><pre>${esc(issue.sourceText||'请先修正引用行号并保存，便可显示对应原文。')}</pre>${issue.sourceText?`<button data-wf-action="production-use-source" data-issue-index="${index}" aria-label="采用右侧原文 · ${esc(issue.label)}">采用右侧原文</button>`:''}<p data-wf-issue-change="${index}" class="wf-muted"></p></div></div>`:'<p class="wf-muted">可在下方物料状态、镜头引用与提示词中修改，然后保存检查。</p>'}</article>`).join('')}</details>`;
}
export function reviewSaveBar(job,draft,busy) {
  return `<div class="wf-production-savebar"><div><b data-wf-production-draft-status>${draft?'有修改尚未保存检查':'内容可直接编辑'}</b><p class="wf-muted">保留 AI 原始返回 · 保存不消耗积分</p></div><div class="wf-actions"><button class="primary" data-wf-action="production-review-save" ${busy||job.stale?'disabled':''}>保存修改并检查</button><button data-wf-action="production-review-discard" ${busy?'disabled':''}>恢复已保存内容</button></div></div>`;
}
