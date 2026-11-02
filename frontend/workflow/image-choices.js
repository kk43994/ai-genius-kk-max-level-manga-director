import {escapeHTML as esc,assetURL,revisionLabel} from './model.js';

const attrs=values=>Object.entries(values).map(([name,value])=>`${name}="${esc(String(value))}"`).join(' ');
const check='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>';
const expand='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/></svg>';

// Native radio/checkbox inputs preserve form values and keyboard behavior.
// Action cards use explicit buttons; previews are siblings, never nested controls.
export function imageChoice({src,name,caption='',selected=false,disabled=false,input,action={},previewId,previewURL,choose='点击选用',chosen='已选用'}){
 const locked=disabled||!src,identity=[name,caption].filter(Boolean).join(' · ');
 const contents=`${src?`<img src="${esc(src)}" alt="${esc(name)}" loading="lazy">`:'<span class="image-choice-missing">暂无预览图</span>'}<span class="image-choice-badge">${check}<span class="image-choice-off">${esc(choose)}</span><span class="image-choice-on">${esc(chosen)}</span></span>`;
 const pick=input?`<label class="image-choice-pick"><input ${attrs(input)} ${selected?'checked':''} ${locked?'disabled':''} aria-label="${esc(choose+' '+identity)}">${contents}</label>`:`<button type="button" class="image-choice-pick" ${attrs(action)} aria-label="${esc(choose+' '+identity)}" aria-pressed="${selected}" ${locked?'disabled':''}>${contents}</button>`;
 const preview=previewId?`<button type="button" class="image-choice-preview" data-wf-review="${esc(previewId)}" aria-label="放大查看 ${esc(identity)}" title="放大查看">${expand}</button>`:previewURL&&/^(https?:\/\/|\/(?!\/))/.test(previewURL)?`<a class="image-choice-preview" href="${esc(previewURL)}" target="_blank" rel="noopener" aria-label="放大查看 ${esc(identity)}" title="放大查看">${expand}</a>`:'';
 return `<figure class="image-choice" ${input?'':`data-selected="${selected}"`}><div class="image-choice-media">${pick}${preview}</div><figcaption><b>${esc(name)}</b>${caption?`<small>${esc(caption)}</small>`:''}</figcaption></figure>`;
}

export function sourceImagePicker(rows,selectedId,apiBase,{name='sourceRevisionId',title='选择参考图',attributes={},required=true}={}){
 return `<fieldset class="image-choice-field" data-image-picker><legend>${esc(title)}</legend>${rows.length>6?'<input type="search" data-image-choice-search aria-label="搜索参考图" placeholder="搜索参考图">':''}<div class="image-choice-grid">${rows.map(r=>imageChoice({src:assetURL(apiBase,r.assetId,r.id,true),name:r.sourceName||r.name||revisionLabel(r),caption:revisionLabel(r)+' · '+r.id.slice(-6),selected:r.id===selectedId,input:{type:'radio',name,value:r.id,...(required?{required:''}:{}),...attributes},previewId:r.id,choose:'用作参考',chosen:'已选参考'})).join('')||'<p class="wf-muted">暂无可用的已审核图片</p>'}</div>${selectedId&&!rows.some(r=>r.id===selectedId)?'<p class="wf-note">原参考版本已不可用，请重新选图。</p>':''}</fieldset>`;
}
