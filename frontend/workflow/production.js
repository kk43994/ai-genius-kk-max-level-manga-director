import {escapeHTML as esc, assetURL, categories, belongsToSelection} from './model.js';
import {elapsedLabel} from './progress.js';

export const productionRunning = job => ['preparing','submitting','running','reviewing'].includes(job?.status);
const list = items => items?.length ? `<ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>` : '<p class="wf-muted">暂无补充</p>';
const evidence = items => items.map(e=>`<button class="wf-evidence" data-wf-source="${e.startLine}" data-wf-source-end="${e.endLine}">L${e.startLine}–${e.endLine} · ${esc(e.quote)}</button>`).join('');
const dialogueKinds = {dialogue:'对白',inner_monologue:'内心独白',narration:'旁白',voiceover:'画外音',offscreen:'画外对白',system_voice:'系统音',unknown:'待确认'};
export function dialogueText(job, shot) {
  const names=new Map((job.characters||[]).map(c=>[c.id,c.name]));
  return shot.dialogueIds.map(id=>{
    const d=job.dialogues.find(d=>d.id===id);
    return d?{...d,label:`${names.get(d.speakerId)||d.speakerLabel||'未署名'} · ${dialogueKinds[d.kind]||d.kind}`} : null;
  }).filter(Boolean);
}
export function referenceCards(job,shot,assets,selection,apiBase) {
  return shot.references.map(ref=>{
    const item=job.result.assets.find(a=>a.id===ref.assetId), state=item?.states.find(s=>s.id===ref.stateId);
    const binding=job.bindings.find(b=>b.assetId===ref.assetId&&b.stateId===ref.stateId);
    const asset=binding&&assets.find(a=>a.entityId===binding.entityId&&a.active);
    // Preview never substitutes pending/rejected/stale or another owner's image.
    const candidates=!job.stale&&!binding?.changed?(asset?.revisions||[]).filter(r=>r.status==='ready'&&r.review==='approved'&&belongsToSelection(r,selection)):[];
    const revision=[...candidates].sort((a,b)=>({refine:3,asset:2,style:1}[b.stage]-{refine:3,asset:2,style:1}[a.stage])||b.createdAt.localeCompare(a.createdAt))[0];
    return {name:`${item?.name||ref.assetId} · ${state?.name||ref.stateId}`,category:item?.category,entityId:binding?.entityId,
      saved:binding?.saved,changed:binding?.changed,src:revision?assetURL(apiBase,asset.id,revision.id,true):null};
  });
}
function cardsHtml(cards, controls=false) {
  return `<div class="wf-production-references">${cards.map(r=>`<figure>${r.src?`<img src="${esc(r.src)}" alt="${esc(r.name)} 已审核资产参考" loading="lazy">`:'<div class="wf-production-placeholder">'+(r.changed?'设定已调整':r.saved?'等待图片审核':'物料待建立')+'</div>'}<figcaption>${esc(r.name)}</figcaption>${controls&&r.saved?`<button data-wf-entity="${esc(r.entityId)}" data-wf-stage="style">查看 / 制作物料</button>`:''}</figure>`).join('')}</div>`;
}
export function timelineAt(shots,elapsed) {
  let start=0;
  for(let i=0;i<shots.length;i++){const end=start+shots[i].durationSeconds;if(elapsed<end)return {index:i,start,end};start=end;}
  return {index:Math.max(0,shots.length-1),start:Math.max(0,start-(shots.at(-1)?.durationSeconds||0)),end:start};
}
export function previewFrame(job,index,{assets=[],selection,apiBase='/api/v1'}={}) {
  const shot=job.result.shots[index];if(!shot)return '';
  const lines=dialogueText(job,shot);
  const cards=referenceCards(job,shot,assets,selection,apiBase);
  return `<div class="wf-production-screen" data-ratio="${esc(job.result.aspectRatio)}"><p class="wf-eyebrow">镜头 ${String(index+1).padStart(3,'0')} · ${esc(shot.framing)}</p><h4>${esc(shot.purpose)}</h4>${cardsHtml(cards)}<p class="wf-production-action">${esc(shot.beat)}</p><p>${esc(shot.performance)}</p>${lines.map(d=>`<p class="wf-production-dialogue"><small>${esc(d.label)}</small><br>${esc(d.text)}</p>`).join('')}<p class="wf-muted">${cards.some(c=>c.src)?'已审核资产示意 · 尚非最终分镜画面':'文字图板预演 · 分镜图片尚未生成'}</p></div><p class="wf-muted">镜头：${esc(shot.camera)}<br>声音设计：${esc(shot.sound)}</p>`;
}
export function productionPanel({script,analysis,job,enabled,connected,busy,error='',models=[],modelId,assets=[],selection,apiBase,draft=null}) {
  if(!script)return '<section class="wf-panel"><h3>先导入剧本</h3><button data-wf-nav="plan">返回剧本</button></section>';
  const ready=job?.status==='ready',running=productionRunning(job),canStart=!job||ready||job.canRetry;
  let html=`<section class="wf-panel wf-production" data-wf-production aria-label="漫剧制作方案"><div class="wf-section-title"><div><p class="wf-eyebrow">PRODUCTION / 从故事到镜头</p><h3>物料、状态与分镜</h3></div><span class="wf-tag">${esc(job?.model||models.find(m=>m.id===modelId)?.name||'AI 制作设计')}</span></div><p class="wf-muted">复用已完成的剧本分析，AI 设计角色与场景状态、关键道具、人物表演和逐镜画面。原文台词独立关联，创作建议需要核对。</p>${error?`<p class="wf-note wf-error">${esc(error)}</p>`:''}${job?`<div role="status" aria-live="polite"><b>${esc(job.message)}</b><p class="wf-muted">编号 ${String(job.displayNumber||0).padStart(3,'0')} · ${job.completedCalls} / ${job.totalCalls||1} 次 AI 调用${job.phaseStartedAt&&running?' · '+esc(elapsedLabel(Date.parse(job.phaseStartedAt))):''}</p>${running?'<progress aria-label="AI 正在制作方案，尚无精确百分比"></progress>':''}</div>`:''}${job?.stale?'<p class="wf-note wf-error">原文或统一风格已变更。此方案保留供对照，请重新设计后再建立物料。</p>':''}${job?.canRefresh?'<button data-wf-action="production-refresh">继续查询原制作任务</button><p class="wf-muted">每 5 秒查询一次原回执，不会重复提交。</p>':''}${job?.canRetrySubmission?'<button data-wf-action="production-retry">使用新编号继续（上次未提交）</button>':''}`;
  if(job?.canRevalidate)html+='<button data-wf-action="production-revalidate">重新核验原返回结果</button><p class="wf-muted">更新后的程序可重新核验原回执，不会新增 AI 调用。若内容仍不完整，会保留具体问题。</p>';
  if(job?.canRepairProduction)html+='<div class="wf-note"><label><input type="checkbox" data-wf-production-repair-spend> 允许 AI 修正原结果（额外 1 次文本调用）</label><button data-wf-action="production-repair">修正引用与物料关联</button><p class="wf-muted">保留原文和已有方案，让 AI 修正核验问题；本轮最多修正一次，不自动重试。</p></div>';
  if(canStart)html+=`<details ${job?'':'open'}><summary>${job?'重新设计（新任务）':'开始 AI 制作设计'}</summary>${analysis?.status!=='ready'?'<p class="wf-note">需要先完成当前剧本的 AI 分析。</p><button data-wf-nav="plan">去分析剧本</button>':''}<div class="wf-form-grid"><label>制作分析模型<select data-wf-analysis-model ${busy?'disabled':''}>${models.map(m=>`<option value="${esc(m.id)}" ${m.id===modelId?'selected':''}>${esc(m.name)} · LibTV</option>`).join('')}</select></label><label>影片画幅<select data-wf-production-ratio>${['9:16','16:9','1:1'].map(r=>`<option ${r===(job?.aspectRatio||'9:16')?'selected':''}>${r}</option>`).join('')}</select></label></div><label class="wf-analysis-check"><input type="checkbox" data-wf-production-spend> 允许本次制作设计使用已连接账号积分（1 次 AI 文本调用）</label><button class="primary" data-wf-action="production-start" ${busy||!enabled||!connected||analysis?.status!=='ready'?'disabled':''}>${job?'重新设计':'生成制作方案'} →</button>${!connected?'<button data-wf-action="connect">连接 / 检查 LibTV</button>':''}<p class="wf-muted">本步骤设计方案，不生成图片或视频。金额以 LibTV 官方扣费为准。</p></details>`;
  if(!ready)return html+'</section>';
  const result=job.result,total=result.shots.reduce((sum,s)=>sum+s.durationSeconds,0),states=result.assets.reduce((sum,a)=>sum+a.states.length,0);
  html+=`<div class="wf-analysis-counts"><span><b>${result.assets.length}</b> 项基础物料</span><span><b>${states}</b> 个物料状态</span><span><b>${result.shots.length}</b> 个镜头</span><span><b>${Math.round(total)}</b> 秒预演建议</span></div><details open><summary>美术设定与待确认项</summary><p>${esc(result.styleBible)}</p><p class="wf-muted">以下是 AI 创作建议，尚未作为全局风格保存。</p>${list(result.uncertainties)}</details><div class="wf-actions"><button data-wf-action="production-preview-open">播放分镜预演</button><button data-wf-action="production-shots-open">查看 / 调整镜头</button></div><details><summary>物料与状态清单 · ${states}</summary><div class="wf-grid">${result.assets.map(asset=>`<article class="wf-production-asset"><p class="wf-eyebrow">${categories[asset.category]}</p><h4>${esc(asset.name)}</h4><p>${esc(asset.design)}</p><details><summary>创作建议（原文未限定）</summary>${list(asset.creativeChoices)}</details>${asset.states.map(state=>`<details><summary>${esc(state.name)}</summary><p>${esc(state.description)}</p><p class="wf-muted">${esc(state.imagePrompt)}</p></details>`).join('')}<details><summary>原文依据</summary>${evidence(asset.evidence)}</details></article>`).join('')}</div><label class="wf-analysis-check"><input type="checkbox" data-wf-production-reviewed> 我已核对物料、状态和创作建议，加入清单后继续逐项确认</label><button class="primary" data-wf-action="production-plan" ${busy||job.stale?'disabled':''}>加入资产清单草稿 →</button><p class="wf-muted">保留原有条目，仅新增本方案物料；确认保存前可编辑。已有同编号物料不会被覆盖。</p></details><details><summary>场次空间与连续性</summary>${result.scenePlans.map(s=>`<article class="wf-production-asset"><h4>${esc(scenesTitle(job,s.sceneId))}</h4><p><b>空间布局：</b>${esc(s.spatialLayout)}</p><p><b>光线：</b>${esc(s.lighting)}</p><p><b>情绪变化：</b>${esc(s.emotionalArc)}</p>${list(s.continuity)}</article>`).join('')}</details>`;
  html+=`<details data-wf-production-preview><summary>分镜图板预演 · ${Math.round(total)} 秒</summary><p class="wf-note">按建议时长播放镜头说明和原文台词；物料审核后可显示参考缩略图。当前不是生成的视频，系统试读也不是正式角色配音。</p><div data-wf-preview-frame>${previewFrame(job,0,{assets,selection,apiBase})}</div><progress data-wf-preview-progress value="0" max="${total}" aria-label="分镜预演播放进度"></progress><p data-wf-preview-time class="wf-muted">0 / ${Math.round(total)} 秒</p><div class="wf-actions"><button data-wf-action="production-play">播放</button><button data-wf-action="production-pause">暂停</button><button data-wf-action="production-prev">上一镜</button><button data-wf-action="production-next">下一镜</button><button data-wf-action="production-rewind">从头播放</button></div><label><input type="checkbox" data-wf-preview-voice> 使用浏览器系统试读原文台词（非最终配音，仍需校准时长）</label></details>`;
  html+=`<details data-wf-production-shots><summary>逐镜设计与提示词 · ${result.shots.length}</summary><p class="wf-muted">资产图、分镜静帧和视频动作提示分开保存。这里的视频提示词是模型无关的导演草稿，正式提交前仍需匹配模型和参考素材。</p>${draft?'<p class="wf-note">有本机未保存的分镜调整；预演使用上次保存版本。</p>':''}<div class="wf-actions"><button data-wf-action="production-save" ${busy||job.stale?'disabled':''}>保存分镜调整</button>${draft?'<button data-wf-action="production-discard">恢复已保存分镜</button>':''}</div>${result.shots.map((shot,index)=>{
    const value={...shot,...draft?.shots?.[shot.id]};
    return `<details class="wf-production-shot"><summary>${String(index+1).padStart(3,'0')} · ${esc(shot.purpose)} · ${value.durationSeconds} 秒</summary><p><b>动作：</b>${esc(shot.beat)}</p><p><b>画面：</b>${esc(shot.framing)} · ${esc(shot.camera)}</p>${cardsHtml(referenceCards(job,shot,assets,selection,apiBase),true)}<label>建议时长（秒）<input type="number" min="1" max="60" step="0.5" data-wf-production-edit="durationSeconds" data-shot-id="${esc(shot.id)}" value="${value.durationSeconds}"></label><label>人物表演<textarea rows="3" maxlength="1500" data-wf-production-edit="performance" data-shot-id="${esc(shot.id)}">${esc(value.performance)}</textarea></label><p><b>开始：</b>${esc(shot.startState)}</p><p><b>结束：</b>${esc(shot.endState)}</p>${dialogueText(job,shot).map(d=>`<blockquote><small>${esc(d.label)}</small><br>${esc(d.text)}</blockquote>`).join('')}<p><b>声音：</b>${esc(shot.sound)}</p><label>分镜静帧提示词<textarea rows="4" maxlength="3000" data-wf-production-edit="imagePrompt" data-shot-id="${esc(shot.id)}">${esc(value.imagePrompt)}</textarea></label><label>视频动作提示词<textarea rows="4" maxlength="3000" data-wf-production-edit="videoPrompt" data-shot-id="${esc(shot.id)}">${esc(value.videoPrompt)}</textarea></label><b>连续性检查</b>${list(shot.continuity)}<details><summary>原文依据</summary>${evidence(shot.evidence)}</details></details>`;
  }).join('')}</details>`;
  return html+'</section>';
}
function scenesTitle(job,id){return `场次 ${job.result.scenePlans.findIndex(s=>s.sceneId===id)+1}`;}

export function createPreview({root,getContext,onStatus=()=>{}}) {
  let timer=null,elapsed=0,index=-1,jobId=null,lastTick=0,spoken=-1;
  const win=root.ownerDocument.defaultView;
  function stop(){if(timer)clearInterval(timer);timer=null;win.speechSynthesis?.cancel();spoken=-1;}
  function sync(){const ctx=getContext(),job=ctx.job;if(!job?.result)return null;if(jobId!==job.id){stop();jobId=job.id;elapsed=0;index=-1;}return ctx;}
  function draw(){const ctx=sync();if(!ctx)return;const {job}=ctx,shots=job.result.shots,total=shots.reduce((sum,s)=>sum+s.durationSeconds,0),current=timelineAt(shots,elapsed);
    const target=root.querySelector('[data-wf-preview-frame]');if(!target||!root.querySelector('[data-wf-production-preview]')?.open){stop();return;}
    if(index!==current.index){index=current.index;target.innerHTML=previewFrame(job,index,ctx);}
    const progress=root.querySelector('[data-wf-preview-progress]');if(progress){progress.max=total;progress.value=Math.min(elapsed,total);}
    const label=root.querySelector('[data-wf-preview-time]');if(label)label.textContent=`${Math.floor(elapsed)} / ${Math.round(total)} 秒 · 镜头 ${index+1} / ${shots.length}`;
    if(timer&&spoken!==index&&root.querySelector('[data-wf-preview-voice]')?.checked){spoken=index;win.speechSynthesis?.cancel();const text=dialogueText(job,shots[index]).map(d=>d.text).join('。');if(text&&win.speechSynthesis&&win.SpeechSynthesisUtterance){const utterance=new win.SpeechSynthesisUtterance(text);utterance.lang='zh-CN';win.speechSynthesis.speak(utterance);}else if(text)onStatus('当前浏览器没有可用试读，继续播放文字图板。');}
    if(elapsed>=total){stop();onStatus('预演播放完成；请检查台词是否说完、动作是否连贯。');}
  }
  function play(){const ctx=sync();if(!ctx)return;stop();const total=ctx.job.result.shots.reduce((sum,s)=>sum+s.durationSeconds,0);if(elapsed>=total)elapsed=0;lastTick=Date.now();timer=setInterval(()=>{const now=Date.now();elapsed+=(now-lastTick)/1000;lastTick=now;draw();},200);draw();}
  function jump(delta){const ctx=sync();if(!ctx)return;stop();const target=Math.max(0,Math.min(ctx.job.result.shots.length-1,timelineAt(ctx.job.result.shots,elapsed).index+delta));elapsed=ctx.job.result.shots.slice(0,target).reduce((sum,s)=>sum+s.durationSeconds,0);index=-1;draw();}
  return {stop,play,jump,rewind(){stop();elapsed=0;index=-1;play();},reset(){stop();jobId=null;elapsed=0;index=-1;},refresh(){index=-1;draw();}};
}
