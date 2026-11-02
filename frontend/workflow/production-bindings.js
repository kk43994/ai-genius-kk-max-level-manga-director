import {escapeHTML as esc, assetURL, belongsToSelection} from './model.js';
import {imageChoice} from './image-choices.js';

export function bindingPicker({job,asset,state,assets=[],apiBase,busy,changed}) {
  const binding=job.bindings?.find(b=>b.assetId===asset?.id&&b.stateId===state?.id);
  if(!binding)return '';
  const candidates=[...(binding.legacyCandidates||[])];
  if(binding.linked)candidates.unshift({entityId:binding.entityId,name:binding.name});
  if(!candidates.length)return '';
  return `<details class="creator-binding" ${!binding.saved||binding.changed?'open':''}><summary>${binding.changed?'重新核对档案关联':binding.linked?'已关联：'+esc(binding.name):'使用已有档案与图片'}</summary><p class="wf-muted">确认适用于「${esc(asset.name)} · ${esc(state.name)}」后关联，原图和审核记录保留。</p>${candidates.map(c=>{
    const images=(assets.find(a=>a.entityId===c.entityId)?.revisions||[]).filter(r=>belongsToSelection(r,job.ownership)).slice(0,4);
    const selected=binding.entityId===c.entityId&&!binding.changed,disabled=busy||changed||job.stale||selected;
    return `<article><b>${esc(c.name)}</b>${images.length?`<div class="image-choice-grid">${images.map(r=>imageChoice({src:assetURL(apiBase,r.assetId,r.id,true),name:c.name,caption:'关联档案 · 保留原审核状态',selected,disabled,previewId:r.id,choose:'确认适用，关联此档案',chosen:'当前关联档案',action:{'data-production-bind':c.entityId,'data-binding-asset':asset.id,'data-binding-state':state.id}})).join('')}</div>`:`<button type="button" data-production-bind="${esc(c.entityId)}" data-binding-asset="${esc(asset.id)}" data-binding-state="${esc(state.id)}" ${disabled?'disabled':''}>${selected?'当前关联档案':'确认适用，关联此档案'}</button>`}</article>`;
  }).join('')}${changed?'<p>先保存方案修改，再确认关联。</p>':''}</details>`;
}
