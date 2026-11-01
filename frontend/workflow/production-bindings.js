import {escapeHTML as esc, assetURL, belongsToSelection} from './model.js';

export function bindingPicker({job,asset,state,assets=[],apiBase,busy,changed}) {
  const binding=job.bindings?.find(b=>b.assetId===asset?.id&&b.stateId===state?.id);
  if(!binding)return '';
  const candidates=[...(binding.legacyCandidates||[])];
  if(binding.linked)candidates.unshift({entityId:binding.entityId,name:binding.name});
  if(!candidates.length)return '';
  return `<details class="creator-binding" ${!binding.saved||binding.changed?'open':''}><summary>${binding.changed?'重新核对档案关联':binding.linked?'已关联：'+esc(binding.name):'使用已有档案与图片'}</summary><p class="wf-muted">确认适用于「${esc(asset.name)} · ${esc(state.name)}」后关联，原图和审核记录保留。</p>${candidates.map(c=>{
    const images=(assets.find(a=>a.entityId===c.entityId)?.revisions||[]).filter(r=>belongsToSelection(r,job.ownership)).slice(0,4);
    return `<article><b>${esc(c.name)}</b><div class="creator-binding-images">${images.map(r=>`<button type="button" data-wf-review="${esc(r.id)}"><img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="${esc(c.name)} 历史候选"></button>`).join('')}</div><button type="button" data-production-bind="${esc(c.entityId)}" data-binding-asset="${esc(asset.id)}" data-binding-state="${esc(state.id)}" ${busy||changed||job.stale?'disabled':''}>${binding.entityId===c.entityId&&!binding.changed?'当前关联档案':'确认适用，关联此档案'}</button></article>`;
  }).join('')}${changed?'<p>先保存方案修改，再确认关联。</p>':''}</details>`;
}
