import {escapeHTML as esc,assetURL,belongsToSelection,revisionLabel} from './model.js';
import {imageChoice} from './image-choices.js';
export const referencePurposes={'style':'美术风格','identity':'人物外形','scene':'场景空间','prop':'道具造型','composition':'构图姿态'};
export function extraReferences(value){
 try{const rows=typeof value==='string'?JSON.parse(value):value;return Array.isArray(rows)?rows.filter(r=>r&&typeof r.id==='string'&&Object.hasOwn(referencePurposes,r.purpose)).slice(0,19):[];}catch{return [];}
}
export function referencePool(assets,owner){return assets.filter(a=>a.active).flatMap(a=>a.revisions.filter(r=>r.status==='ready'&&r.review==='approved'&&belongsToSelection(r,owner)).map(r=>({...r,name:a.name})));}
export function chooseExtraReference(refs,pool,id,purpose,selected){
 if(!selected)return refs.filter(r=>r.id!==id);
 if(!pool.some(r=>r.id===id))throw new Error('这张图片已不可用于参考，请重新选择。');
 if(!Object.hasOwn(referencePurposes,purpose))throw new Error('请先选择参考用途。');
 if(!refs.some(r=>r.id===id)&&refs.length>=19)throw new Error('最多添加 19 张补充参考。');
 return [...refs.filter(r=>r.id!==id),{id,purpose}];
}
export function imageReferencePicker({assets=[],selection,job,apiBase,generationDraft={}}){
 const owner=job.ownership||selection,refs=extraReferences(generationDraft.extraReferences),pool=referencePool(assets,owner);
 const pending=assets.filter(a=>a.referenceOnly&&a.active).flatMap(a=>a.revisions.filter(r=>r.status==='ready'&&r.review==='pending'&&belongsToSelection(r,owner)).map(r=>({...r,name:a.name})));
 const purposes=selected=>Object.entries(referencePurposes).map(([id,name])=>`<option value="${id}" ${selected===id?'selected':''}>${esc(name)}</option>`).join('');
 return `<details class="creator-reference-picker" data-image-picker ${refs.length?'open':''}><summary>补充参考图（${refs.length}）</summary>
 <input type="hidden" name="extraReferences" value="${esc(JSON.stringify(refs))}">
 <div class="wf-form-grid"><label>搜索素材<input type="search" data-image-choice-search placeholder="搜索人物、场景、道具"></label><label>新增图片的参考用途<select name="referencePurpose" data-reference-purpose>${purposes(generationDraft.referencePurpose||'style')}</select></label></div>
 <div class="image-choice-grid">${pool.map(r=>{
  const ref=refs.find(ref=>ref.id===r.id);
  return `<div class="image-choice-item">${imageChoice({src:assetURL(apiBase,r.assetId,r.id,true),name:r.name,caption:revisionLabel(r)+' · '+r.id.slice(-6),selected:Boolean(ref),input:{type:'checkbox','data-reference-toggle':r.id},previewId:r.id,choose:'加入参考',chosen:'已加入 · 点击移除'})}${ref?`<label class="image-choice-purpose">参考用途<select data-reference-purpose-change="${esc(r.id)}">${purposes(ref.purpose)}</select></label>`:''}</div>`;
 }).join('')||'<p class="wf-muted">暂无已保留素材，可先上传或从素材库选择。</p>'}</div>
 ${refs.filter(ref=>!pool.some(r=>r.id===ref.id)).map(ref=>`<div class="wf-note">原参考已失效 · ${esc(referencePurposes[ref.purpose])}<button type="button" data-extra-reference-remove="${esc(ref.id)}">移除失效参考</button></div>`).join('')}
 <div class="wf-actions"><label class="wf-link">上传参考图<input type="file" data-image-reference-upload accept="image/png,image/jpeg,image/webp" hidden></label><button type="button" data-library-open>从 LibTV 素材库选择</button></div>
 ${pending.length?`<h4>上传图片 · 待你确认</h4><div class="image-choice-grid">${pending.map(r=>imageChoice({src:assetURL(apiBase,r.assetId,r.id,true),name:r.name,action:{'data-creator-keep':r.id},previewId:r.id,choose:'保留此图'})).join('')}</div>`:''}</details>`;
}
export function referencePrompt(refs){return refs.map(r=>referencePurposes[r.purpose]+'参考={{reference:'+r.id+'}}').join('\n');}

export function libraryPanel(state){
 if(!state?.open)return '';
 return `<section class="wf-panel creator-library-dialog" role="dialog" aria-modal="true" aria-label="LibTV 素材库"><div class="wf-section-title"><h3>LibTV 素材库</h3><button data-library-close>收起素材库</button></div><form data-wf-form="library-search"><label>素材名称<input name="name" value="${esc(state.query||'')}" maxlength="200"></label><button ${state.loading?'disabled':''}>搜索素材</button></form>${state.loading?'<p role="status">正在读取素材库…</p>':''}${state.error?`<p class="wf-note">${esc(state.error)}</p>`:''}<div class="creator-library-list">${(state.items||[]).map(item=>`<button data-library-asset="${esc(item.id)}" ${state.loading?'disabled':''}>${esc(item.name)}</button>`).join('')}</div>${!state.loading&&!state.error&&state.items?.length===0?'<p>当前查询没有可显示的素材。</p>':''}${state.detail?`<h4>${esc(state.detail.name)}</h4><div class="image-choice-grid">${state.detail.images.map(image=>imageChoice({src:image.preview,name:state.detail.name,caption:image.previewError||`图片 ${image.index+1}`,action:{'data-library-import':image.index},disabled:state.loading,previewURL:image.preview,choose:'保存为项目参考图'})).join('')}</div>`:''}<p class="wf-muted">点图复制到本项目；保留后即可加入生成参考。</p></section>`;
}
