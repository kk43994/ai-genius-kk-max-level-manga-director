import {canAutoCollect, nextCollection, collectionDelay, needsAssetRefresh} from './collection.js';
import {analysisPanel, sourceView} from './analysis.js';
import {operationLabel, elapsedLabel, taskProgress, reviewProgress} from './progress.js';
import {buildCustomerArchives} from '../asset-lab-archives.js';
import {nextAction, prepareIdentity} from './guide.js';
import {DraftStore, escapeHTML as esc, localBase, assetURL, categories, stages, stageLabels, states, recipes,
  approvedSources, belongsToSelection, resolveRefineSource, defaultPrompt} from './model.js';

const clone = value => JSON.parse(JSON.stringify(value));
const key = () => crypto.randomUUID();
const label = value => states[value] || value;
const tag = (state, text = label(state)) => `<span class="wf-tag ${esc(state)}">${esc(text)}</span>`;
const normalizePage = page => ({script:'plan',clean:'refine',export:'delivery',overview:'plan'}[page] || page);
const entityFields = ['id','category','name','description','origin','quote','scriptId','variant'];
const cleanEntity = entity => Object.fromEntries(entityFields.filter(k => entity[k] !== undefined).map(k => [k,entity[k]]));

export function mount({root, api, events = new EventTarget(), session, apiBase = '/api/v1', publicBasePath = '/', storage = globalThis.localStorage}) {
  if (!root || !api?.request || !session?.tenant?.id) throw new Error('工作流需要挂载节点、API 客户端与本站会话。');
  apiBase = localBase(apiBase, '/api/v1'); publicBasePath = localBase(publicBasePath, '/');
  const doc = root.ownerDocument;
  doc.body.dataset.workflowMounted = 'true';
  const drafts = new DraftStore(storage, session.tenant.id, apiBase);
  const listeners = [];
  let operation = null, operationSerial = 0, progressTimer, pollingTimer, lastChecked = null, polling = false;
  const transport = api;
  api = {...transport, request: async (url, options = {}) => {
    const writing = (options.method || 'GET') !== 'GET';
    const tracked = writing || (!operation && (loading || busy));
    const serial = tracked ? ++operationSerial : null;
    if (tracked) {operation = {serial, label:options.responseType==='blob'?'正在下载交付包':operationLabel(url,options.method), startedAt:Date.now()}; renderProgress();}
    try {return await transport.request(url, options);}
    finally {if (operation?.serial === serial) {operation = null; renderProgress();}}
  }};
  let alive = true, busy = false, loading = false, requestSerial = 0, timer, flowTimer, error = '', notice = '';
  let projects = [], project = null, plan = {version:0,entities:[],stylePrompt:''}, assets = [], bundles = [], tasks = [], scripts = [];
  let analysis = null, analysisError = '';
  let collecting = false;
  const collectionAttempts = new Map();
  let coverage = {total:0, ready:0, complete:false}, capabilities = {scriptAnalysis:false}, taskError = '';
  let selected = drafts.get('quick-start')?.text ? '' : drafts.get('selectedProject') || '', page = normalizePage(drafts.get('page') || 'plan');
  let selectedEntity = drafts.get('selectedEntity') || '', editing = false, reviewId = null, prepared = null;
  let filter = 'all', search = '', saveError = '', creating = Boolean(drafts.get('quick-start')?.text), focusedBeforeReview;
  const status = () => root.querySelector('[data-wf-status]');
  const listen = (target, event, handler) => { if (!target) return; target.addEventListener(event,handler); listeners.push(() => target.removeEventListener(event,handler)); };
  const announce = message => { notice = message; if (status()) status().textContent = message; };
  const currentAsset = () => assets.find(a => a.entityId === selectedEntity && a.active);
  const currentEntity = () => plan.entities.find(e => e.id === selectedEntity) || plan.entities[0];
  const planKey = () => `plan:${selected}`;
  const composeKey = () => `compose:${selected}:${selectedEntity}:${page}`;
  const image = (assetId, revisionId, thumb = true) => esc(assetURL(apiBase,assetId,revisionId,thumb));
  const path = relative => apiBase + relative;
  const dirty = () => Object.keys(drafts.data).some(k => k.startsWith('plan:') || k.startsWith('compose:') || k.startsWith('review:') || (k==='quick-start'&&drafts.get(k)?.text));
  const guide = () => scripts.length && !plan.entities.length && !drafts.get(planKey()) ? {kind:'analysis',title:analysis?.status==='ready'?'核对 AI 分析，建立资产清单':'先完成 AI 剧本分析',detail:analysis?.message||'用 AI 理解角色、场景、时间、地点、事件与台词。'} : nextAction({project, plan:{...plan,needsReview:plan.needsReview||Boolean(drafts.get(planKey()))}, assets, tasks, bundles, selection:session.selection, taskError, styleCount:session.features?.imageGeneration ? 4 : 1});

  const stylesheet = doc.createElement('link');
  stylesheet.rel = 'stylesheet'; stylesheet.href = new URL('./workflow.css', import.meta.url).href;
  stylesheet.dataset.workflowStyle = 'true'; doc.head.append(stylesheet);

  function persist(name, value) {
    try { drafts.set(name, value); saveError = ''; }
    catch (e) { saveError = '本机草稿保存失败。请先保存到项目，再刷新或升级页面。'; announce(saveError); }
    events.dispatchEvent(new CustomEvent('workflow:dirty', {detail:{dirty:dirty(), savedLocally:!saveError}}));
  }
  function removeDraft(name) { try { drafts.delete(name); saveError = ''; } catch { saveError = '本机草稿更新失败。'; } }
  async function flushDrafts() {
    if (busy) throw new Error('正在保存、导入或审核，请等待当前操作完成再刷新。');
    drafts.flush(); saveError = ''; return {saved:true, dirty:dirty(), scope:'local-tenant-drafts'};
  }
  function emitProject() { events.dispatchEvent(new CustomEvent('project:changed',{detail:{projectId:selected, project, coverage}})); events.dispatchEvent(new CustomEvent('shell:view',{detail:{workspaceState:project?'ready':'empty',projectName:project?.name||'开始创作'}})); }
  function renderStatus() { return `<div data-wf-status class="wf-status ${error || saveError ? 'wf-note wf-error' : 'wf-muted'}" role="status" aria-live="polite">${esc(error || saveError || notice)}${error?'<div class="wf-actions"><button data-wf-action="refresh">刷新状态</button><button data-wf-action="connect">检查账号与空间</button></div>':''}</div>`; }
  function options(values, selectedValue) { return values.map(([value,text]) => `<option value="${esc(value)}" ${value === selectedValue ? 'selected' : ''}>${esc(text)}</option>`).join(''); }
  function nav() {
    const entries = [['plan','01 清单'],['style','02 MJ 风格'],['asset','03 Image2'],['refine','04 Nano'],['review','05 审核'],['delivery','06 下载']];
    return `<nav class="wf-tabs" aria-label="资产制作步骤">${entries.map(([id,title]) => `<button type="button" data-wf-nav="${id}" ${page === id ? 'aria-current="step"' : ''}>${title}</button>`).join('')}</nav>`;
  }
  function stepNavigation() { return nav(); }
  function empty(title, detail) { return `<div class="wf-empty"><h3>${esc(title)}</h3><p class="wf-muted">${esc(detail)}</p></div>`; }
  function render() {
    if (!alive) return;
    const title = project ? project.name : projects.length ? '开始一个新项目' : '开始你的第一个项目';
    const chooser = projects.length ? `<label><span class="sr-only">当前项目</span><select data-wf-project>${!selected?'<option value="">选择已有项目</option>':''}${options(projects.map(p=>[p.id,p.name]),selected)}</select></label>` : '';
    root.innerHTML = `<section class="wf" aria-label="资产工作流"><div class="wf-toolbar"><div><span class="wf-muted">从一份剧本，到一套可用资产</span><h2>${esc(title)}</h2></div><div class="wf-actions">${chooser}<button type="button" data-wf-action="new-project" ${busy?'disabled':''}>＋ 新项目</button><button type="button" data-wf-action="refresh" ${busy ? 'disabled' : ''}>刷新状态</button></div></div>${renderStatus()}<div data-wf-operation></div>${project ? guideView()+stepNavigation() : ''}${loading ? '<p class="wf-muted" role="status">正在读取已保存项目…</p>' : !project ? createView() : page === 'plan' ? planView() : stages.includes(page) ? composeView() : page === 'review' ? reviewView()+tasksView(selectedEntity) : deliveryView()}${reviewId ? reviewDetail() : ''}${prepared ? confirmationView() : ''}</section>`;
    renderProgress(); renderLibrary();
    const saveStatus = doc.getElementById('saveStatus'); if (saveStatus) saveStatus.textContent = saveError ? '草稿保存失败' : busy ? '处理中' : dirty() ? '编辑草稿已在本机保存' : '项目已同步';
    const titleNode = doc.getElementById('workspace-title'); if (titleNode) titleNode.textContent = project?.name || '开始创作';
    const countNode = doc.getElementById('reviewCount'); if (countNode) countNode.textContent = assets.flatMap(a=>a.revisions).filter(r=>r.review==='pending' && r.status==='ready').length;
    if (busy) root.querySelectorAll('form button, [data-wf-action="approve"], [data-wf-action="reject"]').forEach(b=>b.disabled=true);
  }
  function renderProgress() {
    const target = root.querySelector('[data-wf-operation]'); if (!target) return;
    const active = operation || (busy ? {label:'正在处理当前步骤',startedAt:busyStartedAt} : null);
    target.hidden = !active;
    root.setAttribute('aria-busy', String(Boolean(active)));
    if (!active) {target.replaceChildren(); return;}
    target.innerHTML = `<section class="wf-live" role="status" aria-live="polite"><div><b>${esc(active.label)}</b><span data-wf-elapsed>${elapsedLabel(active.startedAt)}</span></div><progress aria-label="${esc(active.label)}"></progress><p>正在等待实际结果，尚无精确百分比。当前输入已保留，请勿重复提交。</p><p data-wf-slow ${Date.now()-active.startedAt<30000?'hidden':''}>此步骤耗时较长，仍在等待服务响应；返回后会显示可继续的操作。</p></section>`;
  }
  let busyStartedAt = 0;
  progressTimer = setInterval(() => {
    const active = operation || (busy ? {startedAt:busyStartedAt} : null);
    if(active){const node=root.querySelector('[data-wf-elapsed]');if(node)node.textContent=elapsedLabel(active.startedAt);const slow=root.querySelector('[data-wf-slow]');if(slow)slow.hidden=Date.now()-active.startedAt<30000;}
  },1000);
  pollingTimer = setInterval(() => {
    if(alive&&!loading&&!polling&&project&&doc.visibilityState!=='hidden'&&(['preparing','submitting','running','reviewing'].includes(analysis?.status)||collecting||busy||needsAssetRefresh(tasks,assets)||tasks.some(t=>canAutoCollect(t)||['preparing','submitting','queued','submitted','running','downloading'].includes(t.status))))void pollTasks();
  },5000);
  function createView() {
    const draft = drafts.get('new-project') || {name:'',description:''};
    const quick = drafts.get('quick-start') || {text:''};
    return `<section class="wf-panel wf-start"><p class="wf-eyebrow">ASSET LAB / 从剧本开始</p><h3>把故事放进来，<br>接下来的步骤交给工作台。</h3><p class="wf-muted">自动建立项目、提取资产清单、填写制作要求。你在关键节点确认清单和图片。</p><form data-wf-form="quick-start" class="wf-compose"><label>剧本正文<textarea name="text" rows="10" maxlength="250000" required placeholder="粘贴你的剧本，例如：&#10;《山间来信》&#10;角色：林舟、阿宁&#10;场景：旧书店&#10;道具：信封&#10;林舟：这封信，是留给你的。">${esc(quick.text)}</textarea></label><div class="wf-actions"><button class="primary" type="submit">开始制作 →</button><label class="wf-link">或导入剧本文件<input data-wf-quick-upload type="file" accept=".txt,.md,.docx" hidden></label><span class="wf-muted">TXT / MD / DOCX · 最大 8 MiB</span></div></form><ol class="wf-roadmap"><li>拆出清单</li><li>确定风格</li><li>制作资产</li><li>精修审核</li><li>下载交付</li></ol><p class="wf-muted">原文保存后点击 AI 分析，由 LibTV 文本模型提取六类信息并复核。分析和图片制作需要 LibTV 创作授权及可用积分。</p><details><summary>手工创建项目</summary><form data-wf-form="create" class="wf-compose"><label>项目名称<input name="name" maxlength="120" required value="${esc(draft.name)}"></label><label>项目说明（可选）<textarea name="description" maxlength="4000">${esc(draft.description)}</textarea></label><div><button type="submit">创建空项目</button></div></form></details></section>`;
  }
  function guideView() {
    const next = guide(), labels = {analysis:'查看 AI 分析与下一步',plan:plan.entities.length?'确认清单并继续':'补充资产清单',connect:'连接 / 选择账号',review:'查看图片并审核',prepare:'一键继续制作',confirm:'核对并继续',recover:'查询原任务',archive:'整理交付包',download:'下载全部资产',import:'导入剧本'};
    const unavailable = ['prepare','confirm'].includes(next.kind) && session.features?.imageGeneration !== true;
    const {done,total} = reviewProgress(plan.entities,assets,session.selection,belongsToSelection);
    return `<section class="wf-panel wf-guide" aria-label="一键制作进度"><div><p class="wf-eyebrow">${unavailable?'制作服务待就绪':'接下来只需这一步'}</p><h3>${esc(next.title)}</h3><p class="wf-muted">${esc(next.detail)}</p>${total?`<p class="wf-muted">${done} / ${total} 个制作环节已审核</p><progress class="wf-overall" value="${done}" max="${total}" aria-label="制作环节审核进度"></progress>`:''}${unavailable?'<p class="wf-note">这个版本的图片生成服务尚未开放。剧本和清单已保存，服务接通后从这里继续。</p>':''}</div><div class="wf-actions">${next.kind==='download'?`<a data-wf-download class="wf-link primary" href="${esc(path(`/projects/${encodeURIComponent(selected)}/bundles/${encodeURIComponent(next.bundle.id)}/content`))}">下载全部资产 ↓</a>`:next.kind==='blocked'?'<button data-wf-nav="review">查看任务与素材</button>':`<button class="primary" data-wf-action="continue" ${busy||unavailable?'disabled':''}>${labels[next.kind]||'继续'}</button>${unavailable?'<button data-wf-action="connect">查看已连接账号</button><button data-wf-action="refresh">检查服务状态</button>':''}`}${next.kind==='recover'?`<span class="wf-muted">${canAutoCollect(next.task)?'页面打开时自动收取':'点击查询原任务继续，不会重新生成'}</span>`:''}</div></section>`;
  }
  function planView() {
    const draft = drafts.get(planKey());
    const warnings = [...new Set(scripts.flatMap(s=>s.analysis?.warnings||[]))];
    const header = `<section class="wf-panel"><h3>剧本与资产清单</h3><div class="wf-actions"><label class="wf-link">导入剧本<input data-wf-upload type="file" accept=".txt,.md,.docx" hidden></label><button type="button" data-wf-action="edit-plan">${plan.entities.length ? '编辑资产清单' : '手工填写清单'}</button></div><p class="wf-muted">TXT / Markdown / DOCX · 单文件 ≤ 8 MiB。每项原文依据可以在清单中核对。</p>${warnings.length?`<div class="wf-note">${warnings.map(w=>esc(w)).join('<br>')}</div>`:''}${scripts.map(sourceView).join('')}</section>${analysisView()}`;
    if (editing || draft) return header + planEditor(draft || {expectedVersion:plan.version, entities:plan.entities.map(cleanEntity),stylePrompt:plan.stylePrompt});
    return header + `<div data-wf-archives>${archivesView()}</div>`;
  }
  function archivesView() {
    const archives = buildCustomerArchives(assets,plan);
    return (archives.length ? `<div class="wf-section-title"><h3>本项目档案</h3><span class="wf-muted">${archives.length} 项 · 未生成的条目也保留在这里</span></div><div class="wf-grid">${archives.map(a=>archiveCard(a)).join('')}</div>` : empty('等待 AI 分析结果','分析完成后核对六类信息，再建立角色与地点资产清单。'));
  }
  function analysisView() { return analysisPanel({script:scripts.at(-1),analysis,enabled:capabilities.scriptAnalysis,connected:Boolean(session.selection?.providerAccountId&&session.selection?.spaceId),busy,error:analysisError}); }
  function archiveCard(a) {
    return `<article class="wf-entity">${a.cover ? `<div class="wf-cover"><button class="wf-image-button" data-wf-review="${esc(a.cover.id)}" aria-label="查看 ${esc(a.name)} 原图与审核"><img src="${image(a.assetId,a.cover.id)}" alt="${esc(a.name)} ${esc(stageLabels[a.cover.stage])}" loading="lazy"></button></div>` : '<div class="wf-cover"><span class="wf-muted">待制作</span></div>'}<p>${tag('',categories[a.category])}</p><h3>${esc(a.name)}</h3><p class="wf-muted">${esc(a.description || '设定待补充')}</p><div class="wf-stage-line">${stages.map(s=>`<span class="${a.stages[s] ? 'done' : ''}">${esc(stageLabels[s])} ${a.stages[s]?'✓':a.revisions.some(r=>r.stage===s&&r.status==='ready'&&r.review==='pending')?'待审核':a.revisions.some(r=>r.stage===s&&r.review==='changes_requested')?'待返修':'待制作'}</span>`).join('')}</div><div class="wf-actions"><button data-wf-entity="${esc(a.id)}" data-wf-stage="${a.stages.asset?'refine':a.stages.style?'asset':'style'}">继续制作</button><button data-wf-archive="${esc(a.id)}">版本与审核 (${a.revisions.length})</button></div></article>`;
  }
  function planEditor(draft) {
    const conflict = draft.expectedVersion !== plan.version;
    return `<form data-wf-form="plan" class="wf-panel"><h3>核对资产清单</h3>${conflict?'<p class="wf-note wf-error">服务端清单已变化。当前编辑草稿完整保留，保存会进行冲突检查；请先核对新版。</p>':''}<label>统一视觉风格（创作设定）<textarea name="stylePrompt" maxlength="10000">${esc(draft.stylePrompt)}</textarea></label>${draft.entities.map((e,i)=>`<section class="wf-edit-row" data-wf-row="${i}" data-entity-id="${esc(e.id)}"><header><b>档案 ${i+1}</b><button type="button" data-wf-remove="${i}">移出本次清单</button></header><div class="wf-form-grid"><label>类别<select data-field="category">${options(Object.entries(categories),e.category)}</select></label><label>名称<input data-field="name" maxlength="120" required value="${esc(e.name)}"></label><label class="wf-full">设定说明<textarea data-field="description" maxlength="4000">${esc(e.description)}</textarea></label><label>变体 / 状态<input data-field="variant" maxlength="100" value="${esc(e.variant)}" placeholder="基础设定"></label><label>依据<select data-field="origin">${options([['manual','手工补充 / 创作设定'],['script','剧本原文']],e.origin)}</select></label><label>引用剧本<select data-field="scriptId"><option value="">仅原文条目需要选择</option>${options(scripts.map(s=>[s.id,s.filename]),e.scriptId)}</select></label><label>原文连续片段<textarea data-field="quote" maxlength="4000">${esc(e.quote)}</textarea></label></div></section>`).join('')}<div class="wf-actions"><button type="button" data-wf-action="add-entity">＋ 添加档案</button><button class="primary" type="submit">确认并保存清单</button></div><p class="wf-muted">改变设定或风格后，关联旧图会标记为依据已变更；历史图与审核记录仍保留。</p></form>`;
  }
  function getCompose() {
    const e = currentEntity(); if (!e) return null;
    if (selectedEntity !== e.id) selectedEntity = e.id;
    const old = drafts.get(composeKey()); if (old) return page==='style'&&session.features?.imageGeneration?{...old,count:'4'}:old;
    const source = approvedSources(currentAsset(),page,session.selection)[0];
    return {prompt:defaultPrompt(e,page,plan.stylePrompt),sourceRevisionId:source?.id || '',count:page==='style'&&session.features?.imageGeneration?'4':'1',ratio:'',prepareKey:key()};
  }
  function composeView() {
    const e = currentEntity(); if (!e) return empty('还没有资产档案','先在清单中添加角色、场景或道具。');
    if (selectedEntity !== e.id) selectedEntity = e.id;
    const draft = getCompose(), sources = approvedSources(currentAsset(),page,session.selection);
    const selectedSource = sources.find(s=>s.id===draft.sourceRevisionId), connected = session.selection?.providerAccountId && session.selection?.spaceId;
    return `<section class="wf-panel"><h3>${esc(stageLabels[page])}</h3><p class="wf-muted">${page==='style'?'探索风格，先由你选定这一版，再制作 Image2 资产。':page==='asset'?'已审核的 MJ 风格作为依据，制作可复用的角色、场景和道具。':'使用原始 Image2 文件精修。退回后的 Nano 图片不会被当作新的原图。'}</p><form data-wf-form="compose" class="wf-compose"><label>资产档案<select data-wf-entity-select>${options(plan.entities.map(item=>[item.id,`${categories[item.category]} · ${item.name}`]),selectedEntity)}</select></label>${page!=='style'?`<label>上一阶段已审核参考<select name="sourceRevisionId" required><option value="">请选择当前账号 / 空间的已审核版本</option>${options(sources.map(r=>[r.id,`${stageLabels[r.stage]} · ${r.id.slice(-6)} · 已审核`]),draft.sourceRevisionId)}</select></label>${selectedSource?`<div class="wf-reference"><img src="${image(selectedSource.assetId,selectedSource.id)}" alt="已审核参考原图"><span class="wf-muted">${esc(selectedSource.ownership.accountLabelAtCreation || selectedSource.ownership.providerAccountId)} / ${esc(selectedSource.ownership.spaceNameAtCreation || selectedSource.ownership.spaceId)}</span></div>`:'<p class="wf-note">尚未选择可用参考。每一步需要先通过人工审核，且不能混用其他账号或空间的图片。</p>'}`:''}<label>制作要求<textarea name="prompt" rows="7" maxlength="20000" required>${esc(draft.prompt)}</textarea></label><div class="wf-form-grid"><label>候选数量<select name="count">${options(page==='style'&&session.features?.imageGeneration?[['4','4 张（MJ 一组）']]:[['1','1 张'],['2','2 张'],['4','4 张']],String(draft.count))}</select></label><label>画幅（可选）<select name="ratio">${options([['','使用官方模型默认'],['16:9','16:9'],['9:16','9:16'],['1:1','1:1']],draft.ratio)}</select></label></div>${!connected?'<div class="wf-note">请先选择已授权的 LibTV 账号与空间。当前草稿会保留。</div>':''}<div class="wf-actions"><button class="primary" type="submit" ${!connected || (page!=='style'&&!selectedSource)?'disabled':''}>准备任务并核对</button><button type="button" data-wf-nav="review">查看返回结果</button></div><p class="wf-muted">准备不会提交生成。模型与参数以官方适配器核验为准；金额未知时不会显示为免费。${session.features?.imageGeneration?'提交后使用当前已授权账号的 LibTV 积分。':'图片提交服务尚未启用。'}</p></form></section><div data-wf-returned>${returnedView(e.id)}</div>${tasksView(e.id)}`;
  }
  function returnedView(entityId) {
    const asset=assets.find(a=>a.entityId===entityId&&a.active);
    const rows=(asset?.revisions||[]).filter(r=>r.status==='ready'&&r.review==='pending');
    return rows.length ? `<section class="wf-panel"><div class="wf-section-title"><h3>已返回 · ${rows.length} 张候选图待审核</h3><button data-wf-nav="review">进入审核</button></div><p class="wf-muted">图片已保存到当前项目，点击缩略图查看原图并决定是否保留。</p><div class="wf-review-list">${rows.map(r=>`<article class="wf-revision"><div class="wf-cover"><button class="wf-image-button" data-wf-review="${esc(r.id)}" aria-label="查看 ${esc(asset.name)} 候选图"><img src="${image(asset.id,r.id)}" alt="${esc(asset.name)} ${esc(stageLabels[r.stage])}" loading="lazy"></button></div><p>${esc(stageLabels[r.stage])} · 待人工审核</p><button data-wf-review="${esc(r.id)}">查看并审核</button></article>`).join('')}</div></section>` : '';
  }
  function taskLabel(task) {
    if(task.status!=='completed')return label(task.status);
    const revisions=assets.flatMap(a=>a.revisions).filter(r=>r.taskId===task.id);
    if(!revisions.length)return '已返回 · 待接入审核';
    if(revisions.every(r=>r.status==='stale'))return '已返回 · 依据已变更';
    if(revisions.some(r=>r.review==='approved'&&r.status==='ready'))return '已返回 · 已保留';
    if(revisions.some(r=>r.review==='changes_requested'))return '已返回 · 待返修';
    return '已返回 · 待人工审核';
  }
  function tasksView(entityId) {
    const rows = tasks.filter(t=>!entityId || t.entityId===entityId);
    return `<section class="wf-panel" data-wf-task-feedback><h3>当前档案的任务</h3>${taskError?`<p class="wf-note">${esc(taskError)}</p>`:''}<p class="wf-muted">${lastChecked?'本地状态更新 '+esc(lastChecked.toLocaleTimeString()):'正在检查任务状态'} · 处理中的任务每 5 秒刷新</p>${rows.length?`<ul class="wf-task-list">${rows.map(t=>`<li>${tag(t.status,taskLabel(t))} <b>${esc(stageLabels[Object.keys(recipes).find(s=>recipes[s]===t.recipe)] || t.recipe)}</b><p class="wf-muted">${esc(t.ownership?.accountLabelAtCreation||t.ownership?.providerAccountId)} / ${esc(t.ownership?.spaceNameAtCreation||t.ownership?.spaceId)} · ${esc(t.id.slice(-8))}</p><p class="wf-muted">${esc(taskProgress(t))} · 更新于 ${esc(new Date(t.updatedAt).toLocaleTimeString())}</p>${['preparing','submitting','queued','submitted','running','downloading'].includes(t.status)?'<progress aria-label="任务处理中，等待实际结果"></progress>':''}${t.error?`<p class="wf-note">${esc(t.error.message)}</p>`:''}${!t.submissionAttempted&&!['completed','cancelled'].includes(t.status)?`<button data-wf-cancel="${esc(t.id)}">取消未提交记录</button>`:''}${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询原任务并收取</button>`:''}</li>`).join('')}</ul>`:'<p class="wf-muted">还没有任务。准备后的任务归属会固定保存，切换账号不改变旧任务。</p>'}</section>`;
  }
  function allRevisions() { return assets.filter(a=>!selectedEntity || a.entityId===selectedEntity).flatMap(a=>a.revisions.map(r=>({...r,asset:a}))); }
  function reviewView() {
    const rows = allRevisions().sort((a,b)=>(a.review==='pending'?-1:0)-(b.review==='pending'?-1:0)||b.createdAt.localeCompare(a.createdAt));
    return `<section class="wf-panel" data-wf-review-list><div class="wf-section-title"><h3>比较版本，决定保留或返修</h3><select aria-label="筛选审核档案" data-wf-review-entity><option value="">全部档案</option>${options(plan.entities.map(e=>[e.id,e.name]),selectedEntity)}</select></div><p class="wf-muted">“任务完成”表示图片已返回；只有人工保留后才进入下一步。历史与失效版本保留供核对。</p>${rows.length?`<div class="wf-review-list">${rows.map(r=>`<article class="wf-revision"><div class="wf-cover"><button class="wf-image-button" data-wf-review="${esc(r.id)}" aria-label="查看 ${esc(r.asset.name)} 原图与审核"><img src="${image(r.assetId,r.id)}" alt="${esc(r.asset.name)} ${esc(stageLabels[r.stage])}" loading="lazy"></button></div><h4>${esc(r.asset.name)} · ${esc(stageLabels[r.stage])}</h4>${tag(r.status==='stale'?'stale':r.review)}<p class="wf-muted">${r.width} × ${r.height} · ${esc(r.id.slice(-6))}</p><div class="wf-actions"><button data-wf-review="${esc(r.id)}">对比 / 审核</button>${r.review==='changes_requested'?`<button data-wf-repair="${esc(r.id)}">按意见返修</button>`:''}</div></article>`).join('')}</div>`:empty('等待你的第一份候选图','返回图片会在这里展示，所有阶段都需要你确认。')}</section>`;
  }
  function reviewDetail() {
    const asset = assets.find(a=>a.revisions.some(r=>r.id===reviewId)), r=asset?.revisions.find(r=>r.id===reviewId); if(!r)return '';
    const original = r.stage==='refine'?resolveRefineSource(r,asset.revisions):asset.revisions.find(s=>s.id===r.sourceRevisionIds[0]);
    const previous = asset.revisions.filter(s=>s.stage===r.stage&&s.id!==r.id).at(-1), comparison=original||previous;
    const note = drafts.get(`review:${r.id}`)?.note || '';
    return `<section class="wf-panel" data-review-detail tabindex="-1" aria-label="${esc(asset.name)} 对比审核"><div class="wf-section-title"><h3>${esc(asset.name)} · ${esc(stageLabels[r.stage])}</h3><button data-wf-action="close-review">收起审核</button></div><div class="wf-comparison">${comparison?`<figure><img src="${image(comparison.assetId,comparison.id,false)}" alt="${r.stage==='refine'?'原始 Image2 设计基准':'参考或上一个版本'}"><figcaption>${r.stage==='refine'?'原始 Image2 · 设计基准':original?'上一阶段已选参考':'上一个版本'}</figcaption></figure>`:''}<figure><img src="${image(r.assetId,r.id,false)}" alt="本次待审候选"><figcaption>本次候选 · ${esc(r.id.slice(-6))} · ${esc(label(r.review))}</figcaption></figure></div><p class="wf-muted">归属：${esc(r.ownership.accountLabelAtCreation||r.ownership.providerAccountId)} / ${esc(r.ownership.spaceNameAtCreation||r.ownership.spaceId)}</p><ul class="wf-review-checks"><li>身份、轮廓与设定是否一致</li><li>服装纹样、结构与道具细节是否保留</li><li>构图、光向、画幅与视图数量是否正确</li><li>没有额外文字、拼接错误或细节洗糊</li></ul><label>具体审核 / 返修意见<textarea data-wf-review-note maxlength="2000" placeholder="写清问题的位置、期望修改和必须保留的内容。">${esc(note)}</textarea></label><div class="wf-actions"><button data-wf-action="reject" ${r.status==='stale'?'disabled':''}>退回修改</button><button class="primary" data-wf-action="approve" ${r.status==='stale'?'disabled':''}>保留此版</button><a class="wf-link" href="${image(r.assetId,r.id,false)}" target="_blank" rel="noopener">打开原图</a></div>${r.status==='stale'?'<p class="wf-note">此图的依据已经变化，不能继续审核或作为新参考。请使用当前已审核的上游版本重新制作。</p>':''}<details><summary>审核历史 (${r.reviewHistory.length})</summary>${r.reviewHistory.map(h=>`<p class="wf-muted">${esc(label(h.decision))} · ${esc(new Date(h.at).toLocaleString())}<br>${esc(h.note)}</p>`).join('')}</details></section>`;
  }
  function confirmationView() {
    const task=prepared.task, cost=prepared.cost || task.cost || {}, enabled=session.features?.imageGeneration===true;
    return `<section class="wf-panel" data-confirmation tabindex="-1"><h3>核对这次任务</h3><p>生成 ${esc(prepared.confirmation?.summary?.count || task.spec?.settings?.count || 1)} 张候选图</p><p class="wf-note">任务账号：${esc(task.ownership?.accountLabelAtCreation||task.ownership?.providerAccountId)}<br>工作空间：${esc(task.ownership?.spaceNameAtCreation||task.ownership?.spaceId)}<br>费用：${cost.state==='known'?esc(`${cost.amount} ${cost.unit}`):'未知 · 不能视为免费'}</p><p class="wf-muted">切换页面上的账号不会改变这个任务的归属。${!enabled?'当前版本未启用图片提交；准备记录已保存。':''}</p><div class="wf-actions"><button data-wf-action="close-confirmation">保留准备记录</button><button data-wf-action="submit-task" class="primary" ${!enabled||busy?'disabled':''}>确认并提交生成</button></div></section>`;
  }
  function deliveryView() {
    const approved = assets.flatMap(a=>a.revisions).filter(r=>r.review==='approved'&&r.status==='ready');
    return `<section class="wf-panel"><h3>已确认资产，安心交付</h3><p>${coverage.ready} / ${coverage.total} 个档案完成 MJ → Image2 → Nano 审核</p><div class="wf-progress"><span style="width:${coverage.total?Math.round(100*coverage.ready/coverage.total):0}%"></span></div><p class="wf-muted">下载包含有效的已审核图片、版本来源和逐文件 SHA-256。未审核、已退回或依据已变更的图片不会进入交付包。</p><div class="wf-actions">${approved.length?`<a data-wf-download class="wf-link" href="${esc(path(`/projects/${encodeURIComponent(selected)}/export`))}">下载已审核资产 (${approved.length})</a>`:'<button disabled>尚无可下载的已审核图片</button>'}<button class="primary" data-wf-action="archive" ${!coverage.complete?'disabled':''}>确认完成并归档</button></div>${!coverage.complete?`<div class="wf-note">尚有 ${(coverage.missing||[]).map(e=>esc(e.name)).join('、')||'未建档资产'} 未完成。当前下载属于部分交付。</div>`:''}</section><section class="wf-panel"><h3>交付归档</h3>${bundles.length?bundles.map(b=>`<div class="wf-note"><b>${esc(new Date(b.createdAt).toLocaleString())}</b><p>${b.assetCount} 张已审核资产 · ${Math.ceil(b.bytes/1024)} KiB</p><a data-wf-download class="wf-link" href="${esc(path(`/projects/${encodeURIComponent(selected)}/bundles/${encodeURIComponent(b.id)}/content`))}">下载这次归档</a></div>`).join(''):'<p class="wf-muted">归档保存当时确认的交付包。以后返修与换版不会覆盖旧交付。</p>'}</section>`;
  }
  function renderLibrary() {
    const select=doc.getElementById('scriptSelect'); if(select){select.innerHTML=projects.length?(!selected?'<option value="">选择已有项目</option>':'')+options(projects.map(p=>[p.id,p.name]),selected):'<option value="">新建你的第一个项目</option>';select.value=selected;}
    const list=doc.getElementById('warehouseList'); if(!list)return;
    const rows=buildCustomerArchives(assets,plan).filter(e=>(filter==='all'||e.category===filter)&&(!search||(e.name+' '+e.description).includes(search)));
    list.innerHTML=rows.length?`<div class="wf">${rows.map(e=>`<button class="wf-library-button" data-wf-archive="${esc(e.id)}">${e.cover?`<img class="wf-library-thumb" src="${image(e.assetId,e.cover.id)}" alt="${esc(e.name)} 缩略图" loading="lazy">`:'<span class="wf-library-placeholder" aria-hidden="true">待制作</span>'}<span><b>${esc(e.name)}</b><small>${esc(categories[e.category])} · ${e.revisions.length} 个版本 · ${e.stages.refine?'精修已审核':e.cover?label(e.cover.review):'待制作'}</small></span></button>`).join('')}</div>`:'<p class="wf-muted">先填写资产清单，档案会出现在这里。</p>';
    const count=doc.getElementById('warehouseCount');if(count)count.textContent=plan.entities.length;
    const summary=doc.getElementById('review-summary-root');if(summary){const pending=assets.flatMap(a=>a.revisions).filter(r=>r.review==='pending'&&r.status==='ready').length;summary.innerHTML=`<div class="wf wf-panel"><b>${pending} 张图片等待你审核</b><p class="wf-muted">每一步确认后，才能进入下一阶段。</p></div>`;}
  }
  async function load({initial=false}={}) {
    const serial=++requestSerial;loading=initial;error='';if(initial)render();
    try {
      const [projectResult, caps]=await Promise.all([api.request('/projects'),api.request('/workflow/capabilities')]);capabilities=caps;if(!alive||serial!==requestSerial)return;
      projects=projectResult.items || [];
      if(!creating&&!projects.some(p=>p.id===selected))selected=projects[0]?.id || '';
      project=projects.find(p=>p.id===selected)||null;
      if(!project){analysis=null;analysisError='';plan={version:0,entities:[],stylePrompt:''};assets=[];scripts=[];tasks=[];bundles=[];coverage={total:0,ready:0,complete:false};return;}
      const projectId=selected;
      const replies=await Promise.all([
        api.request(`/projects/${encodeURIComponent(projectId)}/plan`),
        api.request(`/projects/${encodeURIComponent(projectId)}/assets`),
        api.request(`/projects/${encodeURIComponent(projectId)}/bundles`),
        loadTasks(projectId).then(value=>({ok:true,value}),e=>({ok:false,error:e})),
      ]);
      if(!alive||serial!==requestSerial||projectId!==selected)return;
      [plan]=replies;assets=replies[1].items||[];coverage=replies[1].coverage||{total:plan.entities.length,ready:0,complete:false};bundles=replies[2].items||[];
      if(replies[3].ok){tasks=replies[3].value.items||[];taskError='';lastChecked=new Date();}else{tasks=[];taskError=replies[3].error.message||'任务服务尚未就绪。';}
      const loadedScripts=await Promise.all(project.scriptIds.map(id=>api.request(`/projects/${encodeURIComponent(projectId)}/scripts/${encodeURIComponent(id)}`)));
      if(!alive||serial!==requestSerial||projectId!==selected)return;scripts=loadedScripts;analysis=null;analysisError='';
      if(scripts.length){try{const response=await api.request(`/projects/${encodeURIComponent(projectId)}/scripts/${encodeURIComponent(scripts.at(-1).id)}/analysis`);if(!alive||serial!==requestSerial||projectId!==selected)return;analysis=response.analysis;}catch(e){analysisError=e.message||'AI 分析状态暂不可用。';}}
      if(selectedEntity && !plan.entities.some(e=>e.id===selectedEntity))selectedEntity='';
      persist('selectedProject',selected);emitProject();
    } catch(e) {if(alive&&serial===requestSerial)error=e.message||'读取项目失败，编辑草稿已保留。';}
    finally {if(alive&&serial===requestSerial){loading=false;render();scheduleFlow();events.dispatchEvent(new CustomEvent('workflow:tasks-refreshed',{detail:{projectId:selected}}));}}
  }
  async function loadTasks(projectId) {
    let cursor, items=[];
    for(let i=0;i<50;i++){
      const result=await api.request(`/tasks?projectId=${encodeURIComponent(projectId)}&limit=100${cursor?'&cursor='+encodeURIComponent(cursor):''}`);
      items.push(...(result.items||[]));if(!result.nextCursor)return {items};cursor=result.nextCursor;
    }
    throw new Error('任务记录较多，尚未读取完整；已暂停准备新任务。');
  }
  async function pollTasks() {
    const projectId=selected, serial=requestSerial;
    polling=true;let mediaChanged=false;
    try {
      if(analysis?.canRefresh){const updated=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/refresh`,{method:'POST',body:{}});if(!alive||serial!==requestSerial||projectId!==selected)return;analysis=updated;analysisError='';const panel=root.querySelector('[data-wf-analysis]');if(panel)panel.outerHTML=analysisView();}
      // Read tasks first: a completed task guarantees its outputs were persisted.
      const result=await loadTasks(projectId);
      const received=await api.request(`/projects/${encodeURIComponent(projectId)}/assets`);
      if(!alive||serial!==requestSerial||projectId!==selected)return;
      const previous=new Set(assets.flatMap(a=>a.revisions.map(r=>r.id)));
      mediaChanged=JSON.stringify(assets)!==JSON.stringify(received.items||[]);
      assets=received.items||[];coverage=received.coverage||coverage;
      const added=assets.flatMap(a=>a.revisions).filter(r=>!previous.has(r.id)&&r.status==='ready').length;
      tasks=result.items;taskError='';lastChecked=new Date();
      if(added)announce(`${added} 张图片已自动返回，缩略图已更新，等待你审核。`);
    } catch(e) {
      if(!alive||serial!==requestSerial||projectId!==selected)return;
      taskError=e.message||'任务状态暂时无法读取，已有记录已保留。';
    } finally {
      polling=false;
      if(alive&&serial===requestSerial&&projectId===selected){
        // Keep form nodes and their caret intact while refreshing background status.
        const taskPanel=root.querySelector('[data-wf-task-feedback]');if(taskPanel)taskPanel.outerHTML=tasksView(selectedEntity);
        if(mediaChanged){
        const returned=root.querySelector('[data-wf-returned]');if(returned)returned.innerHTML=returnedView(selectedEntity||currentEntity()?.id);
        const reviewPanel=root.querySelector('[data-wf-review-list]');if(reviewPanel)reviewPanel.outerHTML=reviewView();
        const archives=root.querySelector('[data-wf-archives]');if(archives)archives.innerHTML=archivesView();
        renderLibrary();
        const countNode=doc.getElementById('reviewCount');if(countNode)countNode.textContent=assets.flatMap(a=>a.revisions).filter(r=>r.review==='pending'&&r.status==='ready').length;
        }
        const guidePanel=root.querySelector('.wf-guide');if(guidePanel)guidePanel.outerHTML=guideView();
        events.dispatchEvent(new CustomEvent('workflow:tasks-refreshed',{detail:{projectId}}));
        scheduleFlow();
      }
    }
  }
  function scheduleFlow() {
    const pending=alive&&project?nextCollection(tasks,collectionAttempts):null;
    if(!pending){clearTimeout(flowTimer);flowTimer=null;return;}
    // Receipt collection is independent of plan editing, the guide and auto-flow drafts.
    if(flowTimer||collecting)return;
    flowTimer=setTimeout(()=>{
      flowTimer=null;
      if(alive&&!busy&&!loading&&doc.visibilityState!=='hidden')void collectOriginal(pending.task.id);
      else scheduleFlow();
    },Math.max(1000,pending.due-Date.now()));
  }
  async function collectOriginal(taskId) {
    const task=tasks.find(t=>t.id===taskId),projectId=selected;
    if(collecting||!task||!canAutoCollect(task))return;
    collecting=true;
    try {
      const result=await api.request(`/tasks/${encodeURIComponent(task.id)}/recover`,{method:'POST',body:{expectedVersion:task.version}});
      collectionAttempts.set(task.id,{due:Date.now()+collectionDelay(result.task)});
    } catch(e) {
      collectionAttempts.set(task.id,{due:Date.now()+30000});
      if(alive&&projectId===selected&&!['TASK_BUSY','VERSION_CONFLICT'].includes(e.code))announce('原任务收取暂时中断，稍后自动继续；也可点击“查询原任务并收取”。');
    } finally {
      collecting=false;
      if(alive&&projectId===selected&&!polling)await pollTasks();
      if(alive)scheduleFlow();
    }
  }
  async function continueFlow() {
    if(busy||loading||!project)return;
    persist(`flow:${selected}`,true);
    const next=guide();
    if(next.kind==='analysis')return navigate('plan');
    if(next.kind==='plan'){
      if(!plan.entities.length||drafts.get(planKey())){editing=true;if(!drafts.get(planKey()))persist(planKey(),{expectedVersion:plan.version,entities:plan.entities.map(cleanEntity),stylePrompt:plan.stylePrompt});return navigate('plan');}
      await perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/plan`,{method:'PUT',body:{expectedVersion:plan.version,entities:plan.entities.map(cleanEntity),stylePrompt:plan.stylePrompt}});await load();});
      if(!error)continueAfterReview();return;
    }
    if(next.kind==='connect'){events.dispatchEvent(new CustomEvent('workflow:connect'));announce(next.detail);return;}
    if(next.kind==='import'){root.querySelector('[data-wf-upload]')?.click();return;}
    if(next.kind==='review'){selectedEntity=next.entity.id;page='review';persist('selectedEntity',selectedEntity);persist('page',page);return openReview(next.revision.id);}
    if(['prepare','confirm'].includes(next.kind)&&session.features?.imageGeneration!==true){announce('图片制作服务尚未开放，剧本与清单已保存。');return;}
    if(next.kind==='prepare')return perform(async()=>{
      const revision=session.selection.revision, idempotencyKey=await prepareIdentity(next.spec,revision,
        {entityVersion:next.entity.version,styleVersion:plan.styleVersion,...(next.cancelledTaskId?{cancelledTaskId:next.cancelledTaskId}:{})});
      prepared=await api.request('/tasks/prepare',{method:'POST',body:{...next.spec,expectedSelectionRevision:revision},idempotencyKey});
      selectedEntity=next.entity.id;page=next.stage;await load();
      if(!prepared.confirmation){announce(prepared.task?.error?.message||'制作尚未就绪，请核对任务状态。');prepared=null;}
    });
    if(next.kind==='confirm')return perform(async()=>{prepared=await api.request(`/tasks/${encodeURIComponent(next.task.id)}/confirm`,{method:'POST',body:{expectedVersion:next.task.version}});await load();});
    if(next.kind==='recover')return perform(async()=>{await api.request(`/tasks/${encodeURIComponent(next.task.id)}/recover`,{method:'POST',body:{expectedVersion:next.task.version}});await load();});
    if(next.kind==='archive')return perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/bundles`,{method:'POST',body:{expectedVersion:project.version}});page='delivery';persist('page',page);await load();});
  }
  function continueAfterReview() {
    if(drafts.get(`flow:${selected}`))setTimeout(()=>{if(alive&&!busy)void continueFlow();},0);
  }
  async function perform(operation) {
    if(busy)return;busy=true;busyStartedAt=Date.now();error='';notice='';render();
    try {await operation();}catch(e){error=e.message||'操作未完成，原有数据与草稿已保留。';}
    finally {busy=false;render();}
  }
  function capturePlan(form) {
    const draft=drafts.get(planKey())||{expectedVersion:plan.version};
    return {...draft,stylePrompt:form.elements.stylePrompt.value,entities:[...form.querySelectorAll('[data-wf-row]')].map(row=>{
      const entity={id:row.dataset.entityId};row.querySelectorAll('[data-field]').forEach(input=>entity[input.dataset.field]=input.value);return entity;
    })};
  }
  function captureCompose(form) {
    const draft=getCompose();return {...draft,prompt:form.elements.prompt.value,sourceRevisionId:form.elements.sourceRevisionId?.value||'',
      count:form.elements.count.value,ratio:form.elements.ratio.value,prepareKey:key()};
  }
  function navigate(next) {
    page=normalizePage(next);if(!['plan',...stages,'review','delivery'].includes(page))page='plan';
    reviewId=null;persist('page',page);render();root.scrollIntoView({behavior:'smooth',block:'start'});
  }
  async function switchProject(id) {
    if(busy||id===selected)return;clearTimeout(flowTimer);flowTimer=null;creating=false;selected=id;selectedEntity='';reviewId=null;prepared=null;editing=false;
    persist('selectedProject',id);persist('selectedEntity','');await load({initial:true});
  }
  function openReview(id, button) {
    reviewId=id;focusedBeforeReview=button;render();root.querySelector('[data-review-detail]')?.focus();root.querySelector('[data-review-detail]')?.scrollIntoView({behavior:'smooth',block:'start'});
  }
  async function decide(decision) {
    const asset=assets.find(a=>a.revisions.some(r=>r.id===reviewId)),r=asset?.revisions.find(r=>r.id===reviewId);if(!r)return;
    const note=drafts.get(`review:${r.id}`)?.note||'';
    if(decision==='changes_requested'&&note.trim().length<4){error='请填写至少 4 个字的具体返修意见。';render();return;}
    await perform(async()=>{
      await api.request(`/assets/${encodeURIComponent(asset.id)}/reviews`,{method:'POST',body:{revisionId:r.id,sha256:r.sha256,decision,note,expectedVersion:asset.version}});
      removeDraft(`review:${r.id}`);reviewId=null;announce(decision==='approved'?'这一版已保留，将按项目进度继续。':'返修意见已保存；尚未发起新的生成。');
      events.dispatchEvent(new CustomEvent('workflow:reviewed',{detail:{projectId:selected,assetId:asset.id,revisionId:r.id,decision}}));await load();
    });
    if(!error)continueAfterReview();
  }
  function repair(id) {
    const asset=assets.find(a=>a.revisions.some(r=>r.id===id)),r=asset?.revisions.find(r=>r.id===id);if(!r)return;
    if(!belongsToSelection(r,session.selection)){error='请切回这份素材所属的账号与空间，再准备返修。';render();return;}
    if(r.review!=='changes_requested'||!r.reviewNote){error='请先记录具体的返修意见。';render();return;}
    const original=r.stage==='refine'?resolveRefineSource(r,asset.revisions):null;
    const sourceId=original?.id||r.sourceRevisionIds[0]||'';
    const base=r.stage==='style'?'':asset.revisions.find(s=>s.id===sourceId);
    if(r.stage!=='style'&&(!base||base.review!=='approved'||base.status!=='ready')){error='返修所需的原始参考已失效，请使用当前已审核的上游版本重新准备。';render();return;}
    selectedEntity=asset.entityId;page=r.stage;reviewId=null;persist('selectedEntity',selectedEntity);persist('page',page);
    persist(composeKey(),{prompt:`${r.prompt}\n返修意见：${r.reviewNote}`,sourceRevisionId:sourceId,count:'1',ratio:r.settings?.ratio||'',prepareKey:key(),repairOfRevisionId:r.id});
    announce(r.stage==='refine'?'已回到原始 Image2 文件准备 Nano 返修，尚未提交。':'已按审核意见准备返修草稿，尚未提交。');render();
  }
  async function upload(file) {
    if(!file)return;if(!selected){error='请先创建一个项目，再导入剧本。';render();return;}
    if(!/\.(txt|md|docx)$/i.test(file.name)||file.size>8*1024*1024||!file.size){error='请选择不超过 8 MiB 的 TXT、MD 或 DOCX 文件。';render();return;}
    await perform(async()=>{
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
      for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
      const result=await api.request(`/projects/${encodeURIComponent(selected)}/scripts`,{method:'POST',body:{filename:file.name,contentBase64:btoa(binary)}});
      page='plan';persist('page',page);announce(result.duplicate?'这份剧本已保存，已恢复原记录。':'剧本原文已保存，点击“开始 AI 分析”继续。');await load();
    });
  }
  async function startFromFile(file) {
    if(!file)return;
    if(!/\.(txt|md|docx)$/i.test(file.name)||file.size>8*1024*1024||!file.size){error='请选择不超过 8 MiB 的 TXT、MD 或 DOCX 文件。';render();return;}
    await perform(async()=>{
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let offset=0;offset<bytes.length;offset+=8192)binary+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
      const source={filename:file.name,contentBase64:btoa(binary)};
      // Content identity survives a lost response without storing a large file in localStorage.
      await quickStart({...source,idempotencyKey:await prepareIdentity(source,0)});
    });
  }
  async function quickStart(body) {
    const result=await api.request('/workflow/start',{method:'POST',body});
    project=result.project;selected=project.id;creating=false;page='plan';editing=false;
    if(drafts.get('quick-start')?.text===body.text)removeDraft('quick-start');
    persist('selectedProject',selected);persist('page',page);persist(`flow:${selected}`,true);
    announce(result.duplicate?'已恢复这份剧本的项目。':'项目和剧本已保存，点击“开始 AI 分析”提取六类信息。');await load();
    root.querySelector('.wf-guide')?.scrollIntoView({behavior:'smooth',block:'start'});
  }
  function onInput(event) {
    const target=event.target;if(target.matches('[data-wf-review-note]')&&reviewId){persist(`review:${reviewId}`,{note:target.value});return;}
    const form=target.closest('[data-wf-form]');if(!form)return;
    if(form.dataset.wfForm==='plan')persist(planKey(),capturePlan(form));
    if(form.dataset.wfForm==='compose')persist(composeKey(),captureCompose(form));
    if(form.dataset.wfForm==='create')persist('new-project',Object.fromEntries(new FormData(form)));
    if(form.dataset.wfForm==='quick-start')persist('quick-start',{text:form.elements.text.value,idempotencyKey:key()});
  }
  async function onSubmit(event) {
    const form=event.target.closest('[data-wf-form]');if(!form)return;event.preventDefault();
    if(form.dataset.wfForm==='quick-start'){
      const saved=drafts.get('quick-start'),text=form.elements.text.value;
      const body={text,idempotencyKey:(saved?.text===text&&saved.idempotencyKey)||key()};persist('quick-start',body);
      return perform(()=>quickStart(body));
    }
    if(form.dataset.wfForm==='create'){
      const body=Object.fromEntries(new FormData(form));persist('new-project',body);
      return perform(async()=>{project=await api.request('/projects',{method:'POST',body});selected=project.id;creating=false;removeDraft('new-project');page='plan';persist('page',page);announce('项目已保存，可以导入剧本或填写清单。');await load();});
    }
    if(form.dataset.wfForm==='plan'){
      const body=capturePlan(form);persist(planKey(),body);
      await perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/plan`,{method:'PUT',body});removeDraft(planKey());editing=false;announce('清单已保存，所有档案已建立。');await load();});
      if(!error)continueAfterReview();return;
    }
    if(form.dataset.wfForm==='compose'){
      const draft=drafts.get(composeKey())||getCompose();persist(composeKey(),draft);
      const body={projectId:selected,entityId:selectedEntity,recipe:recipes[page],prompt:draft.prompt,sourceRevisionIds:page==='style'?[]:[draft.sourceRevisionId],settings:{count:Number(draft.count),...(draft.ratio?{ratio:draft.ratio}:{})},expectedSelectionRevision:session.selection.revision};
      return perform(async()=>{prepared=await api.request('/tasks/prepare',{method:'POST',body,idempotencyKey:draft.prepareKey});if(!prepared.confirmation){announce(prepared.task?.error?.message||'准备未完成，请查看任务记录。');prepared=null;}else announce('任务准备记录已保存，请核对原账号、空间和费用。');events.dispatchEvent(new CustomEvent('tasks:changed',{detail:{projectId:selected}}));await load();});
    }
  }
  async function onClick(event) {
    const button=event.target.closest('button,a');if(!button||button.disabled)return;
    if(button.hasAttribute('data-wf-download')){event.preventDefault();const url=new URL(button.href);const relative=url.pathname.slice(apiBase.length);return perform(async()=>{const blob=await api.request(relative,{responseType:'blob'});const link=doc.createElement('a');const objectUrl=URL.createObjectURL(blob);link.href=objectUrl;link.download='asset-lab-approved-assets.zip';link.hidden=true;doc.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),60000);announce('交付包已交给浏览器下载。');});}
    if(button.dataset.wfNav)return navigate(button.dataset.wfNav);
    if(button.dataset.wfEntity){selectedEntity=button.dataset.wfEntity;persist('selectedEntity',selectedEntity);return navigate(button.dataset.wfStage);}
    if(button.dataset.wfArchive){selectedEntity=button.dataset.wfArchive;persist('selectedEntity',selectedEntity);return navigate('review');}
    if(button.dataset.wfReview)return openReview(button.dataset.wfReview,button);
    if(button.dataset.wfRepair)return repair(button.dataset.wfRepair);
    if(button.dataset.wfRemove!==undefined){const draft=drafts.get(planKey());if(draft){draft.entities.splice(Number(button.dataset.wfRemove),1);persist(planKey(),draft);render();}return;}
    if(button.dataset.wfCancel){const task=tasks.find(t=>t.id===button.dataset.wfCancel);if(!task||task.submissionAttempted)return;return perform(async()=>{await api.request(`/tasks/${encodeURIComponent(task.id)}/cancel`,{method:'POST',body:{expectedVersion:task.version}});prepared=null;const draft=drafts.get(composeKey());if(draft)persist(composeKey(),{...draft,prepareKey:key()});announce('未提交的准备记录已取消；原记录仍保留。');await load();});}
    if(button.dataset.wfRecover){const task=tasks.find(t=>t.id===button.dataset.wfRecover);if(!task)return;return perform(async()=>{await api.request(`/tasks/${encodeURIComponent(task.id)}/recover`,{method:'POST',body:{expectedVersion:task.version}});announce('已查询原任务；没有重新发起生成。');await load();});}
    if(button.dataset.wfAnalysisGroup){const group=root.querySelector('#analysis-'+button.dataset.wfAnalysisGroup);if(group){group.open=true;group.scrollIntoView({behavior:'smooth',block:'start'});}return;}
    if(button.dataset.wfSource){const source=root.querySelector(`[data-wf-script="${scripts.at(-1)?.id}"]`);if(source){source.open=true;source.querySelectorAll('[data-wf-line]').forEach(line=>line.classList.toggle('wf-source-active',Number(line.dataset.wfLine)>=Number(button.dataset.wfSource)&&Number(line.dataset.wfLine)<=Number(button.dataset.wfSourceEnd)));source.querySelector('.wf-source-active')?.scrollIntoView({behavior:'smooth',block:'center'});}return;}
    const action=button.dataset.wfAction;
    if(action==='continue')return continueFlow();
    if(action==='analyze'){
      if(!root.querySelector('[data-wf-analysis-spend]')?.checked){announce('请先确认本次两步 AI 分析使用当前账号积分。');return;}
      const script=scripts.at(-1);if(!script)return;
      const requestName=`analysis:${script.id}:${session.selection.revision}:${analysis?.id||'first'}`;
      const idempotencyKey=drafts.get(requestName)||key();persist(requestName,idempotencyKey);
      return perform(async()=>{analysis=await api.request(`/projects/${encodeURIComponent(selected)}/scripts/${encodeURIComponent(script.id)}/analyze`,{method:'POST',body:{idempotencyKey,expectedSelectionRevision:session.selection.revision,confirmSpend:true,reanalyze:Boolean(analysis)}});analysisError='';announce('AI 分析请求已保存，状态将在这里持续更新。');});
    }
    if(action==='analysis-refresh'&&analysis)return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/refresh`,{method:'POST',body:{}});analysisError='';});
    if(action==='analysis-plan'&&analysis?.status==='ready'){
      if(!root.querySelector('[data-wf-analysis-reviewed]')?.checked){announce('请先对照原文核对分析结果和待确认问题。');return;}
      return perform(async()=>{const candidate=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/plan`);persist(planKey(),{expectedVersion:candidate.expectedVersion,entities:candidate.entities,stylePrompt:candidate.stylePrompt});editing=true;page='plan';announce(candidate.hasExistingPlan?'AI 草稿已打开；保存时将更新当前资产清单，请核对原有条目是否需要保留。':'AI 角色与地点草稿已打开，请核对设定和视觉风格后保存。');});
    }
    if(action==='connect'){events.dispatchEvent(new CustomEvent('workflow:connect'));return;}
    if(action==='refresh')return perform(()=>load());
    if(action==='new-project'){analysis=null;analysisError='';creating=true;project=null;selected='';selectedEntity='';plan={version:0,entities:[],stylePrompt:''};assets=[];scripts=[];tasks=[];bundles=[];coverage={total:0,ready:0,complete:false};reviewId=null;prepared=null;render();root.querySelector('input[name=name]')?.focus();return;}
    if(action==='edit-plan'){editing=true;if(!drafts.get(planKey()))persist(planKey(),{expectedVersion:plan.version,entities:plan.entities.map(cleanEntity),stylePrompt:plan.stylePrompt});render();return;}
    if(action==='add-entity'){const draft=drafts.get(planKey())||{expectedVersion:plan.version,entities:[],stylePrompt:plan.stylePrompt};if(draft.entities.length>=300){announce('一个项目最多 300 项资产。');return;}draft.entities.push({id:'ent_'+key().replaceAll('-',''),category:'character',name:'',description:'',variant:'',origin:'manual',quote:'',scriptId:''});persist(planKey(),draft);render();root.querySelector('[data-wf-row]:last-of-type input[data-field=name]')?.focus();return;}
    if(action==='close-review'){reviewId=null;render();focusedBeforeReview?.isConnected&&focusedBeforeReview.focus();return;}
    if(action==='approve')return decide('approved');
    if(action==='reject')return decide('changes_requested');
    if(action==='close-confirmation'){prepared=null;render();return;}
    if(action==='submit-task'&&prepared&&session.features?.imageGeneration===true){const target=prepared;return perform(async()=>{await api.request(`/tasks/${encodeURIComponent(target.task.id)}/submit`,{method:'POST',body:{expectedVersion:target.task.version,confirmationToken:target.confirmation.token},idempotencyKey:target.submitKey||(target.submitKey=key())});prepared=null;persist(`flow:${selected}`,true);announce('已发送提交请求，最终状态以任务记录为准。');await load();});}
    if(action==='archive')return perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/bundles`,{method:'POST',body:{expectedVersion:project.version}});announce('本次确认的交付包已归档。');await load();});
  }
  function imageFailure(event) {
    const img=event.target;if(img.tagName!=='IMG')return;
    img.hidden=true;
    if(!img.nextElementSibling?.classList.contains('wf-image-error-note')) {
      const note=doc.createElement('span');note.className='wf-image-error-note';
      note.textContent='缩略图暂未加载，点击查看原图或刷新状态';img.after(note);
    }
  }
  root.addEventListener('error',imageFailure,true);
  doc.getElementById('warehouseList')?.addEventListener('error',imageFailure,true);
  listeners.push(()=>{root.removeEventListener('error',imageFailure,true);doc.getElementById('warehouseList')?.removeEventListener('error',imageFailure,true);});
  listen(root,'input',onInput);listen(root,'submit',onSubmit);listen(root,'click',onClick);
  listen(root,'change',async event=>{
    const target=event.target;
    if(target.matches('[data-wf-project]'))return switchProject(target.value);
    if(target.matches('[data-wf-upload]'))return upload(target.files?.[0]);
    if(target.matches('[data-wf-quick-upload]'))return startFromFile(target.files?.[0]);
    if(target.matches('[data-wf-entity-select]')){selectedEntity=target.value;persist('selectedEntity',selectedEntity);render();}
    if(target.matches('[data-wf-review-entity]')){selectedEntity=target.value;reviewId=null;render();}
    if(target.name==='sourceRevisionId'){const form=target.closest('form');persist(composeKey(),captureCompose(form));render();}
  });
  listen(doc.getElementById('warehouseList'),'click',onClick);
  listen(doc.getElementById('scriptSelect'),'change',e=>switchProject(e.target.value));
  listen(doc.getElementById('warehouseSearch'),'input',e=>{search=e.target.value;renderLibrary();});
  listen(doc.getElementById('warehouseFilters'),'click',e=>{const b=e.target.closest('[data-warehouse-filter]');if(!b)return;filter=b.dataset.warehouseFilter;renderLibrary();});
  listen(doc.getElementById('importScript'),'click',()=>{if(!selected){announce('请先创建项目。');return;}doc.getElementById('scriptFile')?.click();});
  listen(doc.getElementById('scriptFile'),'change',e=>{upload(e.target.files?.[0]);e.target.value='';});
  listen(events,'shell:action',e=>{if(e.detail?.action!=='manual-plan')return;e.preventDefault();if(project){editing=true;navigate('plan');}else{render();root.querySelector('input[name=name]')?.focus();}root.scrollIntoView({behavior:'smooth',block:'start'});});
  listen(events,'workflow:navigate',e=>navigate(e.detail?.page||'plan'));
  listen(events,'workflow:manual-plan',()=>{if(project){editing=true;navigate('plan');}else{render();root.querySelector('input[name=name]')?.focus();}});
  listen(events,'selection:changed',e=>{session={...session,selection:e.detail?.selection||e.detail};render();});
  listen(events,'session:changed',e=>{
    const next=e.detail?.session?.tenant?e.detail.session:e.detail;
    if(next?.tenant?.id&&next.tenant.id!==session.tenant.id){unmount();root.textContent='本站会话已改变，请重新载入该客户的工作区。';events.dispatchEvent(new CustomEvent('workflow:remount-required'));return;}
    if(next?.tenant)session=next;render();
  });
  listen(events,'tasks:changed',()=>{clearTimeout(timer);timer=setTimeout(()=>{if(alive&&!busy)load();},150);});
  listen(events,'workflow:flush-drafts',e=>{const pending=flushDrafts();if(typeof e.detail?.waitUntil==='function')e.detail.waitUntil(pending);else pending.catch(err=>{error=err.message;render();});});
  listen(doc.defaultView,'beforeunload',e=>{try{drafts.flush();}catch{e.preventDefault();e.returnValue='';}if(busy){e.preventDefault();e.returnValue='';}});
  function unmount(){alive=false;requestSerial++;clearTimeout(timer);clearTimeout(flowTimer);clearInterval(progressTimer);clearInterval(pollingTimer);delete doc.body.dataset.workflowMounted;listeners.forEach(remove=>remove());stylesheet.remove();root.replaceChildren();for(const id of ['warehouseList','review-summary-root'])doc.getElementById(id)?.replaceChildren();const chooser=doc.getElementById('scriptSelect');if(chooser)chooser.replaceChildren();}
  const ready=load({initial:true});
  return {unmount,ready,refresh:load,flushDrafts,hasUnsavedChanges:dirty,getState:()=>({projectId:selected,page,dirty:dirty(),busy,saveError})};
}
