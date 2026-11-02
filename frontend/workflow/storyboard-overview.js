import {escapeHTML as esc,assetURL,belongsToSelection} from './model.js';
import {compactTasks} from './in-place.js';
import {returnedResult} from './production-editor.js';
import {readableText} from './production-references.js';
import {dialogueText,referenceCards} from './production.js';
import {MASTER_STATE_ID,SCENE_MASTER_STATE_ID} from './production-generation.js';

const paragraph=value=>esc(value||'').replaceAll('\n','<br>');
const number=i=>String(i+1).padStart(3,'0');
const latest=rows=>[...rows].sort((a,b)=>(b.createdAt||'').localeCompare(a.createdAt||''))[0];
const taskLabels={draft:'待确认生成',prepared:'待确认生成',preparing:'正在准备',submitting:'正在提交',submitted:'正在生成',queued:'正在排队',running:'正在生成',downloading:'正在收取',needs_attention:'原任务待查询',blocked_authorization:'原任务需恢复授权',failed:'生成中断'};
const labels={approved:'已保留',pending:'待审核',changes_requested:'需返修',missing:'待生成',stale:'需更新图片'};
const imageButton=(r,name,apiBase)=>`<button class="overview-image" data-image-tools="${esc(r.id)}" aria-label="调整 ${esc(name)} 图片"><img src="${esc(assetURL(apiBase,r.assetId,r.id,true))}" alt="${esc(name)}" loading="lazy"></button>`;

export function overviewShots({job,assets=[],coverage={},selection,tasks=[]}) {
  const result=returnedResult(job);if(!result)return [];
  const allowed=new Set(coverage.exportRevisionIds||[]),owner=job.ownership||selection;
  return result.shots.map((shot,index)=>{
    const binding=(job.shotBindings||[]).find(b=>b.shotId===shot.id);
    const scope=(coverage.entities||[]).find(e=>e.shotId===shot.id);
    const library=assets.find(a=>a.active&&a.entityId===binding?.entityId);
    const rows=(library?.revisions||[]).filter(r=>r.stage==='storyboard'&&r.status==='ready'&&belongsToSelection(r,owner));
    const approved=latest(rows.filter(r=>r.review==='approved'&&allowed.has(r.id)));
    const current=job.status==='ready'&&!job.stale&&scope?.designCurrent===true;
    const revision=current?(approved||latest(rows.filter(r=>r.review!=='approved'))||null):null;
    const task=latest(tasks.filter(t=>t.entityId===binding?.entityId&&belongsToSelection(t,owner)));
    const historyRevision=latest((library?.revisions||[]).filter(r=>r.stage==='storyboard'&&belongsToSelection(r,owner)));
    const status=revision?.review||(library?.revisions?.length?'stale':'missing');
    return {shot,index,revision,status,task,pendingCount:rows.filter(r=>r.review==='pending').length,historyRevision,historyRevisionId:historyRevision?.id,ready:Boolean(current&&approved)};
  });
}

export function storyboardOverview({job,assets=[],coverage={},selection,analysis,apiBase='/api/v1',tasks=[],filter='all',scene='',unsaved=false}) {
  const result=returnedResult(job);if(!result)return '';
  const owner=job.ownership||selection,rows=overviewShots({job,assets,coverage,selection,tasks});
  const scenes=analysis?.result?.scenes||analysis?.draftResult?.scenes||[];
  const sceneIds=[...new Set(result.shots.map(s=>s.sceneId))];
  const sceneName=id=>`场次 ${sceneIds.indexOf(id)+1}${scenes.find(s=>s.id===id)?.title?' · '+scenes.find(s=>s.id===id).title:''}`;
  const assetCards=category=>overviewAssetCards({job,assets,selection,apiBase},category);
  const shotCard=row=>overviewShotCard(row,{job,assets,selection,apiBase});
  const visible=rows.filter(r=>(filter!=='attention'||!r.ready)&&(!scene||r.shot.sceneId===scene));
  const groups=[];for(const row of visible){let group=groups.at(-1);if(!group||group.id!==row.shot.sceneId){group={id:row.shot.sceneId,rows:[]};groups.push(group);}group.rows.push(row);}
  return `<section class="storyboard-overview" aria-label="分镜总览"><header class="wf-panel overview-heading"><div><p class="wf-eyebrow">05 / 审核交付</p><h3>分镜总览</h3><p>${rows.length} 个镜头 · ${rows.filter(r=>r.ready).length} 张已保留 · ${rows.filter(r=>!r.ready).length} 镜待处理</p></div><div class="wf-actions"><button data-wf-nav="production">返回导演编排</button>${unsaved||job.stale?'<span class="wf-note">这里展示已保存方案；导演台的未保存修改请先核对。</span>':`<a class="wf-link" target="_blank" rel="noopener" href="${esc(apiBase)}/production-jobs/${encodeURIComponent(job.id)}/storyboard-preview">打开图文脚本</a><a class="wf-link" data-wf-download href="${esc(apiBase)}/production-jobs/${encodeURIComponent(job.id)}/storyboard-export">下载图文分镜脚本</a>`}</div></header><details class="wf-panel overview-assets" open><summary>角色与场景多视图</summary><h4>角色 · 主多视图与剧情状态</h4><div class="overview-asset-grid">${assetCards('character')||'<p>本剧没有角色资产</p>'}</div><h4>场景 · 多视图</h4><div class="overview-asset-grid">${assetCards('scene')||'<p>本剧没有场景资产</p>'}</div><details><summary>关键道具</summary><div class="overview-asset-grid">${assetCards('prop')}</div></details></details><div class="wf-panel overview-toolbar"><div class="wf-actions"><button data-overview-filter="all" aria-pressed="${filter==='all'}">全部镜头</button><button data-overview-filter="attention" aria-pressed="${filter==='attention'}">只看待处理</button><label>场次<select data-overview-scene aria-label="筛选总览场次"><option value="">全部场次</option>${sceneIds.map(id=>`<option value="${esc(id)}" ${id===scene?'selected':''}>${esc(sceneName(id))}</option>`).join('')}</select></label></div><p class="wf-muted">按剧情顺序核对画面、动作和台词；点图放大，展开首尾状态检查衔接。</p></div>${groups.map(g=>`<section class="overview-scene" aria-label="${esc(sceneName(g.id))}"><h3>${esc(sceneName(g.id))}</h3><div class="overview-shot-grid">${g.rows.map(shotCard).join('')}</div></section>`).join('')||'<p class="wf-panel">当前筛选下没有待处理镜头。</p>'}</section>`;
}

export function overviewAssetCards({job,assets=[],selection,apiBase='/api/v1'},category,{canvas=false}={}) {
    const result=returnedResult(job);if(!result)return '';
    const owner=job.ownership||selection;
    return result.assets.flatMap((asset,index)=>{
      if(asset.category!==category)return [];
      const states=category==='character'?[{id:MASTER_STATE_ID,name:'人物主多视图'},...asset.states]:category==='scene'?[{id:SCENE_MASTER_STATE_ID,name:'场景主多视图'},...asset.states]:asset.states;
      return states.map((state,si)=>{
        const binding=(job.bindings||[]).find(b=>b.assetId===asset.id&&b.stateId===state.id);
        const library=assets.find(a=>a.active&&a.entityId===binding?.entityId);
        const candidates=job.status==='ready'&&!job.stale&&binding?.saved&&!binding.changed?(library?.revisions||[]).filter(r=>['asset','refine'].includes(r.stage)&&r.status==='ready'&&belongsToSelection(r,owner)):[];
        const r=latest(candidates.filter(r=>r.review==='approved'))||latest(candidates);
        const history=latest((library?.revisions||[]).filter(r=>['asset','refine'].includes(r.stage)&&belongsToSelection(r,owner)));
        const stateIndex=['character','scene'].includes(category)?Math.max(0,si-1):si;
        return `<article class="overview-asset-card" ${canvas?`data-story-node="asset:${esc(asset.id)}:${esc(state.id)}" data-story-category="${esc(category)}"`: ''}>${canvas?`<button type="button" class="story-drag" data-story-drag aria-label="移动 ${esc(asset.name)} ${esc(state.name)}">⠿</button>`:''}<h5>${esc(asset.name)}</h5><p>${esc(state.name)}</p>${r?imageButton(r,`${asset.name} · ${state.name}`,apiBase):history?`<div class="quick-history-image">${imageButton(history,`${asset.name} · ${state.name} · 历史原图`,apiBase)}<span>原图保留 · 制作依据待核对</span></div>`:'<div class="overview-empty">多视图待制作</div>'}<div class="wf-actions"><span class="wf-tag ${esc(r?.review||'pending')}">${labels[r?.review]||(history?'待核对':'待制作')}</span><button data-overview-asset="${index}" data-overview-state="${stateIndex}" data-overview-master="${[MASTER_STATE_ID,SCENE_MASTER_STATE_ID].includes(state.id)}">查看资产</button></div></article>`;
      });
    }).join('');
  }

export function overviewShotCard(row,{job,assets=[],selection,apiBase='/api/v1'},{canvas=false}={}) {
    const result=returnedResult(job);
    const {shot,index,revision,status,ready,task,historyRevisionId,historyRevision}=row;
    const taskLabel=taskLabels[task?.status];
    const lines=dialogueText(job,shot),previous=result.shots[index-1];
    const validRefs=referenceCards(job,shot,assets,selection,apiBase);
    const refs=shot.references.map((ref,ri)=>{
      const asset=result.assets.find(a=>a.id===ref.assetId),state=asset?.states.find(s=>s.id===ref.stateId);
      const r=validRefs[ri]?.pinned&&validRefs[ri]?.src?{id:validRefs[ri].revisionId}:null;
      const name=`${asset?.name||'未找到物料'} · ${state?.name||'未选状态'}`;
      return r?`<button data-wf-review="${esc(r.id)}" aria-label="查看本镜参考 ${esc(name)}">${esc(name)}</button>`:`<span class="wf-tag">${esc(name)} · 参考待补</span>`;
    }).join('');
    return `<article class="overview-shot" ${canvas?`data-story-node="shot:${esc(shot.id)}" data-story-scene-id="${esc(shot.sceneId)}" data-story-ready="${ready}"`: ''} id="overview-shot-${number(index)}" aria-label="分镜 ${number(index)} ${esc(shot.purpose)}">${canvas?`<button type="button" class="story-drag" data-story-drag aria-label="移动镜头 ${number(index)}">⠿</button>`:''}<header><label class="quick-select-shot"><input type="checkbox" data-quick-shot-select="${esc(shot.id)}" aria-label="选择镜头 ${number(index)}"><strong>镜头 ${number(index)}</strong></label><span>${esc(shot.durationSeconds)} 秒</span><span class="wf-tag ${ready?'approved':esc(status)}">${taskLabel||labels[status]||'待审核'}</span></header>${revision?imageButton(revision,`分镜 ${number(index)}`,apiBase):historyRevision?`<div class="quick-history-image">${imageButton(historyRevision,`历史分镜 ${number(index)} · 待核对`,apiBase)}<span>原图保留 · 制作依据待核对</span></div>`:`<div class="overview-empty overview-shot-empty">${taskLabel|| (status==='stale'?'镜头或参考已变化，旧图不作为当前画面':'画面待补 · 分镜与台词已保留')}</div>`}${task?compactTasks([task]):''}${row.pendingCount?`<span class="wf-tag">${row.pendingCount} 张新候选待选</span>`:''}<div class="overview-shot-copy"><button class="quick-copy-button" data-quick-edit="${index}" data-quick-field="purpose"><h4>${esc(shot.purpose)}</h4></button><button class="quick-copy-button" data-quick-edit="${index}" data-quick-field="beat" aria-label="编辑镜头 ${number(index)} 画面与动作"><p class="overview-description">${paragraph(readableText(shot.beat,result,shot))}</p></button><div class="overview-dialogue"><h5>角色台词</h5>${lines.map(d=>`<blockquote><b>${esc(d.label)}</b><button class="quick-copy-button" data-quick-edit="${index}" data-quick-field="dialogue"><p>${paragraph(d.text)}</p></button>${d.added?'<small>人工新增</small>':d.edited?'<small>人工改写 · 原句保留</small>':''}</blockquote>`).join('')||'<p class="wf-muted">本镜无台词</p>'}</div><details><summary>首尾状态与连续性</summary><button class="quick-copy-button" data-quick-edit="${index}" data-quick-field="framing"><b>画面构图</b><p>${paragraph(shot.framing)}</p></button>${previous?`<p><b>上一镜结束</b><br>${paragraph(previous.endState)}</p>`:''}<p><b>本镜开始</b><br>${paragraph(shot.startState)}</p><p><b>本镜结束</b><br>${paragraph(shot.endState)}</p>${(shot.continuity||[]).map(c=>`<p>${paragraph(c)}</p>`).join('')}<p><b>人物表演</b><br>${paragraph(shot.performance)}</p><p><b>摄影机 / 声音</b><br>${paragraph(shot.camera)}<br>${paragraph(shot.sound)}</p></details><details><summary>本镜角色、场景与道具</summary><div class="overview-references">${refs}</div></details><div class="wf-actions"><button data-overview-shot="${index}">修改此镜</button>${revision||historyRevisionId?`<button data-wf-review="${esc(revision?.id||historyRevisionId)}">${revision?'挑选版本 / 重抽':'历史版本 / 重抽'}</button>`:''}${!revision?`<button data-overview-shot="${index}" data-overview-generate>${taskLabel?'查看生成任务':'生成分镜图'}</button>`:''}</div></div></article>`;
  }
