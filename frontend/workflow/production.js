import {escapeHTML as esc, assetURL, categories, belongsToSelection} from './model.js';
import {elapsedLabel} from './progress.js';
import {returnedResult, reviewDraft, field, quoteEditor, reviewIssues, reviewSaveBar} from './production-editor.js';

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
    const item=returnedResult(job).assets.find(a=>a.id===ref.assetId), state=item?.states.find(s=>s.id===ref.stateId);
    const binding=(job.bindings||[]).find(b=>b.assetId===ref.assetId&&b.stateId===ref.stateId);
    const asset=binding&&assets.find(a=>a.entityId===binding.entityId&&a.active);
    // Preview never substitutes pending/rejected/stale or another owner's image.
    const candidates=job.status==='ready'&&!job.stale&&!binding?.changed?(asset?.revisions||[]).filter(r=>r.status==='ready'&&r.review==='approved'&&belongsToSelection(r,selection)):[];
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
  const shot=returnedResult(job).shots[index];if(!shot)return '';
  const lines=dialogueText(job,shot);
  const cards=referenceCards(job,shot,assets,selection,apiBase);
  return `<div class="wf-production-screen" data-ratio="${esc(returnedResult(job).aspectRatio)}"><p class="wf-eyebrow">镜头 ${String(index+1).padStart(3,'0')} · ${esc(shot.framing)}</p><h4>${esc(shot.purpose)}</h4>${cardsHtml(cards)}<p class="wf-production-action">${esc(shot.beat)}</p><p>${esc(shot.performance)}</p>${lines.map(d=>`<p class="wf-production-dialogue"><small>${esc(d.label)}</small><br>${esc(d.text)}</p>`).join('')}<p class="wf-muted">${cards.some(c=>c.src)?'已审核资产示意 · 尚非最终分镜画面':'文字图板预演 · 分镜图片尚未生成'}</p></div><p class="wf-muted">镜头：${esc(shot.camera)}<br>声音设计：${esc(shot.sound)}</p>`;
}
export function productionPanel({script,analysis,job,enabled,connected,busy,error='',models=[],modelId,assets=[],selection,apiBase,draft=null,review=null}) {
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
  const total=result.shots.reduce((sum,s)=>sum+s.durationSeconds,0),states=result.assets.reduce((sum,a)=>sum+a.states.length,0);
  const changed=Boolean(review||draft),issues=job.validationIssues||[];
  html+=`<div class="wf-analysis-counts"><span><b>${result.assets.length}</b> 项基础物料</span><span><b>${states}</b> 个物料状态</span><span><b>${result.shots.length}</b> 个镜头</span><span><b>${Math.round(total)}</b> 秒预演建议</span></div>`;
  html+=reviewSaveBar(job,changed,busy);
  html+=`<div class="wf-actions wf-production-jumps"><button data-wf-action="production-assets-open">查看物料与状态</button><button data-wf-action="production-shots-open">查看分镜与提示词</button><button data-wf-action="production-preview-open">播放分镜预演</button>${issues.length?`<button data-wf-action="production-issues-open">核对 ${issues.length} 处问题</button>`:''}</div>`;
  html+=reviewIssues(job,result);
  html+=`<details><summary>美术设定与待确认项</summary>${field('美术设定（创作建议）','styleBible',result.styleBible,{max:4000,rows:5})}<p class="wf-muted">这里的修改随制作方案保存，不会自动覆盖全局风格。</p>${list(result.uncertainties)}</details>`;
  html+=`<details open data-wf-production-assets><summary>物料与状态清单 · ${result.assets.length} 项物料 / ${states} 个状态</summary><div class="wf-grid">${result.assets.map((asset,ai)=>`<article class="wf-production-asset"><p class="wf-eyebrow">${categories[asset.category]}${issues.some(i=>i.path.startsWith('assets.'+ai+'.'))?' · 引用待核对':''}</p><h4>${esc(asset.name)}</h4>${field('物料名称',`assets.${ai}.name`,asset.name,{max:100,rows:1})}${field('物料设计',`assets.${ai}.design`,asset.design,{max:1500})}<details><summary>创作建议（原文未限定）</summary>${list(asset.creativeChoices)}</details>${asset.states.map((state,si)=>`<details ${si===0?'open':''}><summary>${esc(state.name)}</summary>${field('状态名称',`assets.${ai}.states.${si}.name`,state.name,{max:100,rows:1})}${field('状态描述',`assets.${ai}.states.${si}.description`,state.description,{max:1500})}${field('资产图提示词',`assets.${ai}.states.${si}.imagePrompt`,state.imagePrompt,{max:2500,rows:5})}<fieldset><legend>适用场次</legend>${result.scenePlans.map((scene,sc)=>`<label class="wf-analysis-check"><input type="checkbox" data-wf-production-field="assets.${ai}.states.${si}.sceneIds" value="${esc(scene.sceneId)}" ${state.sceneIds?.includes(scene.sceneId)?'checked':''}> 场次 ${sc+1}</label>`).join('')}</fieldset></details>`).join('')}<details><summary>查看 / 修改原文依据</summary>${quoteEditor(asset.evidence,`assets.${ai}.evidence`)}</details></article>`).join('')}</div></details>`;
  html+=`<details><summary>场次空间与连续性</summary>${result.scenePlans.map((s,i)=>`<article class="wf-production-asset"><h4>场次 ${i+1}</h4>${field('空间布局',`scenePlans.${i}.spatialLayout`,s.spatialLayout)}${field('光线',`scenePlans.${i}.lighting`,s.lighting)}${field('情绪变化',`scenePlans.${i}.emotionalArc`,s.emotionalArc)}${list(s.continuity)}</article>`).join('')}</details>`;
  html+=`<details data-wf-production-preview><summary>分镜图板预演 · ${Math.round(total)} 秒</summary><p class="wf-note">使用上次保存的方案，按建议时长播放镜头说明和原文台词；物料审核后可显示参考缩略图。当前不是生成的视频，系统试读也不是正式角色配音。${!ready?'此方案还有待核对内容，仅供草稿预览。':''}</p><div data-wf-preview-frame>${previewFrame(job,0,{assets,selection,apiBase})}</div><progress data-wf-preview-progress value="0" max="${total}" aria-label="分镜预演播放进度"></progress><p data-wf-preview-time class="wf-muted">0 / ${Math.round(total)} 秒</p><div class="wf-actions"><button data-wf-action="production-play">播放</button><button data-wf-action="production-pause">暂停</button><button data-wf-action="production-prev">上一镜</button><button data-wf-action="production-next">下一镜</button><button data-wf-action="production-rewind">从头播放</button></div><label><input type="checkbox" data-wf-preview-voice> 使用浏览器系统试读原文台词（非最终配音，仍需校准时长）</label></details>`;
  html+=`<details open data-wf-production-shots><summary>逐镜设计与提示词 · ${result.shots.length} 个镜头</summary><p class="wf-muted">展开镜头即可修改表演、画面、提示词和物料状态。原文台词单独保留。修改后点击“保存修改并检查”。</p>${result.shots.map((shot,index)=>{
    const path=`shots.${index}`;
    return `<details class="wf-production-shot" ${index===0?'open':''}><summary>${String(index+1).padStart(3,'0')} · ${esc(shot.purpose)} · ${shot.durationSeconds} 秒${issues.some(i=>i.path.startsWith(path+'.'))?' · 引用待核对':''}</summary>${field('镜头目的',path+'.purpose',shot.purpose,{max:400,rows:2})}${field('动作',path+'.beat',shot.beat,{max:800})}<div class="wf-form-grid">${field('画面构图',path+'.framing',shot.framing,{max:500})}${field('摄影机',path+'.camera',shot.camera,{max:500})}</div>${cardsHtml(referenceCards(job,shot,assets,selection,apiBase),true)}<details><summary>修改镜头物料状态</summary>${shot.references.map((ref,ri)=>{const asset=result.assets.find(a=>a.id===ref.assetId);return `<label>${esc(asset?.name||ref.assetId)}<select data-wf-production-field="${path}.references.${ri}.stateId">${asset?.states.some(s=>s.id===ref.stateId)?'':`<option value="${esc(ref.stateId)}">当前状态无效，请选择</option>`}${(asset?.states||[]).map(s=>`<option value="${esc(s.id)}" ${s.id===ref.stateId?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label>`;}).join('')}</details>${field('建议时长（秒）',path+'.durationSeconds',shot.durationSeconds,{number:true,max:60})}${field('人物表演',path+'.performance',shot.performance,{max:1500})}${field('开始状态',path+'.startState',shot.startState)}${field('结束状态',path+'.endState',shot.endState)}${dialogueText(job,shot).map(d=>`<blockquote><small>${esc(d.label)} · 剧本原文</small><br>${esc(d.text)}</blockquote>`).join('')}${field('声音设计',path+'.sound',shot.sound)}${field('分镜静帧提示词',path+'.imagePrompt',shot.imagePrompt,{max:3000,rows:5})}${field('视频动作提示词',path+'.videoPrompt',shot.videoPrompt,{max:3000,rows:5})}<b>连续性检查</b>${list(shot.continuity)}<details><summary>查看 / 修改原文依据</summary>${quoteEditor(shot.evidence,path+'.evidence')}</details></details>`;
  }).join('')}</details>`;
  html+=`<div class="wf-production-handoff"><h4>继续制作资产</h4><p class="wf-muted">${!ready?'先核对标注的问题并保存，即可将物料加入资产清单。':changed?'先保存当前修改，再将物料加入资产清单。':'引用与关联检查通过，请核对创作内容后继续。'}</p><label class="wf-analysis-check"><input type="checkbox" data-wf-production-reviewed> 我已核对物料、状态和创作建议</label><button class="primary" data-wf-action="production-plan" ${busy||job.stale||!ready||changed?'disabled':''}>加入资产清单草稿 →</button><p class="wf-muted">仅新增本方案物料；保留现有条目和图片。</p></div>`;
  html+='<details><summary>原始返回与其他操作</summary><p class="wf-muted">AI 原始返回保留不变，手动修改另存为方案。</p>';
  if(job.returnedText)html+=`<details><summary>查看 AI 原始返回</summary><pre class="wf-production-raw">${esc(job.returnedText)}</pre></details>`;
  if(job?.canRevalidate)html+='<button data-wf-action="production-revalidate">重新核验原返回结果</button><p class="wf-muted">更新后的程序可重新核验原回执，不会新增 AI 调用。若内容仍不完整，会保留具体问题。</p>';
  if(job?.canRepairProduction)html+='<div class="wf-note"><label><input type="checkbox" data-wf-production-repair-spend> 允许 AI 修正原结果（额外 1 次文本调用）</label><button data-wf-action="production-repair">修正引用与物料关联</button><p class="wf-muted">保留原文和已有方案，让 AI 修正核验问题；本轮最多修正一次，不自动重试。</p></div>';
  html+=startControls+'</details>';
  return html+'</section>';
}

export function createPreview({root,getContext,onStatus=()=>{}}) {
  let timer=null,elapsed=0,index=-1,jobId=null,lastTick=0,spoken=-1;
  const win=root.ownerDocument.defaultView;
  function stop(){if(timer)clearInterval(timer);timer=null;win.speechSynthesis?.cancel();spoken=-1;}
  function sync(){const ctx=getContext(),job=ctx.job;if(!returnedResult(job))return null;if(jobId!==job.id){stop();jobId=job.id;elapsed=0;index=-1;}return ctx;}
  function draw(){const ctx=sync();if(!ctx)return;const {job}=ctx,shots=returnedResult(job).shots,total=shots.reduce((sum,s)=>sum+s.durationSeconds,0),current=timelineAt(shots,elapsed);
    const target=root.querySelector('[data-wf-preview-frame]');if(!target||!root.querySelector('[data-wf-production-preview]')?.open){stop();return;}
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
