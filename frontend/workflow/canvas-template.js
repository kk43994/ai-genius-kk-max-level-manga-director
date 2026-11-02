import {escapeHTML as esc,assetURL} from './model.js';
import {returnedResult} from './production-editor.js';

// Program-owned slots. AI fills screenplay facts, never coordinates or markup.
export const PRODUCTION_TEMPLATE=Object.freeze({
 id:'manjiu-canvas-v1',
 steps:['全剧美术试做','主资产','剧情状态','分镜制作','连续性审查'],
 artSlots:[['character','人物风格','探索人物比例、绘制质感与服饰'],['scene','场景风格','探索空间、材质、色彩与光影'],['trial','人物入景试镜','试做人物与场景的融合效果']],
 shotFields:['场次','人物与道具','动作','原文台词','构图','首尾状态','固定参考','分镜图']
});
const paths={
 character:'<circle cx="48" cy="29" r="14"/><path d="M22 84V70c0-17 10-26 26-26s26 9 26 26v14"/>',
 scene:'<path d="M14 84V38l34-23 34 23v46H14Z"/><path d="M39 84V58h18v26M25 43h9v10h-9M62 43h9v10h-9"/>',
 prop:'<path d="m18 34 30-17 30 17v34L48 85 18 68V34Zm0 0 30 18 30-18M48 52v33M33 25l30 18"/>',
 trial:'<rect x="9" y="17" width="78" height="66" rx="8"/><circle cx="48" cy="37" r="10"/><path d="M30 76V64c0-14 36-14 36 0v12M18 60l12-12M71 48l8 10"/>'
};
export const placeholderIcon=category=>`<svg viewBox="0 0 96 100" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round">${paths[category]||paths.prop}</svg>`;

export function artFramework({project,apiBase='/api/v1'}={}){
 const d=project?.artDirection;
 return `<article class="pipeline-art" data-story-node="art:standard" aria-label="全剧美术试做"><button type="button" class="story-drag" data-story-drag aria-label="移动全剧美术试做">⠿</button><header><span class="pipeline-number">01</span><div><h4>全剧美术试做</h4><p>${d?.valid?'本剧美术标准已确认 · 第 '+d.version+' 版':'先试人物与场景，再确定整部剧的美术方向'}</p></div></header><div class="pipeline-art-slots">${PRODUCTION_TEMPLATE.artSlots.map(([role,title,note])=>{
  const r=d?.samples?.[role];
  return `<button type="button" class="pipeline-slot" data-canvas-art="${role}" aria-label="${title} · ${r?'查看已选样板':'开始试做'}">${r?`<img src="${esc(assetURL(apiBase,r.assetId,r.revisionId,true))}" alt="${title}样板">`:`<span class="pipeline-placeholder" data-placeholder="${role}">${placeholderIcon(role)}</span>`}<strong>${title}</strong><small>${r?'已选样板':note}</small></button>`;
 }).join('')}</div><footer>${d?.valid===false?'<span class="wf-error">全剧美术参考已改选或失效，请核对美术标准；原图与分镜仍保留。</span>':d&&!d.samples?'<span>已有单图标准继续沿用，可补充人物与场景样板</span>':'<span>选好样板 → 少量试做 → 确认全剧美术标准</span>'}<button type="button" class="primary" data-canvas-art="standard">${d?'查看美术标准':'开始美术试做'}</button></footer></article>`;
}

export function analysisMaterials(result){
 const facts=items=>(items||[]).map(f=>f.value).filter(Boolean).join('；');
 return [
  ...(result.characters||[]).map((r,index)=>({id:`character:${r.id}`,category:'character',name:r.name,description:[r.identity?.value,facts(r.appearance),facts(r.costume)].filter(Boolean).join('；'),path:`characters.${index}`})),
  ...(result.locations||[]).map((r,index)=>({id:`scene:${r.id}`,category:'scene',name:r.name,description:r.description?.value||'',path:`locations.${index}`})),
  ...(result.props||[]).map((r,index)=>({id:`prop:${r.id}`,category:'prop',name:r.name,description:r.description?.value||r.description||'',path:`props.${index}`}))
 ];
}

/** An honest placeholder is not a generated asset or a newly invented shot. */
export function initialMaterialCards(result,overview){
 if(returnedResult(overview?.job))return '';
 const labels={character:'人物主形象',scene:'场景主图',prop:'道具定型图'};
 const rows=analysisMaterials(result);
 if(!rows.some(r=>r.category==='prop'))rows.push({id:'prop:pending',category:'prop',name:'关键道具',description:'制作清单确定后补入具体道具',pending:true});
 return rows.map(r=>`<article class="pipeline-material" data-story-node="material:${esc(r.id)}" data-story-category="${r.category}" aria-label="${esc(r.name)} · ${labels[r.category]}"><button type="button" class="story-drag" data-story-drag aria-label="移动 ${esc(r.name)} 主资产卡">⠿</button><header><span>${labels[r.category]}</span><h4>${esc(r.name)}</h4></header><button type="button" class="pipeline-placeholder" data-canvas-material="${esc(r.id)}" aria-label="制作 ${esc(r.name)}">${placeholderIcon(r.category)}<span>${r.pending?'待整理道具':'图片待制作'}</span></button>${r.description?`<p class="pipeline-material-description">${esc(r.description)}</p>`:''}<footer><span>先确认全剧美术标准</span>${r.path?`<button type="button" data-wf-analysis-record="${esc(r.path)}">查看设定</button>`:''}</footer></article>`).join('');
}
