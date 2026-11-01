import {escapeHTML as esc,assetURL,belongsToSelection,categories} from './model.js';
import {generationInspector} from './production-generation.js';

export function styleSummary(project,apiBase){
 const d=project?.artDirection;
 return d?`<section class="creator-style-summary"><img src="${esc(assetURL(apiBase,d.assetId,d.revisionId,true))}" alt="本剧已选风格"><div><b>${d.valid===false?'风格依据待重新确认':'本剧风格已确认'} · 第 ${d.version} 版</b><details><summary>查看美术规范</summary><p>${esc(d.notes)}</p></details></div><button data-wf-nav="style">查看 / 更换风格</button></section>`:'<div class="wf-note">先选定本剧风格，再制作统一的资产。<button data-wf-nav="style">去选风格</button></div>';
}
export function directionForm({project,result,assets,apiBase,directionDraft,busy}){
 const id=directionDraft?.revisionId;if(!id)return '';
 const r=assets.flatMap(a=>a.revisions).find(r=>r.id===id);if(!r)return '';
 return `<section class="wf-panel creator-direction"><h3>确认本剧统一风格</h3><form data-wf-form="art-direction"><img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="待确认的本剧风格"><input type="hidden" name="revisionId" value="${esc(r.id)}"><label>本剧美术规范<textarea name="notes" rows="4" maxlength="4000" required>${esc(directionDraft.notes??project.artDirection?.notes??result.styleBible)}</textarea></label><p class="wf-muted">后续制作自动沿用这份规范。换风格后，按旧规范制作的图片需要重新核对。</p><button class="primary" ${busy?'disabled':''}>选用此张并确认本剧风格</button><button type="button" data-creator-direction-cancel>取消</button></form></section>`;
}
export function creatorDesk(options){
 const {result,job,assets,selection,view,page,project,apiBase,busy}=options;
 const index=Math.min(view.index||0,result.assets.length-1),chosen=result.assets[index];
 const rows=result.assets.map((a,i)=>{
  const ids=job.bindings?.filter(b=>b.assetId===a.id).map(b=>b.entityId)||[];
  const revisions=assets.filter(e=>ids.includes(e.entityId)).flatMap(e=>e.revisions).filter(r=>belongsToSelection(r,job.ownership||selection));
  const relevant=revisions.filter(r=>r.status==='ready'&&r.stage===(page==='style'?'style':'asset'));
  const cover=[...relevant].reverse().find(r=>r.review==='approved'&&r.status==='ready')||relevant.at(-1)||[...revisions].reverse().find(r=>r.stage==='style'&&r.status==='ready'&&r.review==='approved');
  return `<button data-creator-select="${i}" aria-pressed="${index===i}">${cover?`<img src="${esc(assetURL(apiBase,cover.assetId,cover.id,true))}" alt="">`:'<span class="creator-monogram">'+esc(categories[a.category])+'</span>'}<span><b>${esc(a.name)}</b><small>${page==='style'?'基础形象':a.category==='character'?'主多视图 + '+a.states.length+' 个剧情状态':a.states.length+' 个状态'} · ${relevant.filter(r=>r.review==='pending'&&r.status==='ready').length} 张待选</small></span></button>`;
 }).join('');
 return `<section class="wf-panel creator-desk" data-creator-desk><header class="wf-section-title"><div><p class="wf-eyebrow">${page==='style'?'02 / 风格探索':'03 / 资产制作'}</p><h3>${page==='style'?'确认风格与基础形象':'先做主多视图，再派生剧情状态'}</h3></div><button data-wf-nav="${page==='style'?'asset':'production'}">${page==='style'?'制作规范资产 →':'进入导演台 →'}</button></header>${page==='style'?(project.artDirection?styleSummary(project,apiBase):'<p class="wf-muted">MJ 抽人物、场景和道具候选，由你选定本剧的美术方向。</p>'):styleSummary(project,apiBase)}${job.validationIssues?.length?`<div class="wf-note wf-error">制作方案有 ${job.validationIssues.length} 处原文或引用待核对。<button data-wf-action="production-open-review">查看并手动修改</button></div>`:''}${directionForm(options)}<div class="creator-desk-grid"><aside class="creator-catalog" aria-label="本剧物料"><label class="sr-only" for="creator-filter">搜索物料</label><input id="creator-filter" data-creator-filter placeholder="搜索人物、场景、道具"><div data-creator-catalog>${rows}</div></aside><main class="creator-main"><h3>${esc(chosen?.name||'选择物料')}</h3>${chosen?generationInspector({...options,view:{...view,index,kind:'assets'},phase:page}):''}</main></div></section>`;
}
