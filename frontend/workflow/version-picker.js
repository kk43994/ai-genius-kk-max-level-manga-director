import {escapeHTML as esc,assetURL,belongsToSelection,revisionLabel} from './model.js';
import {imageChoice} from './image-choices.js';
import {imageModelPicker,selectedImageModel} from './image-models.js';

export function versionTarget(job,revision){
 if(!job||job.stale||job.status!=='ready'||revision.referenceOnly)return null;
 if(revision.stage==='storyboard'){
  const binding=job.shotBindings?.find(b=>b.entityId===revision.entityId&&!b.changed);
  return binding?{shotId:binding.shotId,recipe:'image25_storyboard'}:null;
 }
 const binding=job.bindings?.find(b=>b.entityId===revision.entityId&&b.saved&&!b.changed);
 const recipe={style:'image25_style',asset:'image25_asset',refine:'nano_refine'}[revision.stage];
 return binding&&recipe?{assetId:binding.assetId,stateId:binding.stateId,recipe}:null;
}

export function versionPicker({asset,revision:r,job,selection,apiBase,reroll=false,draft={},catalog,contracts,loading,error,actionError,busy=false}){
 const rows=asset.revisions.filter(v=>v.stage===r.stage&&belongsToSelection(v,r.ownership));
 const current=rows.find(v=>v.status==='ready'&&v.review==='approved');
 const number=v=>rows.findIndex(row=>row.id===v.id)+1;
 const valid=(r.status==='ready'||Boolean(r.reconfirmation))&&belongsToSelection(r,selection),target=versionTarget(job,r);
 const picture=(v,title)=>`<figure><img src="${esc(assetURL(apiBase,v.assetId,v.id,false))}" alt="${esc(title)} V${number(v)}"><figcaption>${esc(title)} · V${number(v)}</figcaption></figure>`;
 const chosen=selectedImageModel(draft,catalog),canPrepare=Boolean(contracts?.[chosen.id]?.verified)&&!loading&&!busy;
 return `<section class="wf-panel version-picker" data-review-detail tabindex="-1" aria-label="${esc(asset.name)} 版本选择">
 <div class="wf-section-title"><div><h3>${esc(asset.name)}</h3><span class="wf-muted">${esc(revisionLabel(r))} · ${rows.length} 个版本</span></div><button type="button" data-wf-action="close-review">关闭</button></div>
 ${actionError?`<p class="wf-note wf-error" role="alert">${esc(actionError)}</p>`:''}
 <div class="version-content"><div class="version-preview ${current&&current.id!==r.id?'is-comparison':''}">${current&&current.id!==r.id?picture(current,'当前选用'):''}${picture(r,current?.id===r.id?'当前选用':'正在查看')}</div>
 <aside class="version-sidebar"><div class="version-strip" aria-label="点击图片选用版本">${rows.map(v=>imageChoice({src:assetURL(apiBase,v.assetId,v.id,true),name:`V${number(v)}`,caption:v.status!=='ready'?(v.reconfirmation?'镜头方案已调整':'依据已变化'):v.review==='approved'?'当前选用':'',selected:v.review==='approved'&&v.status==='ready',disabled:busy||!belongsToSelection(v,selection),action:{'data-version-select':v.id},previewId:v.id,choose:v.status==='ready'?'选用':'查看',chosen:'当前选用'})).join('')}</div>
 <div class="wf-actions version-actions"><button type="button" class="primary" data-version-reroll="${esc(r.id)}" ${!valid||!target||busy?'disabled':''}>重抽</button><a class="wf-link" href="${esc(assetURL(apiBase,r.assetId,r.id,false))}" target="_blank" rel="noopener">打开原图</a></div>
 ${r.status!=='ready'?`<div class="wf-note">${r.reconfirmation?esc(r.reconfirmation.message):'这版的人物、风格或其他制作依据已变化，仍可查看原图。'}${r.reconfirmation?`<button type="button" class="primary" data-version-confirm="${esc(r.id)}" ${busy||!belongsToSelection(r,selection)?'disabled':''}>仍选用 V${number(r)}</button>`:''}</div>`:''}</aside></div>
 ${reroll?`<form data-wf-form="version-reroll" data-revision-id="${esc(r.id)}" class="version-reroll">
 <div class="version-edit-source"><img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="重抽参考原图 V${number(r)}"><p>以 V${number(r)} 为参考重抽<br><small>沿用人物、场景参考，保留未要求修改的部分。</small></p></div>
 <label>想修改哪里？<textarea name="editNote" rows="3" maxlength="2000" placeholder="例如：把拿桶的手改自然些，保留人物、服装和仓库构图。留空则按原要求再生成一版。">${esc(draft.editNote??(r.review==='changes_requested'?r.reviewNote:'')??'')}</textarea></label>
 <details class="version-options"><summary>模型与生成数量 · ${esc(chosen.name)}</summary>${imageModelPicker({draft,catalog,contracts,loading,error,ratio:r.settings?.ratio})}<label>同时生成<select name="groups">${[1,2,3,4,6,8].map(n=>`<option value="${n}" ${Number(draft.groups||1)===n?'selected':''}>${n} 组</option>`).join('')}</select></label></details>
 ${error?`<p class="wf-note" role="status">${esc(error)}</p>`:''}
 <div class="wf-actions"><button type="submit" class="primary" ${!canPrepare?'disabled':''}>带原图重抽</button><button type="button" data-version-cancel>取消</button></div><small class="wf-muted">下一步核对费用。新图生成后由你选择，当前选用版本保持不变。</small>
 </form>`:''}
 <details class="version-history"><summary>版本信息与修改记录</summary><p class="wf-muted">${esc(r.id.slice(-6))} · ${esc(r.ownership.accountLabelAtCreation||'原账号')} · ${esc(r.ownership.spaceNameAtCreation||'原空间')}</p>${(r.reviewHistory||[]).map(h=>`<p>${esc(new Date(h.at).toLocaleString())} · ${esc(h.note)}</p>`).join('')||'<p>暂无选用记录</p>'}${r.prompt?`<details><summary>本版生成要求</summary><pre class="wf-prompt-text">${esc(r.prompt.replace(/\{\{reference:[^}]+\}\}/g,'（已绑定参考图片）'))}</pre></details>`:''}</details>
 </section>`;
}
