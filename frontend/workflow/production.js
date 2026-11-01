import {escapeHTML as esc, assetURL, categories, belongsToSelection} from './model.js';
import {elapsedLabel} from './progress.js';
import {returnedResult, reviewDraft} from './production-editor.js';
import {productionBoard} from './production-board.js';
import {linkedText} from './production-references.js';

export const productionRunning = job => ['preparing','submitting','running','reviewing'].includes(job?.status);
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
    const item=returnedResult(job).assets.find(a=>a.id===ref.assetId), state=item?.states.find(s=>s.id===ref.stateId);
    const binding=(job.bindings||[]).find(b=>b.assetId===ref.assetId&&b.stateId===ref.stateId);
    const asset=binding&&assets.find(a=>a.entityId===binding.entityId&&a.active);
    // Preview never substitutes pending/rejected/stale or another owner's image.
    const candidates=job.status==='ready'&&!job.stale&&!binding?.changed?(asset?.revisions||[]).filter(r=>['asset','refine'].includes(r.stage)&&r.status==='ready'&&r.review==='approved'&&belongsToSelection(r,job.ownership||selection)):[];
    const versions=[...candidates].sort((a,b)=>({refine:3,asset:2}[b.stage]-{refine:3,asset:2}[a.stage])||b.createdAt.localeCompare(a.createdAt));
    const revision=ref.revisionId?versions.find(r=>r.id===ref.revisionId):versions[0];
    return {name:`${item?.name||ref.assetId} · ${state?.name||ref.stateId}`,category:item?.category,entityId:binding?.entityId,
      saved:binding?.saved,changed:binding?.changed,revisionId:revision?.id,pinned:Boolean(ref.revisionId),versions,src:revision?assetURL(apiBase,asset.id,revision.id,true):null};
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
  const shot=returnedResult(job).shots[index];if(!shot)return '';
  const lines=dialogueText(job,shot);
  const cards=referenceCards(job,shot,assets,selection,apiBase);
  return `<div class="wf-production-screen" data-ratio="${esc(returnedResult(job).aspectRatio)}"><p class="wf-eyebrow">镜头 ${String(index+1).padStart(3,'0')} · ${esc(shot.framing)}</p><h4>${esc(shot.purpose)}</h4>${cardsHtml(cards)}<p class="wf-production-action">${linkedText(shot.beat,returnedResult(job),shot)}</p><p>${esc(shot.performance)}</p>${lines.map(d=>`<p class="wf-production-dialogue"><small>${esc(d.label)}</small><br>${esc(d.text)}</p>`).join('')}<p class="wf-muted">${cards.some(c=>c.src)?'已审核资产示意 · 尚非最终分镜画面':'文字图板预演 · 分镜图片尚未生成'}</p></div><p class="wf-muted">镜头：${esc(shot.camera)}<br>声音设计：${esc(shot.sound)}</p>`;
}
export function productionPanel({script,analysis,job,enabled,connected,busy,error='',models=[],modelId,assets=[],selection,apiBase,draft=null,review=null,view={},tasks=[],generationDraft={},phase,project}) {
  if(!script)return '<section class="wf-panel"><h3>先导入剧本</h3><button data-wf-nav="plan">返回剧本</button></section>';
  const ready=job?.status==='ready',running=productionRunning(job),canStart=!job||ready||job.canRetry;
  const result=review?.result||(draft&&returnedResult(job)?reviewDraft(job,draft).result:returnedResult(job));
  let html=`<section class="wf-panel wf-production" data-wf-production aria-label="漫剧制作方案"><div class="wf-section-title"><div><p class="wf-eyebrow">PRODUCTION / 从故事到镜头</p><h3>物料、状态与分镜</h3></div><span class="wf-tag">${esc(job?.model||models.find(m=>m.id===modelId)?.name||'AI 制作设计')}</span></div><p class="wf-muted">复用已完成的剧本分析，AI 设计角色与场景状态、关键道具、人物表演和逐镜画面。原文台词独立关联，创作建议需要核对。</p>${error?`<p class="wf-note wf-error">${esc(error)}</p>`:''}${job?`<div role="status" aria-live="polite"><b>${esc(job.message)}</b><p class="wf-muted">编号 ${String(job.displayNumber||0).padStart(3,'0')} · ${job.completedCalls} / ${job.totalCalls||1} 次 AI 调用${job.phaseStartedAt&&running?' · '+esc(elapsedLabel(Date.parse(job.phaseStartedAt))):''}</p>${running?'<progress aria-label="AI 正在制作方案，尚无精确百分比"></progress>':''}</div>`:''}${job?.stale?'<p class="wf-note wf-error">原文或统一风格已变更。此方案保留供对照，请重新设计后再建立物料。</p>':''}${job?.canRefresh?'<button data-wf-action="production-refresh">继续查询原制作任务</button><p class="wf-muted">每 5 秒查询一次原回执，不会重复提交。</p>':''}${job?.canRetrySubmission?'<button data-wf-action="production-retry">使用新编号继续（上次未提交）</button>':''}`;
  let startControls='';
  if(canStart)startControls+=`<details ${job?'':'open'}><summary>${job?'重新设计（新任务）':'开始 AI 制作设计'}</summary>${analysis?.status!=='ready'?'<p class="wf-note">需要先完成当前剧本的 AI 分析。</p><button data-wf-nav="plan">去分析剧本</button>':''}<div class="wf-form-grid"><label>制作分析模型<select data-wf-analysis-model ${busy?'disabled':''}>${models.map(m=>`<option value="${esc(m.id)}" ${m.id===modelId?'selected':''}>${esc(m.name)} · LibTV</option>`).join('')}</select></label><label>影片画幅<select data-wf-production-ratio>${['9:16','16:9','1:1'].map(r=>`<option ${r===(job?.aspectRatio||'9:16')?'selected':''}>${r}</option>`).join('')}</select></label></div><label class="wf-analysis-check"><input type="checkbox" data-wf-production-spend> 允许本次制作设计使用已连接账号积分（1 次 AI 文本调用）</label><button class="primary" data-wf-action="production-start" ${busy||!enabled||!connected||analysis?.status!=='ready'?'disabled':''}>${job?'重新设计':'生成制作方案'} →</button>${!connected?'<button data-wf-action="connect">连接 / 检查 LibTV</button>':''}<p class="wf-muted">本步骤设计方案，不生成图片或视频。金额以 LibTV 官方扣费为准。</p></details>`;
  if(!result){
    html+=startControls;
    if(job?.returnedText)html+=`<details open><summary>AI 已返回的内容</summary><p class="wf-note">返回内容尚未整理成完整表单，原文保留如下。</p><pre class="wf-production-raw">${esc(job.returnedText)}</pre></details>`;
    if(job?.canRevalidate)html+='<button data-wf-action="production-revalidate">重新读取原返回结果</button>';
    return html+'</section>';
  }
  return productionBoard({script,analysis,job,enabled,connected,busy,error,models,modelId,assets,selection,apiBase,draft,review,result,startControls,view,tasks,generationDraft,phase,project},{referenceCards,cardsHtml,dialogueText,previewFrame});
}

export function createPreview({root,getContext,onStatus=()=>{}}) {
  let timer=null,elapsed=0,index=-1,jobId=null,lastTick=0,spoken=-1;
  const win=root.ownerDocument.defaultView;
  function stop(){if(timer)clearInterval(timer);timer=null;win.speechSynthesis?.cancel();spoken=-1;}
  function sync(){const ctx=getContext(),job=ctx.job;if(!returnedResult(job))return null;if(jobId!==job.id){stop();jobId=job.id;elapsed=0;index=-1;}return ctx;}
  function draw(){const ctx=sync();if(!ctx)return;const {job}=ctx,shots=returnedResult(job).shots,total=shots.reduce((sum,s)=>sum+s.durationSeconds,0),current=timelineAt(shots,elapsed);
    const target=root.querySelector('[data-wf-preview-frame]');if(!target||!root.querySelector('[data-wf-production-preview]')){stop();return;}
    if(index!==current.index){index=current.index;target.innerHTML=previewFrame(job,index,ctx);}
    const progress=root.querySelector('[data-wf-preview-progress]');if(progress){progress.max=total;progress.value=Math.min(elapsed,total);}
    const label=root.querySelector('[data-wf-preview-time]');if(label)label.textContent=`${Math.floor(elapsed)} / ${Math.round(total)} 秒 · 镜头 ${index+1} / ${shots.length}`;
    if(timer&&spoken!==index&&root.querySelector('[data-wf-preview-voice]')?.checked){spoken=index;win.speechSynthesis?.cancel();const text=dialogueText(job,shots[index]).map(d=>d.text).join('。');if(text&&win.speechSynthesis&&win.SpeechSynthesisUtterance){const utterance=new win.SpeechSynthesisUtterance(text);utterance.lang='zh-CN';win.speechSynthesis.speak(utterance);}else if(text)onStatus('当前浏览器没有可用试读，继续播放文字图板。');}
    if(elapsed>=total){stop();onStatus('预演播放完成；请检查台词是否说完、动作是否连贯。');}
  }
  function play(){const ctx=sync();if(!ctx)return;stop();const total=returnedResult(ctx.job).shots.reduce((sum,s)=>sum+s.durationSeconds,0);if(elapsed>=total)elapsed=0;lastTick=Date.now();timer=setInterval(()=>{const now=Date.now();elapsed+=(now-lastTick)/1000;lastTick=now;draw();},200);draw();}
  function jump(delta){const ctx=sync();if(!ctx)return;stop();const target=Math.max(0,Math.min(returnedResult(ctx.job).shots.length-1,timelineAt(returnedResult(ctx.job).shots,elapsed).index+delta));elapsed=returnedResult(ctx.job).shots.slice(0,target).reduce((sum,s)=>sum+s.durationSeconds,0);index=-1;draw();}
  return {stop,play,jump,rewind(){stop();elapsed=0;index=-1;play();},reset(){stop();jobId=null;elapsed=0;index=-1;},refresh(){index=-1;draw();}};
}
