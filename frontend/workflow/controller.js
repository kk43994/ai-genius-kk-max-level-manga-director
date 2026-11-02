import {canAutoCollect, nextCollection, collectionDelay, collectionOwnerKey, needsAssetRefresh} from './collection.js';
import {promptPanel, promptProcessing, usablePrompt, promptIssue} from './prompts.js';
import {productionPanel, productionRunning, createPreview, referenceCards} from './production.js';
import {returnedResult, reviewDraft, setReviewValue, valueAt, textLines} from './production-editor.js';
import {assetToken,referenceLabel,readableText,storedText,linkedText,referencePicker,bindReference,removeReference,appendManualProp} from './production-references.js';
import {generationContext,generationGallery,generationInspector} from './production-generation.js';
import {sourceImagePicker} from './image-choices.js';
import {NANO_CLEANUP_PROMPT,selectedNanoModel,nanoCleanupSource} from './nano-cleanup.js';
import {versionPicker,versionTarget} from './version-picker.js';
import {extraReferences,referencePrompt,libraryPanel,referencePool,chooseExtraReference} from './image-references.js';
import {batchSize,parallelGroups,missingStoryboardShots,repairStoryboardShots} from './generation-batch.js';
import {selectedImageModel,collectImageSettings} from './image-models.js';
import {promptRecipePanel} from './prompt-recipes.js';
import {canvasBatchPanel} from './canvas-batch.js';
import {artStudiesPanel,artModel,studyPrompt,resolvedArtSamples} from './art-studies.js';
import {analysisMaterials} from './canvas-template.js';
import {creatorDesk,directionForm,styleSummary} from './creator-desk.js';
import {overviewShots} from './storyboard-overview.js';
import {storyCards} from './story-cards.js';
import {mountStoryCanvas} from './story-canvas.js';
import {mountCanvas} from './production-canvas.js';
import {splitShot,addShot,removeBlankShot,numberShots} from './shot-structure.js';
import {analysisDraft} from './analysis-edit.js';
import {analysisPanel, sourceView} from './analysis.js';
import {operationLabel, elapsedLabel, taskProgress, reviewProgress} from './progress.js';
import {buildCustomerArchives} from '../asset-lab-archives.js';
import {nextAction,prepareIdentity} from './guide.js';
import {DraftStore, escapeHTML as esc, localBase, assetURL, categories, stages, stageLabels, states, recipes, recipeLabels, revisionLabel,
  approvedSources, belongsToSelection, resolveRefineSource} from './model.js';

const clone = value => JSON.parse(JSON.stringify(value));
const key = () => crypto.randomUUID();
const label = value => states[value] || value;
const tag = (state, text = label(state)) => `<span class="wf-tag ${esc(state)}">${esc(text)}</span>`;
const normalizePage = page => ({script:'plan',clean:'refine',export:'plan',delivery:'plan',overview:'plan'}[page] || page);
const entityFields = ['id','category','name','description','origin','quote','scriptId','variant'];
const cleanEntity = entity => Object.fromEntries(entityFields.filter(k => entity[k] !== undefined).map(k => [k,entity[k]]));

export function mount({root, api, events = new EventTarget(), session, apiBase = '/api/v1', publicBasePath = '/', storage = globalThis.localStorage, layoutStorage = storage}) {
  if (!root || !api?.request || !session?.tenant?.id) throw new Error('工作流需要挂载节点、API 客户端与本站会话。');
  apiBase = localBase(apiBase, '/api/v1'); publicBasePath = localBase(publicBasePath, '/');
  const doc = root.ownerDocument;
  doc.body.dataset.workflowMounted = 'true';
  const drafts = new DraftStore(storage, session.tenant.id, apiBase);
  const listeners = [];
  let operation = null, operationSerial = 0, progressTimer, pollingTimer, lastChecked = null, polling = false;
  const transport = api;
  api = {...transport, request: async (url, options = {}) => {
    const {background = false, ...requestOptions} = options;
    const writing = (options.method || 'GET') !== 'GET';
    const tracked = !background && (writing || (!operation && (loading || busy)));
    const serial = tracked ? ++operationSerial : null;
    if (tracked) {operation = {serial, label:options.responseType==='blob'?'正在下载交付包':operationLabel(url,options.method), startedAt:Date.now()}; renderProgress();}
    try {return await transport.request(url, requestOptions);}
    finally {if (operation?.serial === serial) {operation = null; renderProgress();}}
  }};
  let alive = true, busy = false, loading = false, requestSerial = 0, timer, flowTimer, error = '', notice = '';
  let projects = [], project = null, plan = {version:0,entities:[],stylePrompt:''}, assets = [], bundles = [], tasks = [], scripts = [];
  let analysis = null, analysisError = '', promptJobs = [], promptError = '';
  const entityPrompt = () => {const entityId=currentEntity()?.id,viewId=drafts.get(`prompt-view:${selected}:${entityId}`);return promptJobs.find(job=>job.entityId===entityId&&job.id===viewId)||promptJobs.find(job=>job.entityId===entityId);};
  let production = null, productionError = '';
  let returnStoryShot = null, storyRefreshPending = false;
  let remoteLibrary={open:false},librarySerial=0,rerollId=null,rerollMode='reroll';
  const rerollKey=()=>`boardgen:${rerollMode==='nano'?'nano-cleanup':'reroll'}:${rerollId}`;
  let imageCatalog=null,imageContracts={},imageModelsLoading=false,imageModelsError='',imageCatalogOwner='',imageModelSerial=0;
  const boardViews=new Map(),canvas=mountCanvas(root),storyCanvas=mountStoryCanvas(root,{storage:layoutStorage,storageKey:`asset-lab:story-canvas:v2:${encodeURIComponent(apiBase)}:${encodeURIComponent(session.tenant.id)}`});
  let referenceCursor=null, directorDrag=null, suppressDirectorClickUntil=0;
  const currentProduction=()=>drafts.get(`production:review:${production?.id}`)?.result||returnedResult(production);
  const artBundleKey=()=>`art-bundle:${selected}`;
  const artGenerationDraft=()=>({modelId:artModel(canvasDrawer?.role,imageCatalog)?.id||selectedImageModel({},imageCatalog).id,...(drafts.get(boardGenerationKey())||{})});
  const boardGenerationKey=()=>canvasDrawer?.type==='batch'?`boardgen:batch:${production?.id}`:canvasDrawer?.type==='art'?`boardgen:art:${selected}:${canvasDrawer.role}`:`boardgen:identity-v2:${boardView().characterLayer||'master'}:${production?.id}:${boardView().kind}:${boardView().index}:${boardView().state||0}:${boardView().stage}`;
  const phase=()=>canvasDrawer?.phase||page;
  const boardView=()=>{const v=boardViews.get(production?.id)||{},page=phase();return stages.includes(page)?{...v,kind:'assets',index:v.kind==='shots'?0:(v.index||0),state:v.state||0,stage:page==='style'?'style':page==='refine'?'refine':v.stage==='refine'?'refine':'asset'}:v;};
  function updateBoard(patch){if(!production)return;const previous=boardView();if(['kind','index','state','characterLayer','stage'].some(k=>Object.hasOwn(patch,k)&&patch[k]!==previous[k]))reviewId=null;boardViews.set(production.id,{...previous,...patch});render();const chosen=selectedImageModel(drafts.get(boardGenerationKey())||{},imageCatalog);if(!imageModelsLoading&&!imageContracts[chosen.id])void loadImageModels();}
  const preview = createPreview({root,getContext:()=>({job:production,assets,coverage,selection:session.selection,apiBase}),onStatus:message=>announce(message)});
  let collecting = false;
  const collectionAttempts = new Map();
  let coverage = {total:0, ready:0, complete:false}, capabilities = {scriptAnalysis:false}, taskError = '';
  let selected = drafts.get('quick-start')?.text ? '' : drafts.get('selectedProject') || '', page = normalizePage(drafts.get('page') || 'plan');
  let canvasDrawer=stages.includes(page)?{type:'production',phase:page}:page==='production'?{type:'production',phase:'production'}:null, drawerTrigger=null;
  if(canvasDrawer)page='plan';
  let selectedEntity = drafts.get('selectedEntity') || '', editing = false, reviewId = null, prepared = null, submittingBatch = false, reviewing = false, recoveringTask = false;
  let filter = 'all', search = '', saveError = '', creating = Boolean(drafts.get('quick-start')?.text), focusedBeforeReview;
  const status = () => root.querySelector('[data-wf-status]');
  const listen = (target, event, handler) => { if (!target) return; target.addEventListener(event,handler); listeners.push(() => target.removeEventListener(event,handler)); };
  const announce = message => { notice = message; if (status() && !error && !saveError) status().textContent = message; };
  const currentAsset = () => assets.find(a => a.entityId === selectedEntity && a.active);
  const currentEntity = () => plan.entities.find(e => e.id === selectedEntity) || plan.entities[0];
  const planKey = () => `plan:${selected}`;
  const composeKey = () => `compose:${selected}:${selectedEntity}:${page}`;
  const image = (assetId, revisionId, thumb = true) => esc(assetURL(apiBase,assetId,revisionId,thumb));
  const path = relative => apiBase + relative;
  const dirty = () => Object.keys(drafts.data).some(k => k.startsWith('plan:') || k.startsWith('compose:') || k.startsWith('review:') || k.startsWith('production:edits:') || k.startsWith('production:review:') || k.startsWith('analysis:review:') || k.startsWith('boardgen:') || k.startsWith('art-direction:') || k.startsWith('art-bundle:') || k.startsWith('prompt-recipe:') || (k==='quick-start'&&drafts.get(k)?.text));
  const guide = () => scripts.length && !plan.entities.length && !drafts.get(planKey()) ? {kind:'analysis',title:analysis?.status==='ready'?'核对 AI 分析，建立资产清单':'先完成 AI 剧本分析',detail:analysis?.message||'用 AI 理解角色、场景、时间、地点、事件与台词。'} : nextAction({project, plan:{...plan,needsReview:plan.needsReview||Boolean(drafts.get(planKey()))}, assets, tasks, bundles, selection:session.selection, taskError, styleCount:session.features?.imageGeneration ? 4 : 1});


  const stylesheet = doc.createElement('link');
  stylesheet.rel = 'stylesheet'; stylesheet.href = new URL('./workflow.css', import.meta.url).href;
  // Measuring unstyled cards creates huge false heights and saves a broken canvas layout.
  const stylesheetReady=new Promise(resolve=>{stylesheet.addEventListener('load',resolve,{once:true});stylesheet.addEventListener('error',resolve,{once:true});});
  stylesheet.dataset.workflowStyle = 'true'; doc.head.append(stylesheet);

  function persist(name, value) {
    try { drafts.set(name, value); saveError = ''; }
    catch (e) { saveError = '本机草稿保存失败。请先保存到项目，再刷新或升级页面。'; announce(saveError); }
    events.dispatchEvent(new CustomEvent('workflow:dirty', {detail:{dirty:dirty(), savedLocally:!saveError}}));
  }
  function removeDraft(name) { try { drafts.delete(name); saveError = ''; } catch { saveError = '本机草稿更新失败。'; } }
  async function flushDrafts() {
    if (busy||reviewing) throw new Error('正在保存、导入或审核，请等待当前操作完成再刷新。');
    drafts.flush(); saveError = ''; return {saved:true, dirty:dirty(), scope:'local-tenant-drafts'};
  }
  function emitProject() { events.dispatchEvent(new CustomEvent('project:changed',{detail:{projectId:selected, project, coverage}})); events.dispatchEvent(new CustomEvent('shell:view',{detail:{workspaceState:project?'ready':'empty',projectName:project?.name||'开始创作'}})); }
  function renderStatus() { return `<div data-wf-status class="wf-status ${error || saveError ? 'wf-note wf-error' : 'wf-muted'}" role="status" aria-live="polite">${esc(error || saveError || notice)}${error?'<div class="wf-actions"><button data-wf-action="refresh">刷新状态</button><button data-wf-action="connect">检查账号与空间</button></div>':''}</div>`; }
  function productionDraftControls() {
    if(!production||page!=='production')return '';
    const parked=drafts.get(`production:parked:${production.id}`),editing=drafts.get(`production:review:${production.id}`)||drafts.get(`production:edits:${production.id}`);
    return parked?`<p class="wf-note">已暂存一份镜头草稿；当前查看已保存方案。<button data-wf-action="production-review-resume" ${busy||editing?'disabled':''}>继续编辑暂存草稿</button></p>`:editing?`<p class="wf-note">镜头修改尚未提交。<button data-wf-action="production-review-park" ${busy?'disabled':''}>暂存草稿，查看已保存方案</button></p>`:'';
  }
  function options(values, selectedValue) { return values.map(([value,text]) => `<option value="${esc(value)}" ${value === selectedValue ? 'selected' : ''}>${esc(text)}</option>`).join(''); }
  function nav() {
    const entries = [['plan','制作画布'],['review','任务与版本']];
    return `<nav class="wf-tabs" aria-label="资产制作步骤">${entries.map(([id,title]) => `<button type="button" data-wf-nav="${id}" ${(page === id||(page==='refine'&&id==='asset')||(page==='review'&&id==='plan')) ? 'aria-current="step"' : ''}>${title}</button>`).join('')}</nav>`;
  }
  function stepNavigation() { return nav(); }
  function empty(title, detail) { return `<div class="wf-empty"><h3>${esc(title)}</h3><p class="wf-muted">${esc(detail)}</p></div>`; }
  let renderedViewKey = '';
  function disclosureStates() {
    const counts=new Map();
    return [...root.querySelectorAll('details')].map(node=>{
      const title=node.querySelector(':scope > summary')?.textContent?.trim()||'';
      const index=counts.get(title)||0;counts.set(title,index+1);
      return {node,key:JSON.stringify([title,index])};
    });
  }
  function render() {
    if (!alive) return;
    if(rerollId!==reviewId)rerollId=null;
    const view=boardView(),viewKey=JSON.stringify([selected,page,selectedEntity,production?.id,view.kind,view.index,view.state,view.stage,view.characterLayer,view.inspector,canvasDrawer]);
    const openStates=new Map(renderedViewKey===viewKey?disclosureStates().map(({node,key})=>[key,node.open]):[]);
    preview.reset();
    doc.body.dataset.workflowPage=page;
    const title = project ? project.name : projects.length ? '开始一个新项目' : '开始你的第一个项目';
    const chooser = projects.length ? `<label><span class="sr-only">当前项目</span><select data-wf-project>${!selected?'<option value="">选择已有项目</option>':''}${options(projects.map(p=>[p.id,p.name]),selected)}</select></label>` : '';
    root.innerHTML = `<section class="wf" aria-label="资产工作流"><div class="wf-toolbar"><div><span class="wf-muted">从一份剧本，到一套可用资产</span><h2>${esc(title)}</h2></div><div class="wf-actions">${chooser}<button type="button" data-wf-action="new-project" ${busy?'disabled':''}>＋ 新项目</button><button type="button" data-wf-action="refresh" ${busy ? 'disabled' : ''}>刷新状态</button></div></div>${renderStatus()}${productionDraftControls()}<div data-wf-operation></div>${project ? stepNavigation() : ''}${loading ? '<p class="wf-muted" role="status">正在读取已保存项目…</p>' : !project ? createView() : page === 'plan' ? planView() : page === 'production' ? productionView() : stages.includes(page) ? creatorView() : page === 'review' ? reviewView()+tasksView(selectedEntity) : planView()}${canvasPanelView()}${libraryPanel(remoteLibrary)}${reviewId ? reviewDetail() : ''}${prepared ? confirmationView() : ''}</section>`;
    for(const {node,key} of disclosureStates())if(openStates.has(key))node.open=openStates.get(key);
    renderedViewKey=viewKey;
    renderProgress(); renderLibrary(); canvas.refresh(); storyCanvas.refresh();
    if(page==='plan'&&returnStoryShot){storyCanvas.locateShot(returnStoryShot);returnStoryShot=null;}
    const saveStatus = doc.getElementById('saveStatus'); if (saveStatus) saveStatus.textContent = saveError ? '草稿保存失败' : busy ? '处理中' : dirty() ? '编辑草稿已在本机保存' : '项目已同步';
    const titleNode = doc.getElementById('workspace-title'); if (titleNode) titleNode.textContent = project?.name || '开始创作';
    const countNode = doc.getElementById('reviewCount'); if (countNode) countNode.textContent = assets.flatMap(a=>a.revisions).filter(r=>r.review==='pending' && r.status==='ready').length;
    if (busy) root.querySelectorAll('form button').forEach(b=>b.disabled=true);
    if (reviewing || (busy && !submittingBatch && !recoveringTask)) root.querySelectorAll('[data-wf-action="approve"], [data-wf-action="reject"]').forEach(b=>b.disabled=true);
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
    if(alive&&!loading&&!polling&&project&&doc.visibilityState!=='hidden'&&(['preparing','submitting','running','reviewing'].includes(analysis?.status)||promptJobs.some(promptProcessing)||productionRunning(production)||collecting||busy||needsAssetRefresh(tasks,assets)||tasks.some(t=>canAutoCollect(t)||['preparing','submitting','queued','submitted','running','downloading'].includes(t.status))))void pollTasks();
  },5000);
  function createView() {
    const draft = drafts.get('new-project') || {name:'',description:''};
    const quick = drafts.get('quick-start') || {text:''};
    return `<section class="wf-panel wf-start"><p class="wf-eyebrow">ASSET LAB / 从剧本开始</p><h3>把故事放进来，<br>接下来的步骤交给工作台。</h3><p class="wf-muted">保存剧本后由 AI 分析故事，再由你选定风格、确认资产和编排镜头。</p><form data-wf-form="quick-start" class="wf-compose"><label>剧本正文<textarea name="text" rows="10" maxlength="250000" required placeholder="粘贴你的剧本，例如：&#10;《山间来信》&#10;角色：林舟、阿宁&#10;场景：旧书店&#10;道具：信封&#10;林舟：这封信，是留给你的。">${esc(quick.text)}</textarea></label><div class="wf-actions"><button class="primary" type="submit">开始制作 →</button><label class="wf-link">或导入剧本文件<input data-wf-quick-upload type="file" accept=".txt,.md,.docx" hidden></label><span class="wf-muted">TXT / MD / DOCX · 最大 8 MiB</span></div></form><ol class="wf-roadmap"><li>分析剧本</li><li>确定风格</li><li>制作资产</li><li>导演编排</li><li>审核交付</li></ol><p class="wf-muted">原文保存后点击 AI 分析，由 LibTV 文本模型提取六类信息并复核。分析和图片制作需要 LibTV 创作授权及可用积分。</p><details><summary>手工创建项目</summary><form data-wf-form="create" class="wf-compose"><label>项目名称<input name="name" maxlength="120" required value="${esc(draft.name)}"></label><label>项目说明（可选）<textarea name="description" maxlength="4000">${esc(draft.description)}</textarea></label><div><button type="submit">创建空项目</button></div></form></details></section>`;
  }
  function guideView() {
    const next = guide(), labels = {prompt:'编写 / 核对提示词',analysis:'查看 AI 分析与下一步',plan:plan.entities.length?'确认清单并继续':'补充资产清单',connect:'连接 / 选择账号',review:'查看图片并审核',prepare:'一键继续制作',confirm:'核对并继续',recover:'查询原任务',archive:'整理交付包',download:'下载全部资产',import:'导入剧本'};
    const unavailable = ['prepare','confirm'].includes(next.kind) && session.features?.imageGeneration !== true;
    const {done,total} = reviewProgress(plan.entities,assets,session.selection,belongsToSelection);
    return `<section class="wf-panel wf-guide" aria-label="一键制作进度"><div><p class="wf-eyebrow">${unavailable?'制作服务待就绪':'接下来只需这一步'}</p><h3>${esc(next.title)}</h3><p class="wf-muted">${esc(next.detail)}</p>${total?`<p class="wf-muted">${done} / ${total} 个制作环节已审核</p><progress class="wf-overall" value="${done}" max="${total}" aria-label="制作环节审核进度"></progress>`:''}${unavailable?'<p class="wf-note">这个版本的图片生成服务尚未开放。剧本和清单已保存，服务接通后从这里继续。</p>':''}</div><div class="wf-actions">${next.kind==='download'?`<a data-wf-download class="wf-link primary" href="${esc(path(`/projects/${encodeURIComponent(selected)}/bundles/${encodeURIComponent(next.bundle.id)}/content`))}">下载全部资产 ↓</a>`:next.kind==='blocked'?'<button data-wf-nav="review">查看任务与素材</button>':`<button class="primary" data-wf-action="continue" ${busy||unavailable?'disabled':''}>${labels[next.kind]||'继续'}</button>${unavailable?'<button data-wf-action="connect">查看已连接账号</button><button data-wf-action="refresh">检查服务状态</button>':''}`}${next.kind==='recover'?`<span class="wf-muted">${canAutoCollect(next.task)?'页面打开时自动收取':'点击查询原任务继续，不会重新生成'}</span>`:''}</div></section>`;
  }
  function planView() {
    const draft = drafts.get(planKey());
    const warnings = [...new Set(scripts.flatMap(s=>s.analysis?.warnings||[]))];
    const header = `<section class="wf-panel story-source-bar"><div class="wf-actions"><label class="wf-link">导入剧本<input data-wf-upload type="file" accept=".txt,.md,.docx" hidden></label><button type="button" data-wf-action="edit-plan">${plan.entities.length ? '编辑资产清单' : '手工填写清单'}</button></div>${warnings.length?`<div class="wf-note">${warnings.map(w=>esc(w)).join('<br>')}</div>`:''}${scripts.map(sourceView).join('')}</section>${analysisView()}`;
    if (editing || draft) return header + planEditor(draft || {expectedVersion:plan.version, entities:plan.entities.map(cleanEntity),stylePrompt:plan.stylePrompt});
    return header + (analysis?.status==='ready'?`<section class="wf-panel"><div class="wf-actions"><button data-wf-action="open-production-plan">${production&&returnedResult(production)?'修改制作清单与镜头':'细化物料与分镜'}</button>${production&&returnedResult(production)?'<button data-canvas-preview>图板预演</button>':''}</div></section>`:'') + (production||assets.length||bundles.length?deliveryView():'') + (plan.entities.length?`<details><summary>已有清单与历史档案</summary><div data-wf-archives>${archivesView()}</div></details>`:'');
  }
  function archivesView() {
    const archives = buildCustomerArchives(assets,plan);
    return (archives.length ? `<div class="wf-section-title"><h3>本项目档案</h3><span class="wf-muted">${archives.length} 项 · 未生成的条目也保留在这里</span></div><div class="wf-grid">${archives.map(a=>archiveCard(a)).join('')}</div>` : empty('等待 AI 分析结果','分析完成后核对六类信息，再建立角色与地点资产清单。'));
  }
  function productionView(panel=false) { return productionPanel({script:scripts.at(-1),analysis,job:production,enabled:capabilities.scriptAnalysis,connected:Boolean(session.selection?.providerAccountId&&session.selection?.spaceId),busy,error:productionError||error||saveError,models:capabilities.analysis?.models||[],modelId:drafts.get('text-model')||capabilities.analysis?.defaultModelId,assets,coverage,selection:session.selection,apiBase,draft:drafts.get(`production:edits:${production?.id}`),review:drafts.get(`production:review:${production?.id}`),view:panel?{kind:'shots',index:0,inspector:'shots',...boardView()}:boardView(),tasks,generationDraft:drafts.get(boardGenerationKey())||{},phase:panel?'canvas':page==='production'?'director':'plan',project,imageCatalog,imageContracts,imageModelsLoading,imageModelsError}); }
  function creatorView(){
    if(!production||!returnedResult(production))return `<section class="wf-panel"><h3>先整理本剧的制作清单</h3><button data-wf-nav="plan">返回剧情总览</button></section>`+(plan.entities.length?`<details><summary>继续使用已有档案制作</summary>${composeView()}</details>`:'');
    return creatorDesk({page:page==='refine'?'asset':page,project,result:currentProduction(),job:production,assets,selection:session.selection,view:boardView(),apiBase,busy,tasks,
      review:drafts.get(`production:review:${production.id}`),draft:drafts.get(`production:edits:${production.id}`),generationDraft:drafts.get(boardGenerationKey())||{},directionDraft:drafts.get(`art-direction:${selected}`),imageCatalog,imageContracts,imageModelsLoading,imageModelsError});
  }
  function openCanvasPanel(value,trigger){
    drawerTrigger=trigger||doc.activeElement;canvasDrawer=value;page='plan';persist('page',page);render();
    root.querySelector('[data-canvas-drawer]')?.focus({preventScroll:true});
    if(value.type==='production'||value.type==='batch'||value.type==='art'&&value.role!=='standard')void loadImageModels();
  }
  function closeCanvasPanel(){canvasDrawer=null;render();if(drawerTrigger?.isConnected)drawerTrigger.focus({preventScroll:true});else root.querySelector('[data-story-viewport]')?.focus({preventScroll:true});}
  function canvasPanelView(){
    if(page!=='plan'||!canvasDrawer)return '';
    const v=boardView(),result=currentProduction();let title='制作',body='';
    if(canvasDrawer.type==='recipes'){title='提示词规范';body=promptRecipePanel({revision:assets.flatMap(a=>a.revisions).find(r=>r.id===canvasDrawer.revisionId),project,assets,apiBase,busy,draft:drafts.get(`prompt-recipe:${selected}:${canvasDrawer.revisionId}`)||{}});
    }else if(canvasDrawer.type==='batch'&&result){title='批量补分镜图';body=canvasBatchPanel({job:production,result:returnedResult(production),assets,tasks,selection:session.selection,draft:drafts.get(boardGenerationKey())||{},catalog:imageCatalog,contracts:imageContracts,busy,loading:imageModelsLoading,error:imageModelsError});
    }else if(canvasDrawer.type==='art'){title='全剧美术试做';body=artStudiesPanel({role:canvasDrawer.role,project,assets,apiBase,selection:session.selection,busy,draft:artGenerationDraft(),bundle:drafts.get(artBundleKey())||{},catalog:imageCatalog,contracts:imageContracts,loading:imageModelsLoading,error:imageModelsError,analysis:analysis?.result||analysis?.draftResult,tasks});
    }else if(canvasDrawer.type==='material'){
      const item=analysisMaterials(analysis?.result||analysis?.draftResult||{}).find(r=>r.id===canvasDrawer.id);
      title=item?.name||'关键道具';body=`<p>${esc(item?.description||'制作方案返回后，可补充剧本中的关键道具。')}</p><p class="wf-muted">先确认全剧美术标准，再细化物料与镜头。这里保留剧本分析中的设定。</p><button data-canvas-art="standard">全剧美术试做</button><details><summary>细化物料与分镜</summary>${productionView()}</details>`;
    }else if(!result){title='细化物料与分镜';body=productionView();
    }else if(stages.includes(phase())){
      title=result.assets[v.index||0]?.name||'选择物料';
      const opts={project,result,job:production,assets,selection:session.selection,view:v,apiBase,busy,tasks,phase:phase()==='style'?'style':'asset',review:drafts.get(`production:review:${production.id}`),generationDraft:drafts.get(boardGenerationKey())||{},directionDraft:drafts.get(`art-direction:${selected}`),imageCatalog,imageContracts,imageModelsLoading,imageModelsError,canvasMode:true};
      body=`<label>当前物料<select data-canvas-asset>${result.assets.map((a,i)=>`<option value="${i}" ${i===(v.index||0)?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label>${phase()==='style'&&project.artDirection?styleSummary(project,apiBase):''}${generationInspector(opts)}${phase()==='style'?`<button type="button" data-creator-go-stage="asset">去生成${result.assets[v.index||0]?.category==='character'?'人物主多视图':result.assets[v.index||0]?.category==='scene'?'场景主多视图':'道具白底图'} →</button>`:''}`;
    }else {title=v.inspector==='preview'?'图板预演':v.inspector==='issues'?'核对原文与关联':`镜头 ${String((v.index||0)+1).padStart(3,'0')}`;body=productionView(true);}
    return `<aside class="canvas-drawer" data-canvas-drawer tabindex="-1" role="region" aria-label="${esc(title)}制作面板"><header><div><h3>${esc(title)}</h3><p>修改留在当前卡片 · 草稿自动保留</p></div><button type="button" data-canvas-close aria-label="关闭制作面板">×</button></header><div class="canvas-drawer-body">${body}</div></aside>`;
  }
  function analysisView() { const overview={project,job:production,assets,coverage,selection:session.selection,apiBase,tasks,unsaved:Boolean(drafts.get(`production:review:${production?.id}`)||drafts.get(`production:edits:${production?.id}`)||drafts.get(`analysis:review:${analysis?.id}`))};const shots=overviewShots(overview);const legacy=shots.length&&!(analysis?.result||analysis?.draftResult)?storyCards({characters:[],scenes:[...new Set(shots.map(r=>r.shot.sceneId))].map((id,i)=>({id,title:`场次 ${i+1}`,order:i,summary:'已保存分镜；原文分析可在下方补充。'}))},{overview,shots,apiBase,canvasKey:production.id}):'';return legacy+analysisPanel({overview,shots,apiBase,script:scripts.at(-1),analysis,draft:drafts.get(`analysis:review:${analysis?.id}`),enabled:capabilities.scriptAnalysis,connected:Boolean(session.selection?.providerAccountId&&session.selection?.spaceId),busy,error:analysisError,models:capabilities.analysis?.models||[],modelId:drafts.get('text-model')||capabilities.analysis?.defaultModelId}); }
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
    return {prompt:'',selectionRevision:session.selection?.revision,sourceRevisionId:source?.id || '',count:page==='style'&&session.features?.imageGeneration?'4':'1',ratio:'',prepareKey:key()};
  }
  function composeView() {
    const e = currentEntity(); if (!e) return empty('还没有资产档案','先在清单中添加角色、场景或道具。');
    if (selectedEntity !== e.id) selectedEntity = e.id;
    const draft = getCompose(), sources = approvedSources(currentAsset(),page,session.selection);
    const selectedSource = sources.find(s=>s.id===draft.sourceRevisionId), connected = session.selection?.providerAccountId && session.selection?.spaceId;
    return `${promptsView()}<section class="wf-panel"><h3>${esc(stageLabels[page])}</h3><p class="wf-muted">${page==='style'?'探索风格，先由你选定这一版，再制作 Image2 资产。':page==='asset'?'已审核的 MJ 风格作为依据，制作可复用的角色、场景和道具。':'使用原始 Image2 文件精修。退回后的 Nano 图片不会被当作新的原图。'}</p><form data-wf-form="compose" class="wf-compose"><label>资产档案<select data-wf-entity-select>${options(plan.entities.map(item=>[item.id,`${categories[item.category]} · ${item.name}`]),selectedEntity)}</select></label>${page!=='style'?`${sourceImagePicker(sources,draft.sourceRevisionId,apiBase,{title:'上一阶段已审核参考'})}${selectedSource?'':'<p class="wf-note">尚未选择可用参考。每一步需要先通过人工审核，且不能混用其他账号或空间的图片。</p>'}`:''}<label>本次实际发送的制作要求<textarea name="prompt" rows="10" maxlength="20000" required placeholder="先在上方点击 AI 编写，再使用并核对提示词。">${esc(draft.prompt)}</textarea></label><details><summary>手工编写 / 调整提示词</summary><label class="wf-analysis-check"><input type="checkbox" name="manualPrompt" ${draft.manualPrompt?'checked':''}> 我自行编写完整的制作要求，不使用上方 AI 草稿</label></details><label class="wf-analysis-check"><input type="checkbox" name="promptReviewed" required> 我已核对提示词、剧本事实和视觉设计选择</label><div class="wf-form-grid"><label>候选数量<select name="count">${options(page==='style'&&session.features?.imageGeneration?[['4','4 张（MJ 一组）']]:[['1','1 张'],['2','2 张'],['4','4 张']],String(draft.count))}</select></label><label>画幅（可选）<select name="ratio">${options([['','使用官方模型默认'],['16:9','16:9'],['9:16','9:16'],['1:1','1:1']],draft.ratio)}</select></label></div>${!connected?'<div class="wf-note">请先选择已授权的 LibTV 账号与空间。当前草稿会保留。</div>':''}<div class="wf-actions"><button class="primary" type="submit" ${!connected || (page!=='style'&&!selectedSource)?'disabled':''}>准备任务并核对</button><button type="button" data-wf-nav="review">查看返回结果</button></div><p class="wf-muted">准备不会提交生成。模型与参数以官方适配器核验为准；金额未知时不会显示为免费。${session.features?.imageGeneration?'提交后使用当前已授权账号的 LibTV 积分。':'图片提交服务尚未启用。'}</p></form></section><div data-wf-returned>${returnedView(e.id)}</div>${tasksView(e.id)}`;
  }
  function promptsView() {
    const entity=currentEntity();if(!entity)return '';
    return promptPanel({job:entityPrompt(),entity,stage:page,models:capabilities.analysis?.models||[],modelId:drafts.get('text-model')||capabilities.analysis?.defaultModelId,enabled:capabilities.scriptAnalysis,connected:Boolean(session.selection?.providerAccountId&&session.selection?.spaceId),busy,error:promptError,history:promptJobs.filter(j=>j.entityId===entity.id)});
  }
  function returnedView(entityId) {
    const asset=assets.find(a=>a.entityId===entityId&&a.active);
    const rows=(asset?.revisions||[]).filter(r=>r.status==='ready'&&r.review==='pending'&&r.stage===page);
    return rows.length ? `<section class="wf-panel"><div class="wf-section-title"><h3>已返回 · ${rows.length} 张候选图待审核</h3><button data-wf-nav="review">进入审核</button></div>${generationGallery(rows,apiBase,{category:asset.category,busy:reviewing||busy&&!submittingBatch&&!recoveringTask})}</section>` : '';
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
    return `<section class="wf-panel" data-wf-task-feedback><h3>当前档案的任务</h3>${taskError?`<p class="wf-note">${esc(taskError)}</p>`:''}<p class="wf-muted">${lastChecked?'本地状态更新 '+esc(lastChecked.toLocaleTimeString()):'正在检查任务状态'} · 处理中的任务每 5 秒刷新</p>${rows.length?`<ul class="wf-task-list">${rows.map(t=>`<li>${tag(t.status,taskLabel(t))} <b>${esc(recipeLabels[t.recipe] || t.recipe)}</b><p class="wf-muted">${esc(t.ownership?.accountLabelAtCreation||t.ownership?.providerAccountId)} / ${esc(t.ownership?.spaceNameAtCreation||t.ownership?.spaceId)} · ${esc(t.id.slice(-8))}</p><p class="wf-muted">${esc(taskProgress(t))} · 更新于 ${esc(new Date(t.updatedAt).toLocaleTimeString())}</p>${['preparing','submitting','queued','submitted','running','downloading'].includes(t.status)?'<progress aria-label="任务处理中，等待实际结果"></progress>':''}${t.error?`<p class="wf-note">${esc(t.error.message)}</p>`:''}${t.canConfirm?`<button data-wf-confirm-task="${esc(t.id)}">继续确认已准备的生成任务</button>`:''}${!t.submissionAttempted&&!['completed','cancelled'].includes(t.status)?`<button data-wf-cancel="${esc(t.id)}">取消未提交记录</button>`:''}${t.canRecover?`<button data-wf-recover="${esc(t.id)}">查询原任务并收取</button>`:''}</li>`).join('')}</ul>`:'<p class="wf-muted">还没有任务。准备后的任务归属会固定保存，切换账号不改变旧任务。</p>'}</section>`;
  }
  function allRevisions() { return assets.filter(a=>!selectedEntity || a.entityId===selectedEntity).flatMap(a=>a.revisions.map(r=>({...r,asset:a}))); }
  function reviewView() {
    const rows = allRevisions().sort((a,b)=>(a.review==='pending'?-1:0)-(b.review==='pending'?-1:0)||b.createdAt.localeCompare(a.createdAt));
    return `<section class="wf-panel" data-wf-review-list><div class="wf-section-title"><h3>比较版本，决定保留或返修</h3><select aria-label="筛选审核档案" data-wf-review-entity><option value="">全部档案</option>${options(plan.entities.map(e=>[e.id,e.name]),selectedEntity)}</select></div><p class="wf-muted">“任务完成”表示图片已返回；只有人工保留后才进入下一步。历史与失效版本保留供核对。</p>${rows.length?`<div class="wf-review-list">${rows.map(r=>`<article class="wf-revision"><h4>${esc(r.asset.name)}</h4>${generationGallery([r],apiBase,{category:r.asset.category,busy:reviewing||busy&&!submittingBatch&&!recoveringTask})}${r.review==='changes_requested'&&!r.asset.referenceOnly?`<button data-wf-repair="${esc(r.id)}">按意见返修</button>`:''}</article>`).join('')}</div>`:empty('等待你的第一份候选图','返回图片会在这里展示，所有阶段都需要你确认。')}</section>`;
  }
  function reviewDetail() {
    const asset = assets.find(a=>a.revisions.some(r=>r.id===reviewId)), r=asset?.revisions.find(r=>r.id===reviewId); if(!r)return '';
    return versionPicker({asset,revision:r,job:production,selection:session.selection,apiBase,reroll:rerollId===r.id,mode:rerollMode,allAssets:assets,
      draft:drafts.get(rerollKey())||{},catalog:imageCatalog,contracts:imageContracts,loading:imageModelsLoading,error:imageModelsError,actionError:error,
      busy:reviewing||busy&&!submittingBatch&&!recoveringTask});
  }

  function confirmationView() {
    const task=prepared.task, enabled=session.features?.imageGeneration===true;
    const batch=prepared.batch||[prepared],total=batch.reduce((n,r)=>n+(r.confirmation?.summary?.count||1),0);
    const costs=batch.map(r=>r.cost||r.task.cost||{}),cost=costs.every(c=>c.state==='known'&&c.unit===costs[0].unit)?{state:'known',amount:costs.reduce((n,c)=>n+Number(c.amount),0),unit:costs[0].unit}:{state:'unknown'};
    const archiveName=plan.entities.find(e=>e.id===task.entityId)?.name||assets.find(a=>a.entityId===task.entityId)?.name||'当前任务档案';
    const targetName=['mj_style','image25_style'].includes(task.recipe)?archiveName.replace(/ · 人物主多视图$/,''):archiveName;
    const purpose=prepared.operationLabel||{mj_style:'基础形象与风格候选',image25_style:'基础形象与风格候选',image2_asset:'规范资产图',image25_asset:'Image2.5 规范资产图',nano_refine:'资产精修图',storyboard_image:'分镜图',image25_storyboard:'Image2.5 分镜图'}[task.recipe]||'候选图';
    const references=(task.sourceRevisionIds||[]).map(id=>{const a=assets.find(a=>a.revisions.some(r=>r.id===id));return a?`${a.name} · ${id.slice(-6)}`:`图片版本 ${id.slice(-6)}`;});
    return `<section class="wf-panel" data-confirmation tabindex="-1"><h3>${submittingBatch?'正在提交这批图片':'核对这次任务'}</h3>${submittingBatch?'<p role="status">正在上传参考并等待各组回执，请勿重复提交。</p><progress aria-label="正在提交图片任务"></progress>':''}<p><b>${batch.length} 组 · 共 ${total} 张</b> · 确认后并发生成</p>${batch.length>1?`<ol>${batch.map((r,i)=>`<li>${esc(r.targetName||`第 ${i+1} 组`)} · ${esc(r.confirmation.summary.modelKey)} · ${r.confirmation.summary.count} 张 · ${esc(r.task.id.slice(-6))}</li>`).join('')}</ol>`:''}<p><strong>制作对象：${esc(prepared.multipleShots?'本批清单中的分镜':targetName)}</strong> · ${esc(purpose)}</p>${prepared.multipleShots?batch.map(r=>`<details><summary>${esc(r.targetName)} · 参考与提示词</summary><p>${(r.task.sourceRevisionIds||[]).map(id=>{const a=assets.find(a=>a.revisions.some(v=>v.id===id));return esc((a?.name||'图片版本')+' · '+id.slice(-6));}).join('；')}</p><pre class="wf-prompt-text">${esc((r.confirmation.summary.prompt||'').replace(/\{\{reference:[^}]+\}\}/g,'（已绑定参考图片）'))}</pre></details>`).join(''):references.length?`<p>已固定参考：${references.map(esc).join('；')}</p>`:''}<details><summary>${prepared.multipleShots?'首镜完整提示词（其他镜头见上方）':'本次实际发送的完整提示词'}</summary><pre class="wf-prompt-text">${esc((prepared.confirmation?.summary?.prompt||'提示词暂不可读，请保留任务后刷新核对。').replace(/\{\{reference:[^}]+\}\}/g,'（已绑定参考图片）'))}</pre></details><p>模型：${esc(prepared.confirmation?.summary?.modelKey||recipeLabels[task.recipe]||task.recipe)}</p><p>每组生成 ${esc(prepared.confirmation?.summary?.count || task.spec?.settings?.count || 1)} 张候选图</p><p class="wf-note">任务账号：${esc(task.ownership?.accountLabelAtCreation||task.ownership?.providerAccountId)}<br>工作空间：${esc(task.ownership?.spaceNameAtCreation||task.ownership?.spaceId)}<br>费用：${cost.state==='known'?esc(`${cost.amount} ${cost.unit}`):'未知 · 不能视为免费'}</p><p class="wf-muted">切换页面上的账号不会改变这个任务的归属。${!enabled?'当前版本未启用图片提交；准备记录已保存。':''}</p><div class="wf-actions"><button data-wf-action="close-confirmation">${submittingBatch?'收起并查看任务进度':'保留准备记录'}</button><button data-wf-action="submit-task" class="primary" ${!enabled||busy?'disabled':''}>${batch.length>1?'确认并提交这 '+batch.length+' 组':'确认并提交生成'}</button></div></section>`;
  }
  function deliveryView() {
    const allowed=coverage.scope==='production'?new Set(coverage.exportRevisionIds||[]):null;
    const approved = assets.flatMap(a=>a.revisions).filter(r=>r.review==='approved'&&r.status==='ready'&&(!allowed||allowed.has(r.id)));
    const archive = `<section class="wf-panel"><h3>审核与交付</h3><button data-wf-nav="review">查看待审核图片</button><p>${coverage.ready} / ${coverage.total} ${coverage.scope==='production'?'项当前制作内容已审核（物料与分镜）':'个档案已具备审核通过的规范资产（精修可选）'}</p><div class="wf-progress"><span style="width:${coverage.total?Math.round(100*coverage.ready/coverage.total):0}%"></span></div>${coverage.message?`<p class="wf-note">${esc(coverage.message)}</p>`:''}<p class="wf-muted">下载包含${coverage.scope==='production'?'当前方案内':''}有效的已审核图片、版本来源和逐文件 SHA-256。未审核、已退回或依据已变更的图片不会进入交付包。</p><div class="wf-actions">${approved.length?`<a data-wf-download class="wf-link" href="${esc(path(`/projects/${encodeURIComponent(selected)}/export`))}">下载已审核资产 (${approved.length})</a>`:'<button disabled>尚无可下载的已审核图片</button>'}<button class="primary" data-wf-action="archive" ${!coverage.complete?'disabled':''}>确认完成并归档</button></div>${!coverage.complete?`<div class="wf-note">尚有 ${(coverage.missing||[]).map(e=>esc(e.name)).join('、')||'未建档资产'} 未完成。当前下载属于部分交付。</div>`:''}</section><section class="wf-panel"><h3>交付归档</h3>${bundles.length?bundles.map(b=>`<div class="wf-note"><b>${esc(new Date(b.createdAt).toLocaleString())}</b><p>${b.assetCount} 张已审核资产 · ${Math.ceil(b.bytes/1024)} KiB</p><a data-wf-download class="wf-link" href="${esc(path(`/projects/${encodeURIComponent(selected)}/bundles/${encodeURIComponent(b.id)}/content`))}">下载这次归档</a></div>`).join(''):'<p class="wf-muted">归档保存当时确认的交付包。以后返修与换版不会覆盖旧交付。</p>'}</section>`;
    return `<details class="wf-panel"><summary>下载素材与交付归档</summary>${archive}</details>`;
  }
  function renderLibrary() {
    const select=doc.getElementById('scriptSelect'); if(select){select.innerHTML=projects.length?(!selected?'<option value="">选择已有项目</option>':'')+options(projects.map(p=>[p.id,p.name]),selected):'<option value="">新建你的第一个项目</option>';select.value=selected;}
    const list=doc.getElementById('warehouseList'); if(!list)return;
    const rows=buildCustomerArchives(assets,plan).filter(e=>(filter==='all'||e.category===filter)&&(!search||(e.name+' '+e.description).includes(search)));
    list.innerHTML=rows.length?`<div class="wf">${rows.map(e=>`<button class="wf-library-button" data-wf-archive="${esc(e.id)}">${e.cover?`<img class="wf-library-thumb" src="${image(e.assetId,e.cover.id)}" alt="${esc(e.name)} 缩略图" loading="lazy">`:'<span class="wf-library-placeholder" aria-hidden="true">待制作</span>'}<span><b>${esc(e.name)}</b><small>${esc(categories[e.category])} · ${e.revisions.length} 个版本 · ${e.stages.refine?'精修已审核':e.cover?label(e.cover.review):'待制作'}</small></span></button>`).join('')}</div>`:'<p class="wf-muted">先填写资产清单，档案会出现在这里。</p>';
    const count=doc.getElementById('warehouseCount');if(count)count.textContent=plan.entities.length;
    const summary=doc.getElementById('review-summary-root');if(summary){const pending=assets.flatMap(a=>a.revisions).filter(r=>r.review==='pending'&&r.status==='ready').length;summary.innerHTML=`<div class="wf wf-panel"><b>${pending} 张图片等待你审核</b><button data-wf-nav="review">查看待审图片</button><p class="wf-muted">每一步确认后，才能进入下一阶段。</p></div>`;}
  }
  async function loadLibrary(query=''){
    const serial=++librarySerial,projectId=selected;
    remoteLibrary={open:true,query,loading:true,items:[],detail:null,error:''};render();
    try{const reply=await api.request('/libtv-assets?projectId='+encodeURIComponent(projectId)+'&name='+encodeURIComponent(query),{quietProgress:true});if(serial===librarySerial)remoteLibrary={...remoteLibrary,...reply};}
    catch(e){if(serial===librarySerial)remoteLibrary.error=e.message||'素材库暂时无法读取。';}
    finally{if(serial===librarySerial){remoteLibrary.loading=false;render();}}
  }
  async function loadImageModels(refresh=false){
    if(!session.selection?.providerAccountId||!session.selection?.spaceId)return;
    const owner=JSON.stringify([session.selection.providerAccountId,session.selection.spaceId,session.selection.revision]);
    const serial=++imageModelSerial;
    if(owner!==imageCatalogOwner){imageCatalog=null;imageContracts={};imageCatalogOwner=owner;}
    imageModelsLoading=true;imageModelsError='';render();
    try{
      if(refresh||!imageCatalog){const response=await api.request('/image-models',{quietProgress:true});if(serial!==imageModelSerial)return;imageCatalog=response;}
      const draft=rerollId?(drafts.get(rerollKey())||{}):canvasDrawer?.type==='art'?artGenerationDraft():drafts.get(boardGenerationKey())||{};
      const chosen=rerollId&&rerollMode==='nano'?selectedNanoModel(draft,imageCatalog):selectedImageModel(draft,imageCatalog);
      if(!chosen)throw new Error('当前官方目录未返回 Nano 图片模型，请检查账号授权或刷新目录。');
      if(refresh||!imageContracts[chosen.id]){const contract=await api.request('/image-models?model='+encodeURIComponent(chosen.id),{quietProgress:true});if(serial!==imageModelSerial)return;imageContracts[chosen.id]=contract;}
    }catch(e){if(serial===imageModelSerial)imageModelsError=e.message||'模型目录暂时无法读取。';}
    finally{if(serial===imageModelSerial){imageModelsLoading=false;render();}}
  }
  async function load({initial=false}={}) {
    const serial=++requestSerial;loading=initial;error='';if(initial)render();
    try {
      const [projectResult, caps]=await Promise.all([api.request('/projects'),api.request('/workflow/capabilities')]);capabilities=caps;if(!alive||serial!==requestSerial)return;
      projects=projectResult.items || [];
      if(!creating&&!projects.some(p=>p.id===selected))selected=projects[0]?.id || '';
      project=projects.find(p=>p.id===selected)||null;
      if(project)project=await api.request(`/projects/${encodeURIComponent(selected)}`);
      if(!project){production=null;productionError='';analysis=null;analysisError='';promptJobs=[];promptError='';plan={version:0,entities:[],stylePrompt:''};assets=[];scripts=[];tasks=[];bundles=[];coverage={total:0,ready:0,complete:false};return;}
      const projectId=selected;
      const replies=await Promise.all([
        api.request(`/projects/${encodeURIComponent(projectId)}/plan`),
        api.request(`/projects/${encodeURIComponent(projectId)}/assets`),
        api.request(`/projects/${encodeURIComponent(projectId)}/bundles`),
        loadTasks(projectId).then(value=>({ok:true,value}),e=>({ok:false,error:e})),
        api.request(`/projects/${encodeURIComponent(projectId)}/prompts`).then(value=>({ok:true,value}),e=>({ok:false,error:e})),
      ]);
      if(!alive||serial!==requestSerial||projectId!==selected)return;
      [plan]=replies;assets=replies[1].items||[];coverage=replies[1].coverage||{total:plan.entities.length,ready:0,complete:false};bundles=replies[2].items||[];
      if(replies[3].ok){tasks=replies[3].value.items||[];taskError='';lastChecked=new Date();}else{tasks=[];taskError=replies[3].error.message||'任务服务尚未就绪。';}
      if(replies[4].ok){promptJobs=replies[4].value.items||[];promptError='';}else{promptJobs=[];promptError=replies[4].error.message||'AI 提示词状态暂不可用。';}
      const loadedScripts=await Promise.all(project.scriptIds.map(id=>api.request(`/projects/${encodeURIComponent(projectId)}/scripts/${encodeURIComponent(id)}`)));
      if(!alive||serial!==requestSerial||projectId!==selected)return;scripts=loadedScripts;analysis=null;analysisError='';
      if(scripts.length){try{const response=await api.request(`/projects/${encodeURIComponent(projectId)}/scripts/${encodeURIComponent(scripts.at(-1).id)}/analysis`);if(!alive||serial!==requestSerial||projectId!==selected)return;analysis=response.analysis;}catch(e){analysisError=e.message||'AI 分析状态暂不可用。';}}
      if(!scripts.length)production=null;productionError='';
      if(scripts.length){try{const response=await api.request(`/projects/${encodeURIComponent(projectId)}/scripts/${encodeURIComponent(scripts.at(-1).id)}/production`);if(!alive||serial!==requestSerial||projectId!==selected)return;production=response.analysis;}catch(e){productionError=e.message||'制作方案暂时无法读取。';}}
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
    polling=true;let mediaChanged=false,tasksChanged=false;
    try {
      if(analysis?.canRefresh){const updated=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/refresh`,{method:'POST',body:{}});if(!alive||serial!==requestSerial||projectId!==selected)return;analysis=updated;analysisError='';const panel=root.querySelector('[data-wf-analysis]');if(panel&&!drafts.get(`analysis:review:${analysis.id}`))panel.outerHTML=analysisView();}
      // Prompt polling updates only its own panel, preserving an edited composer.
      if(production?.canRefresh){const updated=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/refresh`,{method:'POST',body:{}});if(!alive||serial!==requestSerial||projectId!==selected)return;production=updated;productionError='';const panel=root.querySelector('[data-wf-production]');if(panel&&!busy){panel.outerHTML=productionView();canvas.refresh();}}
      let promptsChanged=false;
      for(const job of promptJobs.filter(promptProcessing)){
        const updated=await api.request(`/prompt-jobs/${encodeURIComponent(job.id)}/refresh`,{method:'POST',body:{}});
        if(!alive||serial!==requestSerial||projectId!==selected)return;
        promptsChanged=promptsChanged||JSON.stringify(job)!==JSON.stringify(updated);promptJobs=promptJobs.map(j=>j.id===updated.id?updated:j);promptError='';
      }
      const promptPanel=root.querySelector('[data-wf-prompts]');if(promptPanel&&!busy&&promptsChanged)promptPanel.outerHTML=promptsView();
      // Read tasks first: a completed task guarantees its outputs were persisted.
      const result=await loadTasks(projectId);
      const received=await api.request(`/projects/${encodeURIComponent(projectId)}/assets`);
      if(!alive||serial!==requestSerial||projectId!==selected)return;
      const previous=new Set(assets.flatMap(a=>a.revisions.map(r=>r.id)));
      mediaChanged=JSON.stringify(assets)!==JSON.stringify(received.items||[]);
      assets=received.items||[];coverage=received.coverage||coverage;
      const added=assets.flatMap(a=>a.revisions).filter(r=>!previous.has(r.id)&&r.status==='ready').length;
      tasksChanged=JSON.stringify(tasks)!==JSON.stringify(result.items);
      tasks=result.items;taskError='';lastChecked=new Date();
      if(added)announce(`${added} 张图片已自动返回，缩略图已更新，等待你审核。`);
    } catch(e) {
      if(!alive||serial!==requestSerial||projectId!==selected)return;
      taskError=e.message||'任务状态暂时无法读取，已有记录已保留。';
    } finally {
      polling=false;
      if(alive&&serial===requestSerial&&projectId===selected){
        // Keep form nodes and their caret intact while refreshing background status.
        if((['production',...stages].includes(page)||canvasDrawer?.type==='production')&&production&&returnedResult(production)){
          const c=(stages.includes(phase())||boardView().inspector==='generate')?generationContext({result:currentProduction(),job:production,view:boardView(),assets,selection:session.selection}):null;
          const gallery=root.querySelector('[data-board-generation-gallery]');if(gallery&&c&&mediaChanged)gallery.innerHTML=generationGallery(c.versions,apiBase,{stage:c.shot?'storyboard':boardView().stage,category:c.asset?.category,master:c.master,direction:!canvasDrawer&&phase()==='style',busy:busy||c.binding?.changed||Boolean(drafts.get(`production:review:${production.id}`))});
          const feedback=root.querySelector('[data-board-generation-feedback]');if(feedback&&c)feedback.innerHTML=tasksView(c.binding?.entityId);
          if(mediaChanged){const temp=doc.createElement('div');temp.innerHTML=productionView();const old=root.querySelector('[data-board-stage]'),fresh=temp.querySelector('[data-board-stage]');if(old&&fresh){old.replaceChildren(...fresh.childNodes);canvas.refresh();}}
        }
        if(canvasDrawer?.type==='art'&&(mediaChanged||tasksChanged)){
          const temp=doc.createElement('div');temp.innerHTML=canvasPanelView();
          for(const selector of ['[data-art-gallery]','[data-art-feedback]']){const old=root.querySelector(selector),fresh=temp.querySelector(selector);if(old&&fresh)old.replaceChildren(...fresh.childNodes);}
          const selector='[data-wf-form="art-generation"] button[type="submit"]',old=root.querySelector(selector),fresh=temp.querySelector(selector);
          if(old&&fresh){old.textContent=fresh.textContent;old.disabled=fresh.disabled;old.toggleAttribute('data-art-reroll',fresh.hasAttribute('data-art-reroll'));}
        }
        const taskPanel=root.querySelector('[data-wf-task-feedback]');if(taskPanel&&!taskPanel.closest('[data-board-generation-feedback]'))taskPanel.outerHTML=tasksView(selectedEntity);
        if(mediaChanged){
        const returned=root.querySelector('[data-wf-returned]');if(returned)returned.innerHTML=returnedView(selectedEntity||currentEntity()?.id);
        const reviewPanel=root.querySelector('[data-wf-review-list]');if(reviewPanel)reviewPanel.outerHTML=reviewView();
        const archives=root.querySelector('[data-wf-archives]');if(archives)archives.innerHTML=archivesView();
        renderLibrary();
        const countNode=doc.getElementById('reviewCount');if(countNode)countNode.textContent=assets.flatMap(a=>a.revisions).filter(r=>r.review==='pending'&&r.status==='ready').length;
        }
        if(page==='plan'&&(mediaChanged||tasksChanged)&&!busy&&!reviewId)refreshStoryOverview();
        const guidePanel=root.querySelector('.wf-guide');if(guidePanel)guidePanel.outerHTML=guideView();
        events.dispatchEvent(new CustomEvent('workflow:tasks-refreshed',{detail:{projectId}}));
        scheduleFlow();
      }
    }
  }
  function refreshStoryOverview(){
    if(root.querySelector('.story-panning')){storyRefreshPending=true;return;}
    const old=root.querySelector('.story-canvas');if(!old)return;
    const details=[...old.querySelectorAll('[data-story-node] details')].map(n=>({id:n.closest('[data-story-node]').dataset.storyNode,title:n.querySelector('summary')?.textContent,open:n.open}));
    const scrolls=new Map([...old.querySelectorAll('.overview-shot-copy,.story-card-detail')].map(n=>[n.closest('[data-story-node]').dataset.storyNode,n.scrollTop]));
    const temp=doc.createElement('div');temp.innerHTML=analysisView();const fresh=temp.querySelector('.story-canvas');if(!fresh)return;
    for(const n of fresh.querySelectorAll('[data-story-node] details')){const saved=details.find(d=>d.id===n.closest('[data-story-node]').dataset.storyNode&&d.title===n.querySelector('summary')?.textContent);if(saved)n.open=saved.open;}
    old.replaceWith(fresh);storyCanvas.refresh();
    for(const n of fresh.querySelectorAll('.overview-shot-copy,.story-card-detail'))n.scrollTop=scrolls.get(n.closest('[data-story-node]').dataset.storyNode)||0;
    storyRefreshPending=false;
  }
  listen(root,'pointerup',()=>{if(storyRefreshPending)refreshStoryOverview();});
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
      const result=await api.request(`/tasks/${encodeURIComponent(task.id)}/recover`,{method:'POST',body:{expectedVersion:task.version},background:true});
      collectionAttempts.set(task.id,{due:Date.now()+collectionDelay(result.task)});
      if(result.task.error?.code==='PROVIDER_ACCOUNT_READ_UNAVAILABLE')collectionAttempts.set(collectionOwnerKey(task),{due:Date.now()+60000});
    } catch(e) {
      collectionAttempts.set(task.id,{due:Date.now()+30000});
      if(e.code==='PROVIDER_ACCOUNT_READ_UNAVAILABLE')collectionAttempts.set(collectionOwnerKey(task),{due:Date.now()+60000});
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
    if(next.kind==='prompt'){if(next.spec?.repairOfRevisionId)return repair(next.spec.repairOfRevisionId);selectedEntity=next.entity.id;persist('selectedEntity',selectedEntity);return navigate(next.stage);}
    if(next.kind==='confirm')return perform(async()=>{prepared=await api.request(`/tasks/${encodeURIComponent(next.task.id)}/confirm`,{method:'POST',body:{expectedVersion:next.task.version}});await load();});
    if(next.kind==='recover')return perform(async()=>{await api.request(`/tasks/${encodeURIComponent(next.task.id)}/recover`,{method:'POST',body:{expectedVersion:next.task.version}});await load();});
    if(next.kind==='archive')return perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/bundles`,{method:'POST',body:{expectedVersion:project.version}});page='plan';persist('page',page);await load();});
  }
  function continueAfterReview() {
    if(!canvasDrawer&&!production&&page!=='production'&&drafts.get(`flow:${selected}`))setTimeout(()=>{if(alive&&!busy&&!canvasDrawer)void continueFlow();},0);
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
    const draft=getCompose();
    const current={...draft,prompt:form.elements.prompt.value,sourceRevisionId:form.elements.sourceRevisionId?.value||'',
      count:form.elements.count.value,ratio:form.elements.ratio.value,manualPrompt:form.elements.manualPrompt?.checked===true,
      selectionRevision:session.selection?.revision};
    if(['prompt','sourceRevisionId','count','ratio','selectionRevision'].some(k=>current[k]!==draft[k]))current.prepareKey=key();
    return current;
  }
  function navigate(next,{object=false}={}) {
    if(next==='style'&&!object)return openCanvasPanel({type:'art',role:'standard'});
    if(stages.includes(next)||next==='production'){
      if(next==='production'&&stages.includes(phase())&&production){const v=boardView();boardViews.set(production.id,{...v,kind:'shots',inspector:'shots',index:v.returnShot||0});}
      reviewId=null;return openCanvasPanel({type:'production',phase:next});
    }
    canvasDrawer=null;page=normalizePage(next);if(!['plan','review'].includes(page))page='plan';
    reviewId=null;persist('page',page);render();root.scrollIntoView({behavior:'instant',block:'start'});
  }
  async function switchProject(id) {
    if(busy||id===selected)return;canvasDrawer=null;returnStoryShot=null;storyRefreshPending=false;librarySerial++;remoteLibrary={open:false};clearTimeout(flowTimer);flowTimer=null;creating=false;selected=id;selectedEntity='';reviewId=null;prepared=null;editing=false;
    persist('selectedProject',id);persist('selectedEntity','');await load({initial:true});
  }
  function openReview(id, button) {
    if(reviewId!==id)rerollId=null;reviewId=id;focusedBeforeReview=button;render();root.querySelector('[data-review-detail]')?.focus({preventScroll:true});root.querySelector('[data-review-detail]')?.scrollIntoView({behavior:'instant',block:'start'});
  }
  async function decide(decision,{revisionId=reviewId,note:selectionNote,keepOpen=false,confirmCurrentBasis=false}={}) {
    if(reviewing)return;
    if(busy&&!submittingBatch&&!recoveringTask){announce('当前操作完成后即可保存审核；审核意见已保留。');return;}
    const asset=assets.find(a=>a.revisions.some(r=>r.id===revisionId)),r=asset?.revisions.find(r=>r.id===revisionId);if(!r||(r.status!=='ready'&&!(confirmCurrentBasis&&r.reconfirmation)))return;
    const note=selectionNote??drafts.get(`review:${r.id}`)?.note??'';
    if(decision==='changes_requested'&&note.trim().length<4){error='请填写至少 4 个字的具体返修意见。';render();return;}
    const projectId=selected;reviewing=true;error='';render();
    try{
      await api.request(`/assets/${encodeURIComponent(asset.id)}/reviews`,{method:'POST',body:{revisionId:r.id,sha256:r.sha256,decision,note,expectedVersion:asset.version,...(confirmCurrentBasis?{confirmCurrentBasis:true,expectedEntityVersion:r.reconfirmation.entityVersion}:{})},background:submittingBatch||recoveringTask});
      removeDraft(`review:${r.id}`);
      if(keepOpen){reviewId=r.id;rerollId=null;}else if(reviewId===r.id)reviewId=null;
      // Reviews only change media selection and validity. Refresh that snapshot,
      // leaving the active plan/view and paid submission promises intact.
      const received=await api.request(`/projects/${encodeURIComponent(projectId)}/assets`,{background:submittingBatch||recoveringTask});
      if(alive&&selected===projectId){assets=received.items||[];coverage=received.coverage||coverage;
        announce(decision==='approved'?'这一版已保留。你可以选用、继续调整或制作其他画面。':'返修意见已保存；尚未发起新的生成。');
        events.dispatchEvent(new CustomEvent('workflow:reviewed',{detail:{projectId,assetId:asset.id,revisionId:r.id,decision}}));}
    }catch(e){if(alive&&selected===projectId)error=e.message||'审核状态暂未更新，请刷新核对原记录。';}
    finally{reviewing=false;render();}
    if(!error&&!keepOpen)continueAfterReview();
  }
  function repair(id) {openReview(id);startReroll(id);}
  function startReroll(id,mode='reroll'){
    let r=assets.flatMap(a=>a.revisions).find(r=>r.id===id);
    if(mode==='nano'){if(!['asset','storyboard'].includes(r?.stage))return;r=nanoCleanupSource(r,assets);id=r?.id;}
    if(!r||(r.status!=='ready'&&!r.reconfirmation)||!versionTarget(production,r)||!belongsToSelection(r,session.selection))return;
    rerollMode=mode;rerollId=id;reviewId=id;persist(rerollKey(),{...drafts.get(rerollKey()),prepareKey:key()});render();void loadImageModels();
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
  function changeAnalysisField(path,value,target=null){
    const name=`analysis:review:${analysis.id}`,draft=drafts.get(name)||analysisDraft(analysis);
    if(!setReviewValue(draft.result,path,value))return;
    persist(name,draft);
    root.querySelectorAll('[data-wf-analysis-field]').forEach(input=>{if(input!==target&&input.dataset.wfAnalysisField===path){if(input.type==='checkbox')input.checked=value;else input.value=value??'';}});
    root.querySelectorAll('[data-analysis-draft-status]').forEach(el=>el.textContent='有未保存修改，请保存并核对');
    const next=root.querySelector('[data-wf-action="open-production-plan"]');if(next)next.disabled=true;
  }
  function changeProductionField(path,value,target=null) {
    const name=`production:review:${production.id}`;
    const draft=drafts.get(name)||reviewDraft(production,drafts.get(`production:edits:${production.id}`));
    if(!setReviewValue(draft.result,path,value))return;
    persist(name,draft);
    // Update duplicate quote editors without replacing the focused textarea.
    root.querySelectorAll('[data-wf-production-field]').forEach(input=>{
      if(input!==target&&input.dataset.wfProductionField===path){
        if(input.type==='checkbox')input.checked=value.includes(input.value);else input.value=input.hasAttribute('data-reference-text')?readableText(value,draft.result,draft.result.shots[Number(path.split('.')[1])]):input.hasAttribute('data-production-lines')?value.join('\n'):value;
      }
    });
    root.querySelectorAll('[data-wf-production-draft-status]').forEach(el=>el.textContent='修改已保存在本机，点击保存后检查');
    root.querySelectorAll('[data-board-status]').forEach(el=>el.textContent='有未保存修改');
    root.querySelectorAll('[data-board-next]').forEach(el=>el.textContent=' · 修改尚未保存');
    const handoff=root.querySelector('[data-wf-action="production-plan"]');if(handoff)handoff.disabled=true;
  }
  function openReferencePicker(path,range=null){
    const result=currentProduction(),shot=result?.shots[Number(path.split('.')[1])];if(!shot)return;
    const input=[...root.querySelectorAll('[data-reference-text]')].find(n=>n.dataset.wfProductionField===path);
    const host=[...root.querySelectorAll('[data-reference-picker]')].find(n=>n.dataset.referencePicker===path);if(!input||!host)return;
    referenceCursor={path,start:range?.start??input.selectionStart??input.value.length,end:range?.end??input.selectionEnd??input.value.length};
    host.hidden=false;host.innerHTML=referencePicker(result,shot,path,'',pickerCards(result));host.querySelector('input')?.focus();
    host.scrollIntoView({block:'nearest'});
  }
  function pickerCards(result){
    return referenceCards({...production,result},{references:result.assets.flatMap(a=>a.states.map(s=>({assetId:a.id,stateId:s.id})))},assets,session.selection,apiBase);
  }
  function renderImageChoice(target){
    const {name,value}=target,reference=target.dataset.referenceToggle,purpose=target.dataset.referencePurposeChange;
    render();
    const next=[...root.querySelectorAll('input,select')].find(el=>reference?el.dataset.referenceToggle===reference:purpose?el.dataset.referencePurposeChange===purpose:name&&el.name===name&&el.value===value);
    next?.focus({preventScroll:true});
  }
  function insertDirectorAsset(assetId,stateId,revisionId,shotIndex){
    const result=structuredClone(currentProduction()),shot=result?.shots[shotIndex],asset=result?.assets.find(a=>a.id===assetId);
    if(!asset||!shot)return;
    const binding=production.bindings.find(b=>b.assetId===assetId&&b.stateId===stateId),library=assets.find(a=>a.entityId===binding?.entityId);
    const revision=library?.revisions.find(r=>r.id===revisionId&&r.status==='ready'&&r.review==='approved'&&['asset','refine'].includes(r.stage)&&belongsToSelection(r,production.ownership));
    if(!revision||binding?.changed){announce('该资产尚无当前可用的已选图片，请先补齐。');return;}
    if(!bindReference(shot,asset,stateId,revisionId)){announce('此物料状态不适用于当前场次。');return;}
    shot.references.find(r=>r.assetId===assetId).revisionId=revisionId;
    changeProductionField(`shots.${shotIndex}.references`,shot.references);updateBoard({inspector:'shots',kind:'shots',index:shotIndex});announce(`已将 ${asset.name} 引用到镜头 ${shotIndex+1}，并固定当前图片版本。`);
  }
  function onInput(event) {
    const target=event.target;
    if(target.hasAttribute('data-image-choice-search')){
      const q=target.value.trim().toLocaleLowerCase();
      target.closest('[data-image-picker]')?.querySelectorAll('.image-choice').forEach(card=>{
        const item=card.closest('.image-choice-item')||card;
        item.hidden=!card.textContent.toLocaleLowerCase().includes(q)&&!card.querySelector('input:checked');
      });return;
    }
    if(target.hasAttribute('data-reference-toggle')||target.hasAttribute('data-reference-purpose-change')||target.hasAttribute('data-reference-purpose')){
      const form=target.closest('form'),inputs=Object.fromEntries(new FormData(form));
      if(target.hasAttribute('data-reference-purpose')){persist(boardGenerationKey(),{...inputs,referencePurpose:target.value});return;}
      const id=target.dataset.referenceToggle||target.dataset.referencePurposeChange;
      const purpose=target.hasAttribute('data-reference-purpose-change')?target.value:form.querySelector('[data-reference-purpose]').value;
      try{
        const refs=chooseExtraReference(extraReferences(inputs.extraReferences),referencePool(assets,production?.ownership||session.selection),id,purpose,target.hasAttribute('data-reference-purpose-change')||target.checked);
        persist(boardGenerationKey(),{...inputs,referencePurpose:form.querySelector('[data-reference-purpose]').value,extraReferences:JSON.stringify(refs),prepareKey:key()});renderImageChoice(target);
      }catch(e){renderImageChoice(target);announce(e.message);}return;
    }
    if(target.hasAttribute('data-wf-analysis-field')&&analysis){changeAnalysisField(target.dataset.wfAnalysisField,target.multiple?Array.from(target.selectedOptions,o=>o.value):target.type==='number'?Number(target.value):target.type==='checkbox'?target.checked:(target.tagName==='SELECT'&&!target.value)||target.hasAttribute('data-analysis-null')&&!target.value?null:target.value,target);return;}
    if(target.hasAttribute('data-wf-analysis-json')&&analysis){persist(`analysis:review:${analysis.id}`,{...(drafts.get(`analysis:review:${analysis.id}`)||analysisDraft(analysis)),raw:target.value});return;}
    if(target.hasAttribute('data-director-filter')){const q=target.value.toLocaleLowerCase();root.querySelectorAll('[data-director-asset-row]').forEach(row=>row.hidden=!row.textContent.toLocaleLowerCase().includes(q));return;}
    if(target.hasAttribute('data-creator-filter')){const q=target.value.toLocaleLowerCase();root.querySelectorAll('[data-creator-catalog] > button').forEach(b=>b.hidden=!b.textContent.toLocaleLowerCase().includes(q));return;}
    if(target.hasAttribute('data-image-model')){const formData=new FormData(target.closest('form')),values=Object.fromEntries(formData);if(canvasDrawer?.type==='batch')values.shotIds=formData.getAll('shotIds');for(const name of Object.keys(values))if(name.startsWith('param:'))delete values[name];persist(rerollId&&target.closest('form')?.dataset.wfForm==='version-reroll'?rerollKey():boardGenerationKey(),{...values,prepareKey:key()});void loadImageModels();return;}
    if(target.hasAttribute('data-art-subject')){const form=target.closest('form'),inputs=Object.fromEntries(new FormData(form));persist(boardGenerationKey(),{...inputs,prompt:studyPrompt(canvasDrawer.role,analysis?.result||analysis?.draftResult,inputs.subjectId),prepareKey:key()});render();return;}
    if(target.hasAttribute('data-canvas-asset')){updateBoard({index:Number(target.value),kind:'assets',state:0,characterLayer:'master'});return;}
    if(target.hasAttribute('data-board-generation-state')){updateBoard({state:Number(target.value)});return;}
    if(target.hasAttribute('data-reference-search')){
      const host=target.closest('[data-reference-picker]'),path=host.dataset.referencePicker,result=currentProduction(),shot=result.shots[Number(path.split('.')[1])];
      const holder=doc.createElement('div');holder.innerHTML=referencePicker(result,shot,path,target.value,pickerCards(result));host.querySelector('.board-reference-options').replaceWith(holder.querySelector('.board-reference-options'));return;
    }
    if(target.hasAttribute('data-reference-state-change')||target.hasAttribute('data-reference-version')){
      const si=Number(target.dataset.referenceShot),result=currentProduction(),shot=structuredClone(result.shots[si]);
      const ri=Number(target.dataset.referenceStateChange??target.dataset.referenceVersion),ref=shot.references[ri];if(!ref)return;
      if(target.hasAttribute('data-reference-state-change')){ref.stateId=target.value;delete ref.revisionId;}else if(target.value)ref.revisionId=target.value;else delete ref.revisionId;
      changeProductionField(`shots.${si}.references`,shot.references);renderImageChoice(target);return;
    }
    if(target.dataset.wfProductionField&&returnedResult(production)){
      const path=target.dataset.wfProductionField;
      let value=target.type==='number'?Number(target.value):target.value;
      if(target.hasAttribute('data-production-lines'))value=textLines(value);
      if(target.type==='checkbox'){
        const current=drafts.get(`production:review:${production.id}`)?.result||returnedResult(production);
        const values=new Set(valueAt(current,path)||[]);
        if(target.checked)values.add(target.value);else values.delete(target.value);
        value=[...values];
      }
      if(target.hasAttribute('data-reference-text')){const result=currentProduction(),shot=result.shots[Number(path.split('.')[1])];value=storedText(value,result,shot);}
      changeProductionField(path,value,target);
      if(target.hasAttribute('data-reference-text')){
        const result=currentProduction(),shot=result.shots[Number(path.split('.')[1])],output=[...root.querySelectorAll('[data-reference-preview]')].find(n=>n.dataset.referencePreview===path);if(output)output.innerHTML=linkedText(value,result,shot);
        if(!event.isComposing&&target.value.slice(0,target.selectionStart).endsWith('@'))openReferencePicker(path,{start:target.selectionStart-1,end:target.selectionStart});
      }return;
    }
if(target.matches('[data-wf-review-note]')&&reviewId){persist(`review:${reviewId}`,{note:target.value});return;}
    const form=target.closest('[data-wf-form]');if(!form)return;
    if(form.dataset.wfForm==='library-search')return loadLibrary(form.elements.name.value);
    if(form.dataset.wfForm==='prompt-recipe'){persist(`prompt-recipe:${selected}:${canvasDrawer.revisionId}`,{...Object.fromEntries(new FormData(form)),evidenceRevisionIds:new FormData(form).getAll('evidenceRevisionIds')});return;}
    if(form.dataset.wfForm==='art-generation'){persist(boardGenerationKey(),{...Object.fromEntries(new FormData(form)),prepareKey:key()});return;}
    if(form.dataset.wfForm==='art-standard'){persist(artBundleKey(),{...(drafts.get(artBundleKey())||{}),...Object.fromEntries(new FormData(form))});return;}
    if(form.dataset.wfForm==='art-direction'){persist(`art-direction:${selected}`,Object.fromEntries(new FormData(form)));return;}
    if(form.dataset.wfForm==='plan')persist(planKey(),capturePlan(form));
    if(form.dataset.wfForm==='version-reroll'){persist(rerollKey(),{...Object.fromEntries(new FormData(form)),prepareKey:key()});return;}
    if(form.dataset.wfForm==='board-generation'&&canvasDrawer?.type==='batch'){persist(boardGenerationKey(),{...Object.fromEntries(new FormData(form)),shotIds:new FormData(form).getAll('shotIds')});return;}
    if(form.dataset.wfForm==='board-generation'){persist(boardGenerationKey(),{...Object.fromEntries(new FormData(form)),prepareKey:key()});return;}
    if(form.dataset.wfForm==='compose'){if(target.name!=='promptReviewed'&&form.elements.promptReviewed)form.elements.promptReviewed.checked=false;persist(composeKey(),captureCompose(form));}
    if(form.dataset.wfForm==='create')persist('new-project',Object.fromEntries(new FormData(form)));
    if(form.dataset.wfForm==='quick-start')persist('quick-start',{text:form.elements.text.value,idempotencyKey:key()});
  }
  async function onSubmit(event) {
    const form=event.target.closest('[data-wf-form]');if(!form)return;event.preventDefault();
    if(form.dataset.wfForm==='version-reroll'){
      const r=assets.flatMap(a=>a.revisions).find(r=>r.id===form.dataset.revisionId),target=r&&versionTarget(production,r);
      if(!target)return;const inputs=Object.fromEntries(new FormData(form));
      const draft={...inputs,prepareKey:drafts.get(rerollKey())?.prepareKey||key()};persist(rerollKey(),draft);
      return perform(async()=>{
        if(rerollMode!=='nano'&&(drafts.get(`production:review:${production.id}`)||drafts.get(`production:edits:${production.id}`)))throw new Error('请先保存镜头编排，再准备重抽。');
        const nano=rerollMode==='nano',chosen=nano?selectedNanoModel(draft,imageCatalog):selectedImageModel(draft,imageCatalog);
        if(!chosen||nano&&chosen.id!==inputs.modelId)throw new Error('请选择当前官方目录中可用的 Nano 模型。');
        const settings=collectImageSettings(inputs,imageContracts[chosen.id]);
        const body={...target,prompt:nano?NANO_CLEANUP_PROMPT:r.prompt||'沿用原图设计与当前制作要求。',sourceRevisionIds:r.stage==='asset'||r.stage==='refine'?r.sourceRevisionIds.slice(0,1):[],
          editRevisionId:r.id,editSha256:r.sha256,expectedEditEntityVersion:r.reconfirmation?.entityVersion,editNote:inputs.editNote||(nano?'只做保真清理，保持原图人物、构图、动作与画风，不重新设计。':''),confirmEditReference:true,modelId:chosen.id,settings,
          expectedReviewVersion:production.reviewVersion,expectedEditVersion:production.editVersion,expectedPlanVersion:plan.version,
          expectedSelectionRevision:session.selection.revision,expectedArtDirectionVersion:project.artDirection?.version||0};
        const prepareGroup=async i=>{const response=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/images/prepare`,{method:'POST',body:{...body,idempotencyKey:draft.prepareKey+':group:'+i}});if(!response.confirmation)throw new Error(response.task?.error?.message||'重抽准备未完成，请查看原记录。');return response;};
        const first=await prepareGroup(0),rest=await parallelGroups(Array.from({length:batchSize(inputs.groups)-1},(_,i)=>i+1),prepareGroup);
        const ready=[first,...rest.filter(r=>r.status==='fulfilled').map(r=>r.value)],failed=rest.filter(r=>r.status==='rejected');
        prepared={...first,batch:ready,rerollRevisionId:r.id,operationLabel:nano?'Nano 保真洗图':null};selectedEntity=first.task.entityId;await load();
        announce(`已带上原图，准备 ${ready.length} 组${nano?' Nano 洗图':'重抽'}。${failed.length?failed.length+' 组未准备成功，原记录保留。':''}核对费用后提交；当前选用版本未改变。`);
      });
    }
    if(form.dataset.wfForm==='prompt-recipe'){
      const values=Object.fromEntries(new FormData(form)),r=assets.flatMap(a=>a.revisions).find(r=>r.id===values.revisionId);if(!r)return;
      const body={...values,evidenceRevisionIds:new FormData(form).getAll('evidenceRevisionIds'),sha256:r.sha256,expectedVersion:project.promptRecipeVersion||0};
      return perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/prompt-recipes`,{method:'POST',body});removeDraft(`prompt-recipe:${selected}:${r.id}`);canvasDrawer={type:'recipes'};await load();announce('提示词规范已保存，原图和任务记录保留。');});
    }
    if(form.dataset.wfForm==='art-standard'){
      const notes=form.elements.notes.value,bundle=drafts.get(artBundleKey())||{},samples=resolvedArtSamples(bundle,project,assets);
      persist(artBundleKey(),{...bundle,notes});
      return perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/art-direction`,{method:'PUT',body:{notes,samples:Object.fromEntries(Object.entries(samples).map(([role,r])=>[role,{revisionId:r.id,sha256:r.sha256}])),expectedVersion:project.artDirection?.version||0,confirmStyle:true}});removeDraft(artBundleKey());await load();announce('全剧美术标准已确认。人物与场景画风已固定，可以继续制作主资产。');});
    }
    if(form.dataset.wfForm==='art-generation'){
      const role=canvasDrawer.role,inputs=Object.fromEntries(new FormData(form)),name=boardGenerationKey(),draft={...inputs,prepareKey:event.submitter?.hasAttribute('data-art-reroll')?key():drafts.get(name)?.prepareKey||key()};persist(name,draft);
      return perform(async()=>{
        if(drafts.get(planKey()))throw Error('请先保存资产清单草稿，再开始试做。');
        const model=selectedImageModel(draft,imageCatalog),samples=resolvedArtSamples(drafts.get(artBundleKey())||{},project,assets);
        const body={role,prompt:draft.prompt,settings:collectImageSettings(inputs,imageContracts[model.id]),modelId:model.id,expectedPlanVersion:plan.version,expectedSelectionRevision:session.selection.revision,expectedArtDirectionVersion:project.artDirection?.version||0,...(role==='trial'?{samples:Object.fromEntries(['character','scene'].filter(k=>samples[k]).map(k=>[k,{revisionId:samples[k].id,sha256:samples[k].sha256}]))}:{})};
        const submit=async i=>{const r=await api.request(`/projects/${encodeURIComponent(selected)}/art-studies/prepare`,{method:'POST',body:{...body,idempotencyKey:draft.prepareKey+':group:'+i}});if(!r.confirmation)throw Error(r.task?.error?.message||'尚未准备完成，请查看原任务。');return r;};
        const first=await submit(0),rest=await parallelGroups(Array.from({length:batchSize(inputs.groups)-1},(_,i)=>i+1),submit),ready=[first,...rest.filter(r=>r.status==='fulfilled').map(r=>r.value)];
        prepared={...first,batch:ready};selectedEntity=first.task.entityId;await load();announce(`已准备 ${ready.length} 组美术候选，核对费用后一起提交。${rest.some(r=>r.status==='rejected')?'部分组未准备完成，本次仅提交清单内的组。':''}`);
      });
    }
    if(form.dataset.wfForm==='art-direction'){
      const body=Object.fromEntries(new FormData(form));persist(`art-direction:${selected}`,body);
      const asset=assets.find(a=>a.revisions.some(r=>r.id===body.revisionId)),r=asset?.revisions.find(r=>r.id===body.revisionId);if(!r)return;
      return perform(async()=>{
        if(r.review!=='approved')await api.request(`/assets/${encodeURIComponent(asset.id)}/reviews`,{method:'POST',body:{revisionId:r.id,sha256:r.sha256,decision:'approved',note:'人工选用为本剧统一风格',expectedVersion:asset.version}});
        await api.request(`/projects/${encodeURIComponent(selected)}/art-direction`,{method:'PUT',body:{...body,sha256:r.sha256,expectedVersion:project.artDirection?.version||0,confirmStyle:true}});
        removeDraft(`art-direction:${selected}`);await load();announce('本剧风格已确认，后续制作会沿用这份美术规范。');
      });
    }
    if(form.dataset.wfForm==='board-generation'){
      const view={...boardView()},inputs=Object.fromEntries(new FormData(form)),name=boardGenerationKey();
      if(event.submitter?.hasAttribute('data-generation-missing-shots')||event.submitter?.hasAttribute('data-generation-repair-shots'))return perform(async()=>{
        const repair=event.submitter.hasAttribute('data-generation-repair-shots');
        if(drafts.get(`production:review:${production?.id}`)||drafts.get(`production:edits:${production?.id}`))throw new Error('请先保存镜头编排，再批量准备分镜。');
        tasks=(await loadTasks(selected)).items;taskError='';
        const result=returnedResult(production),explicit=event.submitter.hasAttribute('data-generation-selected-shots'),chosenShots=new FormData(form).getAll('shotIds');
        if(explicit&&(!chosenShots.length||chosenShots.length>8))throw Error('请勾选 1 至 8 个镜头。');
        const eligible=(repair?repairStoryboardShots:missingStoryboardShots)({job:production,result,assets,tasks,selection:session.selection,limit:explicit?Infinity:8},referenceCards),targets=explicit?eligible.filter(r=>chosenShots.includes(r.shot.id)):eligible;
        if(explicit&&targets.length!==chosenShots.length)throw Error('部分镜头状态已变化，请重新核对可生成的镜头；本次尚未准备。');
        if(!targets.length)throw new Error(repair?'没有可批量返修的镜头。只包含最新图片已退回、参考齐全且没有处理中或待核对任务的镜头。':'没有可批量准备的镜头。请先固定参考；已有图片或任务请逐镜查看，避免重复生成。');
        const chosen=selectedImageModel(inputs,imageCatalog),settings=collectImageSettings(inputs,imageContracts[chosen.id]);
        const batchKey=key(),ready=[],failed=[];
        await parallelGroups(targets,async({shot,index})=>{
          announce(`正在准备镜头 ${String(index+1).padStart(3,'0')}；本批 ${targets.length} 镜，尚未提交收费生成。`);
          try{
            let response;
            // Archive writes use optimistic plan versions; only a definite
            // pre-submit conflict retries, always under the same idempotency key.
            for(let attempt=0;attempt<3;attempt++){
              const currentPlan=await api.request(`/projects/${encodeURIComponent(selected)}/plan`);
              const c=generationContext({result,job:production,view:{kind:'shots',index,stage:'storyboard'},assets,selection:session.selection});
              try{response=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/images/prepare`,{method:'POST',body:{
                recipe:'image25_storyboard',modelId:chosen.id,prompt:c.prompt,settings,shotId:shot.id,
                expectedReviewVersion:production.reviewVersion,expectedEditVersion:production.editVersion,expectedPlanVersion:currentPlan.version,
                expectedSelectionRevision:session.selection.revision,expectedArtDirectionVersion:project.artDirection?.version||0,
                idempotencyKey:batchKey+':shot:'+shot.id}});break;}catch(e){if(e.code!=='VERSION_CONFLICT'||attempt===2)throw e;}
            }
            if(!response?.confirmation)throw Error(response?.task?.error?.message||'准备未完成');
            ready.push({...response,targetName:`镜头 ${String(index+1).padStart(3,'0')} · ${shot.purpose}`,shotIndex:index});
          }catch(e){failed.push(`镜头 ${String(index+1).padStart(3,'0')}：${e.message}`);}
        });
        ready.sort((a,b)=>a.shotIndex-b.shotIndex);
        prepared=ready.length?{...ready[0],batch:ready,multipleShots:true}:null;
        await load();announce(`已准备 ${ready.length} 个镜头，使用各镜已保存提示词与固定参考。${failed.length?failed.join('；'):repair?'返修会新建生成任务，核对清单与费用后一起提交。':'核对清单后一起提交生成。'}`);
      });
      const groups=batchSize(inputs.groups);
      const draft={...inputs,prepareKey:event.submitter?.hasAttribute('data-generation-reroll')?key():drafts.get(name)?.prepareKey||key()};persist(name,draft);
      return perform(async()=>{
        if(drafts.get(planKey()))throw new Error('资产清单还有未保存的手工修改，请先保存，避免覆盖。');
        if(drafts.get(`production:review:${production.id}`)||drafts.get(`production:edits:${production.id}`))throw new Error('请先保存镜头编排，或暂存草稿后使用已保存方案生成。');
        const c=generationContext({result:returnedResult(production),job:production,view,assets,selection:session.selection,generationDraft:draft});
        const chosen=selectedImageModel(draft,imageCatalog),settings=collectImageSettings(inputs,imageContracts[chosen.id]);
        const supplemental=extraReferences(inputs.extraReferences);
        const body={recipe:c.mode.recipe,modelId:chosen.id,prompt:[referencePrompt(supplemental),inputs.prompt].filter(Boolean).join('\n'),settings,extraReferenceIds:supplemental.map(r=>r.id),
          expectedReviewVersion:production.reviewVersion,expectedEditVersion:production.editVersion,expectedPlanVersion:plan.version,
          expectedSelectionRevision:session.selection.revision,idempotencyKey:draft.prepareKey,expectedArtDirectionVersion:project.artDirection?.version||0,
          ...(c.shot?{shotId:c.shot.id}:{assetId:c.asset.id,stateId:c.state.id,sourceRevisionIds:inputs.sourceRevisionId?[inputs.sourceRevisionId]:[]})};
        const endpoint=`/production-jobs/${encodeURIComponent(production.id)}/images/prepare`;
        const prepareGroup=async i=>{const response=await api.request(endpoint,{method:'POST',body:{...body,idempotencyKey:draft.prepareKey+':group:'+i},quietProgress:true});if(!response.confirmation)throw new Error(response.task?.error?.message||'准备未完成，请查看原任务记录。');return response;};
        // The first group establishes the archive once, before siblings prepare.
        const first=await prepareGroup(0);
        const rest=await parallelGroups(Array.from({length:groups-1},(_,i)=>i+1),prepareGroup);
        const ready=[first,...rest.filter(r=>r.status==='fulfilled').map(r=>r.value)],failed=rest.filter(r=>r.status==='rejected');
        prepared={...first,batch:ready};selectedEntity=first.task.entityId;await load();
        announce(`已准备 ${ready.length} 组，共 ${ready.reduce((n,r)=>n+r.confirmation.summary.count,0)} 张。${failed.length?failed.length+' 组未准备成功，原记录保留；本次只确认已准备的组。':'核对后可一起提交生成。'}`);
      });
    }
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
      const draft=captureCompose(form);
      persist(composeKey(),draft);
      const problem=promptIssue({draft,job:entityPrompt(),entity:currentEntity(),styleVersion:plan.styleVersion});
      if(problem||!form.elements.promptReviewed?.checked){announce(problem||'请先核对完整提示词并勾选确认。');return;}
      const prompt=draft.prompt;
      const body={projectId:selected,entityId:selectedEntity,recipe:recipes[page],prompt,sourceRevisionIds:page==='style'?[]:[draft.sourceRevisionId],settings:{count:Number(draft.count),...(draft.ratio?{ratio:draft.ratio}:{})},expectedSelectionRevision:session.selection.revision,...(draft.repairOfRevisionId?{repairOfRevisionId:draft.repairOfRevisionId}:{})};
      return perform(async()=>{prepared=await api.request('/tasks/prepare',{method:'POST',body,idempotencyKey:draft.prepareKey});if(!prepared.confirmation){announce(prepared.task?.error?.message||'准备未完成，请查看任务记录。');prepared=null;}else announce('任务准备记录已保存，请核对原账号、空间和费用。');events.dispatchEvent(new CustomEvent('tasks:changed',{detail:{projectId:selected}}));await load();});
    }
  }
  async function onClick(event) {
    const button=event.target.closest('button,a');if(!button||button.disabled)return;
    if(button.hasAttribute('data-version-select')){const r=assets.flatMap(a=>a.revisions).find(r=>r.id===button.dataset.versionSelect);if(r&&(r.status!=='ready'||r.review==='approved')){openReview(r.id,button);return;}return decide('approved',{revisionId:button.dataset.versionSelect,note:'人工点击版本图片选用',keepOpen:true});}
    if(button.hasAttribute('data-version-confirm'))return decide('approved',{revisionId:button.dataset.versionConfirm,note:'人工核对当前镜头方案，确认旧版画面仍适用并选用',keepOpen:true,confirmCurrentBasis:true});
    if(button.hasAttribute('data-version-nano')){startReroll(button.dataset.versionNano,'nano');return;}
    if(button.hasAttribute('data-version-reroll')){startReroll(button.dataset.versionReroll);return;}
    if(button.hasAttribute('data-version-cancel')){rerollId=null;render();return;}
    if(button.hasAttribute('data-extra-reference-remove')){
      const form=button.closest('form'),inputs=Object.fromEntries(new FormData(form));
      const refs=extraReferences(inputs.extraReferences).filter(r=>r.id!==button.dataset.extraReferenceRemove);
      persist(boardGenerationKey(),{...inputs,extraReferences:JSON.stringify(refs),prepareKey:key()});render();return;
    }
    if(button.hasAttribute('data-reference-unpin')){
      const si=Number(button.dataset.referenceShot),shot=structuredClone(currentProduction().shots[si]);
      delete shot.references[Number(button.dataset.referenceUnpin)].revisionId;
      changeProductionField(`shots.${si}.references`,shot.references);render();return;
    }
    if(button.hasAttribute('data-library-open')){await loadLibrary();return;}
    if(button.hasAttribute('data-library-close')){librarySerial++;remoteLibrary.open=false;render();return;}
    if(button.hasAttribute('data-library-asset')){const serial=++librarySerial;remoteLibrary.loading=true;remoteLibrary.error='';render();try{const detail=await api.request('/libtv-assets?projectId='+encodeURIComponent(selected)+'&assetId='+encodeURIComponent(button.dataset.libraryAsset),{quietProgress:true});if(serial===librarySerial)remoteLibrary.detail=detail;}catch(e){if(serial===librarySerial)remoteLibrary.error=e.message;}finally{if(serial===librarySerial){remoteLibrary.loading=false;render();}}return;}
    if(button.hasAttribute('data-library-import')){const item=remoteLibrary.detail;if(!item)return;return perform(async()=>{const reply=await api.request(`/projects/${encodeURIComponent(selected)}/library-references`,{method:'POST',body:{assetId:item.id,expectedAssetVersion:item.version,imageIndex:Number(button.dataset.libraryImport),expectedSelectionRevision:session.selection.revision}});remoteLibrary.open=false;await load();openReview(reply.revision.id);announce('素材库图片已保存为项目参考，请看图确认。');});}
    if(button.hasAttribute('data-canvas-recipes')){openCanvasPanel({type:'recipes'},button);return;}
    if(button.hasAttribute('data-prompt-save')){reviewId=null;openCanvasPanel({type:'recipes',revisionId:button.dataset.promptSave},button);return;}
    if(button.hasAttribute('data-prompt-use')){const recipe=project.promptRecipes?.find(r=>r.id===button.dataset.promptUse),c=generationContext({result:currentProduction(),job:production,view:boardView(),assets,selection:session.selection});if(recipe){persist(boardGenerationKey(),{...(drafts.get(boardGenerationKey())||{}),prompt:recipe.prompt.replaceAll('{{主体}}',c.asset?.name||c.shot?.purpose||'当前对象').replaceAll('{{参考图}}','（以本次所选参考图为准）'),prepareKey:key()});render();announce('已载入可编辑的要求；请核对当前对象、模型和参考，再准备生成。');}return;}
    if(button.hasAttribute('data-canvas-return-shot')){const shotId=button.dataset.canvasReturnShot;closeCanvasPanel();storyCanvas.locateShot(shotId);return;}
    if(button.hasAttribute('data-canvas-batch')){openCanvasPanel({type:'batch'},button);return;}
    if(button.hasAttribute('data-canvas-preview')){if(production)boardViews.set(production.id,{kind:'shots',index:0,inspector:'preview',stage:'storyboard'});openCanvasPanel({type:'production',phase:'production'},button);return;}
    if(button.hasAttribute('data-canvas-close')){closeCanvasPanel();return;}
    if(button.hasAttribute('data-canvas-art')){openCanvasPanel({type:'art',role:button.dataset.canvasArt},button);return;}
    if(button.hasAttribute('data-art-pick')){
      const r=assets.flatMap(a=>a.revisions).find(r=>r.id===button.dataset.artPick),role=button.dataset.artRole;if(!r||r.status!=='ready')return;
      if(r.review!=='approved')await decide('approved',{revisionId:r.id,note:'人工点选为全剧'+role+'试做样板'});
      const approved=assets.flatMap(a=>a.revisions).find(v=>v.id===r.id&&v.review==='approved'&&v.status==='ready');if(!approved)return;
      const bundle=drafts.get(artBundleKey())||{};persist(artBundleKey(),{...bundle,samples:{...(bundle.samples||{}),[role]:{revisionId:r.id,sha256:r.sha256}}});render();announce('已选好样板。三项试做都选定后，再确认全剧美术标准。');return;
    }
    if(button.hasAttribute('data-canvas-material')){openCanvasPanel({type:'material',id:button.dataset.canvasMaterial},button);return;}
    if(button.hasAttribute('data-overview-shot')){
      const index=Number(button.dataset.overviewShot);if(!returnedResult(production)?.shots[index])return;
      boardViews.set(production.id,{kind:'shots',index,inspector:button.hasAttribute('data-overview-generate')?'generate':'shots',stage:'storyboard'});openCanvasPanel({type:'production',phase:'production'},button);return;
    }
    if(button.hasAttribute('data-overview-asset')){
      const index=Number(button.dataset.overviewAsset),state=Number(button.dataset.overviewState);if(!returnedResult(production)?.assets[index]?.states[state])return;
      boardViews.set(production.id,{kind:'assets',index,state,inspector:'generate',stage:'asset',characterLayer:button.dataset.overviewMaster==='true'?'master':'state'});navigate('asset');return;
    }
    if(button.hasAttribute('data-image-models-refresh')){await loadImageModels(true);return;}
    if(button.hasAttribute('data-wf-download')){event.preventDefault();const url=new URL(button.href);const relative=url.pathname.slice(apiBase.length);if(relative.endsWith('/storyboard-export')&&drafts.get(`production:review:${production?.id}`)){announce('请先保存镜头编排，再下载图文分镜脚本。');return;}return perform(async()=>{const blob=await api.request(relative,{responseType:'blob'});const link=doc.createElement('a');const objectUrl=URL.createObjectURL(blob);link.href=objectUrl;link.download=relative.endsWith('/storyboard-export')?'分镜脚本与图片.zip':'asset-lab-approved-assets.zip';link.hidden=true;doc.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),60000);announce('交付包已交给浏览器下载。');});}
    if(button.hasAttribute('data-director-reference')){if(Date.now()<suppressDirectorClickUntil)return;insertDirectorAsset(button.dataset.directorReference,button.dataset.directorState,button.dataset.directorRevision,boardView().index||0);return;}
    if(button.hasAttribute('data-generation-use-saved')){
      const form=button.closest('form'),inputs=Object.fromEntries(new FormData(form));
      if(drafts.get(`production:review:${production?.id}`)||drafts.get(`production:edits:${production?.id}`)){announce('请先保存镜头编排，再载入镜头要求。');return;}
      const c=generationContext({result:returnedResult(production),job:production,view:boardView(),assets,selection:session.selection});
      if(!c.shot)return;
      persist(boardGenerationKey(),{...inputs,prompt:c.prompt,prepareKey:key()});render();announce('已载入当前保存的镜头要求、首帧状态与连续性；原分镜内容未改动。');return;
    }
    if(button.hasAttribute('data-character-layer')){updateBoard({characterLayer:button.dataset.characterLayer,stage:'asset'});return;}
    if(button.hasAttribute('data-creator-select')){updateBoard({index:Number(button.dataset.creatorSelect),kind:'assets',state:0,characterLayer:'master'});return;}
    if(button.hasAttribute('data-creator-go-stage')){const next=button.dataset.creatorGoStage;if(next==='asset')boardViews.set(production.id,{...boardView(),stage:'asset'});return navigate(next,{object:true});}
    if(button.hasAttribute('data-creator-direction')){persist(`art-direction:${selected}`,{revisionId:button.dataset.creatorDirection});render();root.querySelector('.creator-direction')?.scrollIntoView({block:'center'});return;}
    if(button.hasAttribute('data-creator-direction-cancel')){removeDraft(`art-direction:${selected}`);render();return;}
    if(button.hasAttribute('data-creator-keep')){
      const asset=assets.find(a=>a.revisions.some(r=>r.id===button.dataset.creatorKeep)),r=asset?.revisions.find(r=>r.id===button.dataset.creatorKeep);if(!r||r.status!=='ready'||r.review==='approved')return;
      return decide('approved',{revisionId:r.id,note:'人工点击候选图选用此版本'});
    }
    if(button.hasAttribute('data-production-bind')){
      if(drafts.get(planKey())||drafts.get(`production:review:${production?.id}`)||drafts.get(`production:edits:${production?.id}`)){announce('请先保存清单和方案修改，再关联已有档案。');return;}
      const entity=plan.entities.find(e=>e.id===button.dataset.productionBind);if(!entity||!production)return;
      const body={assetId:button.dataset.bindingAsset,stateId:button.dataset.bindingState,entityId:entity.id,
        expectedPlanVersion:plan.version,expectedEntityVersion:entity.version,expectedReviewVersion:production.reviewVersion,
        expectedEditVersion:production.editVersion,expectedBindingVersion:production.bindingVersion,confirmApplicable:true};
      return perform(async()=>{production=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/bindings`,{method:'PUT',body});await load();announce('已有档案已关联，原图与审核状态保留。');});
    }
    if(button.hasAttribute('data-board-generate')){if(canvasDrawer)canvasDrawer.phase=button.dataset.boardGenerate==='assets'?'asset':'production';if(button.dataset.boardGenerate==='assets'&&page==='production'){boardViews.set(production.id,{...boardView(),returnShot:boardView().returnShot??boardView().index??0});page='asset';persist('page',page);}updateBoard({inspector:'generate',kind:button.dataset.boardGenerate,index:Number(button.dataset.boardIndex),state:Number(button.dataset.boardStateIndex)||0,characterLayer:'state',stage:button.dataset.boardGenerate==='shots'?'storyboard':'style'});return;}
    if(button.hasAttribute('data-board-generation-stage')){updateBoard({stage:button.dataset.boardGenerationStage});return;}
    if(button.hasAttribute('data-board-reference-open')){
      const result=currentProduction(),index=Number(button.dataset.boardReferenceOpen);if(!result?.assets[index])return;
      const si=result.shots.findIndex(s=>s.id===button.dataset.shotId),ref=result.shots[si]?.references.find(r=>r.assetId===result.assets[index].id);
      updateBoard({kind:'assets',inspector:'assets',index,state:Math.max(0,result.assets[index].states.findIndex(s=>s.id===ref?.stateId)),returnShot:si});return;
    }
    if(button.hasAttribute('data-board-reference-picker')){openReferencePicker(button.dataset.boardReferencePicker);return;}
    if(button.hasAttribute('data-board-reference-picker-close')){button.closest('[data-reference-picker]').hidden=true;referenceCursor=null;return;}
    if(button.hasAttribute('data-reference-insert')){
      const path=button.dataset.referencePath,result=structuredClone(currentProduction()),si=Number(path.split('.')[1]),shot=result.shots[si],asset=result.assets.find(a=>a.id===button.dataset.referenceInsert);
      const input=[...root.querySelectorAll('[data-reference-text]')].find(n=>n.dataset.wfProductionField===path);if(!input)return;
      const oldShot=structuredClone(shot),cursor=referenceCursor?.path===path?referenceCursor:{start:input.value.length,end:input.value.length};
      const prefix=storedText(input.value.slice(0,cursor.start),result,oldShot),suffix=storedText(input.value.slice(cursor.end),result,oldShot);
      if(!bindReference(shot,asset,button.dataset.referenceState)){announce('该状态不适用本场次，或镜头引用已满。');return;}
      if(button.dataset.referenceImage){
        const card=pickerCards(result).find(c=>c.assetId===asset.id&&c.stateId===button.dataset.referenceState);
        if(!card?.versions.some(r=>r.id===button.dataset.referenceImage)){announce('这张参考图已不可用，请重新选择。');return;}
        shot.references.find(r=>r.assetId===asset.id).revisionId=button.dataset.referenceImage;
      }
      const value=prefix+assetToken(asset.id)+suffix;
      if(value.length>Number(input.maxLength)){announce('描述已达到容量上限，请先缩短内容。');return;}
      changeProductionField(`shots.${si}.references`,shot.references);changeProductionField(path,value);referenceCursor=null;render();
      const next=[...root.querySelectorAll('[data-reference-text]')].find(n=>n.dataset.wfProductionField===path);if(next){next.closest('details')?.setAttribute('open','');next.focus();const caret=readableText(prefix+assetToken(asset.id),result,shot).length;next.setSelectionRange(caret,caret);}
      announce(`已引用 ${asset.name}，画布连线同步更新。保存后保留到项目。`);return;
    }
    if(button.hasAttribute('data-reference-remove')){
      const si=Number(button.dataset.referenceShot),shot=structuredClone(currentProduction().shots[si]),ref=shot.references[Number(button.dataset.referenceRemove)];
      if(!removeReference(shot,ref.assetId)){announce('描述或提示词仍在使用这项物料，请先删除对应的括号标签。');return;}
      changeProductionField(`shots.${si}.references`,shot.references);render();return;
    }
    if(button.hasAttribute('data-prop-create')){
      const form=button.closest('details'),name=form.querySelector('[data-prop-name]').value.trim(),design=form.querySelector('[data-prop-design]').value.trim(),prompt=form.querySelector('[data-prop-prompt]').value.trim();
      if(!name||!design||prompt.length<20){announce('请填写道具名称、外观与结构，以及至少 20 字的完整提示词。');return;}
      const result=structuredClone(currentProduction()),si=Number(button.dataset.propCreate),shot=result.shots[si];
      if(result.assets.length>=100||shot.references.length>=20){announce('本方案物料或本镜引用已达到上限，请先整理。');return;}
      const asset=appendManualProp(result,si,{id:'manual_'+key().replaceAll('-',''),name,design,prompt});if(!asset)return;
      changeProductionField('assets',result.assets);changeProductionField(`shots.${si}.references`,shot.references);render();announce(`已补充道具 ${name} 并连到本镜。可用 @ 插入物料将它放入描述。`);return;
    }
    if(button.hasAttribute('data-reference-check')){
      if(drafts.get(`production:review:${production.id}`)){announce('请先保存当前修改，再检查已保存方案的参考图。');return;}
      const si=Number(button.dataset.referenceCheck),id=production.id,shotId=currentProduction().shots[si].id;button.disabled=true;
      try {const packet=await api.request(`/production-jobs/${encodeURIComponent(id)}/shots/${encodeURIComponent(shotId)}/references`);
        if(production?.id!==id||boardView().inspector!=='shots'||boardView().index!==si)return;
        const target=root.querySelector('[data-reference-check-result]');if(target)target.innerHTML=`<div class="wf-note"><b>${packet.ready?'本镜参考图已备齐':'参考图还未备齐'}</b><p>${packet.readyCount} / ${packet.references.length} 张可用 · 尚未提交生图</p>${packet.references.filter(r=>r.issue).map(r=>`<p>${esc(r.name)}：${esc(r.issue)}</p>`).join('')}<details><summary>查看带引用的分镜提示词</summary><p>${esc(packet.prompt)}</p></details></div>`;
      }catch(e){announce(e.message||'检查失败，请重试。');}finally{if(button.isConnected)button.disabled=false;}return;
    }
    if(button.dataset.boardZoom){canvas.command(button.dataset.boardZoom);return;}
    if(button.dataset.boardLocate){canvas.locate(button.dataset.boardLocate);return;}
    if(button.dataset.boardSelect){if(canvasDrawer)canvasDrawer.phase='production';updateBoard({kind:button.dataset.boardSelect,inspector:button.dataset.boardSelect,index:Number(button.dataset.boardIndex),state:0});return;}
    if(button.dataset.boardInspector){updateBoard({inspector:button.dataset.boardInspector});return;}
    if(button.hasAttribute('data-board-state')){updateBoard({state:Number(button.dataset.boardState)});return;}
    if(button.hasAttribute('data-board-close')){if(canvasDrawer)closeCanvasPanel();else updateBoard({inspector:null});return;}
    if(button.hasAttribute('data-board-focus')){updateBoard({focus:!boardView().focus});return;}
    if(button.dataset.wfNav)return navigate(button.dataset.wfNav);
    if(button.dataset.wfEntity){selectedEntity=button.dataset.wfEntity;persist('selectedEntity',selectedEntity);const result=returnedResult(production),binding=production?.bindings?.find(b=>b.entityId===selectedEntity);if(binding){boardViews.set(production.id,{kind:'assets',index:result.assets.findIndex(a=>a.id===binding.assetId),state:Math.max(0,result.assets.find(a=>a.id===binding.assetId)?.states.findIndex(s=>s.id===binding.stateId)||0),characterLayer:binding.stateId.startsWith('__')?'master':'state',stage:button.dataset.wfStage});return navigate(button.dataset.wfStage,{object:true});}openCanvasPanel({type:'art',role:'standard'});announce('这份独立档案可从已有候选中选用，或在具体物料中明确关联。');return;}
    if(button.dataset.wfArchive){selectedEntity=button.dataset.wfArchive;persist('selectedEntity',selectedEntity);return navigate('review');}
    if(button.dataset.wfReview)return openReview(button.dataset.wfReview,button);
    if(button.dataset.wfRepair)return repair(button.dataset.wfRepair);
    if(button.dataset.wfRemove!==undefined){const draft=drafts.get(planKey());if(draft){draft.entities.splice(Number(button.dataset.wfRemove),1);persist(planKey(),draft);render();}return;}
    if(button.dataset.wfCancel){const task=tasks.find(t=>t.id===button.dataset.wfCancel);if(!task||task.submissionAttempted)return;return perform(async()=>{await api.request(`/tasks/${encodeURIComponent(task.id)}/cancel`,{method:'POST',body:{expectedVersion:task.version}});prepared=null;const draft=drafts.get(composeKey());if(draft)persist(composeKey(),{...draft,prepareKey:key()});const boardDraft=drafts.get(boardGenerationKey());if(boardDraft)persist(boardGenerationKey(),{...boardDraft,prepareKey:key()});announce('未提交的准备记录已取消；原记录仍保留。');await load();});}
    if(button.dataset.wfConfirmTask){const task=tasks.find(t=>t.id===button.dataset.wfConfirmTask);if(!task)return;return perform(async()=>{prepared=await api.request(`/tasks/${encodeURIComponent(task.id)}/confirm`,{method:'POST',body:{expectedVersion:task.version}});announce('请核对原任务的账号、参考和费用。');});}
    if(button.dataset.wfRecover){const task=tasks.find(t=>t.id===button.dataset.wfRecover);if(!task||busy)return;recoveringTask=true;try{return await perform(async()=>{await api.request(`/tasks/${encodeURIComponent(task.id)}/recover`,{method:'POST',body:{expectedVersion:task.version}});announce('已查询原任务；没有重新发起生成。');await load();});}finally{recoveringTask=false;render();}}
    if(button.dataset.wfPromptView){const job=promptJobs.find(j=>j.id===button.dataset.wfPromptView);if(job?.entityId===currentEntity()?.id){persist(`prompt-view:${selected}:${job.entityId}`,job.id);render();}return;}
    if(button.hasAttribute('data-story-scene')){storyCanvas.locate(Number(button.dataset.storyScene));return;}
    if(button.dataset.wfAnalysisRecord){
      storyCanvas.exitFocus();
      const record=[...root.querySelectorAll('[data-analysis-record]')].find(n=>n.dataset.analysisRecord===button.dataset.wfAnalysisRecord);
      if(record){for(let node=record;node&&node!==root;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;const edit=record.querySelector(':scope > details');if(edit)edit.open=true;record.scrollIntoView({block:'start'});record.querySelector('textarea,input,select')?.focus({preventScroll:true});}return;
    }
    if(button.dataset.wfAnalysisGroup){const group=root.querySelector('#analysis-'+button.dataset.wfAnalysisGroup);if(group){group.open=true;group.scrollIntoView({behavior:'smooth',block:'start'});}return;}
    if(button.dataset.wfSource){storyCanvas.exitFocus();if(page==='production')navigate('plan');const source=root.querySelector(`[data-wf-script="${scripts.at(-1)?.id}"]`);if(source){source.open=true;source.querySelectorAll('[data-wf-line]').forEach(line=>line.classList.toggle('wf-source-active',Number(line.dataset.wfLine)>=Number(button.dataset.wfSource)&&Number(line.dataset.wfLine)<=Number(button.dataset.wfSourceEnd)));source.querySelector('.wf-source-active')?.scrollIntoView({behavior:'smooth',block:'center'});}return;}
    const action=button.dataset.wfAction;
    if(['production-preview-open','production-shots-open','production-assets-open','production-issues-open'].includes(action)){const section=action.split('-')[1],panel=root.querySelector(`[data-wf-production-${section}]`);if(panel){panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});}return;}
    if(action==='analysis-read-original'&&analysis)return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/read-original`,{method:'POST',body:{}});announce('正在读取原任务内容，没有重新生成。');});
    if(action==='analysis-use-source'&&analysis){const issue=analysis.validationIssues[Number(button.dataset.analysisIssue)];if(issue?.sourceText){changeAnalysisField(issue.path,issue.sourceText);button.textContent='已填入，保存后核对';}return;}
    if(action==='analysis-review-discard'&&analysis){removeDraft(`analysis:review:${analysis.id}`);render();return;}
    if(action==='analysis-review-save'&&analysis){
      const name=`analysis:review:${analysis.id}`,draft=drafts.get(name)||analysisDraft(analysis),body={...draft};
      if(body.raw!==undefined){try{body.result=JSON.parse(body.raw);}catch{announce('内容尚不是完整 JSON，修改仍保留，请补齐后保存。');return;}delete body.raw;}
      return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/review`,{method:'PUT',body});removeDraft(name);analysisError='';announce(analysis.validationIssues.length?`修改已保存，仍有 ${analysis.validationIssues.length} 处标红待核对。`:'修改已保存，原文核对通过，可以继续制作。');});
    }
    if(action==='production-open-review'){page='plan';canvasDrawer={type:'production',phase:'production'};persist('page',page);updateBoard({inspector:production.validationIssues?.length?'issues':'handoff'});root.querySelector('[data-production-review-panel]')?.scrollIntoView({block:'start'});return;}
    if(button.hasAttribute('data-shot-remove')){
      const result=currentProduction(),index=Number(button.dataset.shotRemove),shot=result.shots[index];
      if(!shot||shot.dialogueIds.length||shot.purpose!=='补充镜头 · 请编辑动作与构图')return;
      persist(`production:removed:${production.id}`,{index,shot});if(saveError)return;
      changeProductionField('shots',removeBlankShot(result,index).shots);updateBoard({inspector:'shots',index:Math.max(0,index-1)});
      announce('已从镜头草稿删除这条空白镜头，其他镜头保留；请保存镜头编排。');return;
    }
    if(action==='production-number-shots'){
      changeProductionField('shots',numberShots(currentProduction().shots));render();
      announce('已按当前播放顺序整理镜头编号，镜头内容与引用不变；请保存镜头编排。');return;
    }
    if(button.hasAttribute('data-shot-split')||button.hasAttribute('data-shot-add')){const index=Number(button.dataset.shotSplit??button.dataset.shotAdd),result=currentProduction();const edited=button.hasAttribute('data-shot-split')?splitShot(result,index,production.dialogues,()=>`shot_${crypto.randomUUID()}`):addShot(result,index,()=>`shot_${crypto.randomUUID()}`);changeProductionField('shots',edited.shots);updateBoard({inspector:'shots',index:button.hasAttribute('data-shot-add')?index+1:index});announce('镜头草稿已更新，请逐镜调整构图和动作后保存；原文台词未改写。');return;}
    if(action==='production-play')return preview.play();
    if(action==='production-pause')return preview.stop();
    if(action==='production-prev')return preview.jump(-1);
    if(action==='production-next')return preview.jump(1);
    if(action==='production-rewind')return preview.rewind();
    if(action==='open-production-plan'){if(production)boardViews.set(production.id,{...boardView(),inspector:production.validationIssues?.length?'issues':'handoff'});openCanvasPanel({type:'production',phase:'production'},button);return;}
    if(action==='production-start'){
      if(drafts.get(`analysis:review:${analysis?.id}`)){announce('请先保存分析修改，再整理制作清单。');return;}
      if(!root.querySelector('[data-wf-production-spend]')?.checked){announce('请先确认本次 AI 制作设计使用账号积分。');return;}
      const script=scripts.at(-1);if(!script||analysis?.status!=='ready')return;
      const ratio=root.querySelector('[data-wf-production-ratio]')?.value||'9:16',modelId=drafts.get('text-model')||capabilities.analysis?.defaultModelId;
      const requestName=`production:request:${script.id}:${analysis.id}:${session.selection.revision}:${modelId}:${ratio}:${production?.id||'first'}`;
      const idempotencyKey=drafts.get(requestName)||key();persist(requestName,idempotencyKey);
      return perform(async()=>{production=await api.request(`/projects/${encodeURIComponent(selected)}/scripts/${encodeURIComponent(script.id)}/production`,{method:'POST',body:{idempotencyKey,expectedSelectionRevision:session.selection.revision,confirmSpend:true,reanalyze:Boolean(production),modelId,analysisId:analysis.id,aspectRatio:ratio}});productionError='';announce('制作设计任务已保存，方案会自动返回。');});
    }
    if(action==='production-refresh'&&production)return perform(async()=>{production=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/refresh`,{method:'POST',body:{}});productionError='';});
    if(action==='production-revalidate'&&production)return perform(async()=>{production=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/revalidate`,{method:'POST',body:{}});announce('正在重新读取原结果进行核验，不会发起新的生成。');});
    if(action==='production-repair'&&production){if(!root.querySelector('[data-wf-production-repair-spend]')?.checked){announce('请确认本次修正增加 1 次 AI 调用。');return;}return perform(async()=>{production=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/repair`,{method:'POST',body:{confirmSpend:true}});announce('已保留原结果，让 AI 修正核验问题；本轮最多增加一次调用。');});}
    if(action==='production-retry'&&production)return perform(async()=>{production=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/retry-rejected`,{method:'POST',body:{}});});
    if(action==='production-use-source'&&production){
      const issue=production.validationIssues?.[Number(button.dataset.issueIndex)];
      if(!issue?.sourceText)return;
      changeProductionField(issue.path+'.quote',issue.sourceText);
      changeProductionField(issue.path+'.startLine',issue.startLine);
      changeProductionField(issue.path+'.endLine',issue.endLine);
      const message=root.querySelector(`[data-wf-issue-change="${Number(button.dataset.issueIndex)}"]`);
      if(message)message.textContent='已填入原文，保存后复核。';
      button.textContent='已采用原文';return;
    }
    if(action==='production-review-discard'&&production){removeDraft(`production:review:${production.id}`);removeDraft(`production:edits:${production.id}`);announce('已恢复上次保存的方案。');render();return;}
    if(action==='production-review-park'&&production){
      const prefix='production:',id=production.id,parked=prefix+'parked:'+id;
      if(drafts.get(parked)){announce('已有暂存草稿，请先继续编辑或保存。');return;}
      persist(parked,{review:drafts.get(prefix+'review:'+id),edits:drafts.get(prefix+'edits:'+id),reviewVersion:production.reviewVersion,editVersion:production.editVersion});
      if(saveError)return;
      removeDraft(prefix+'review:'+id);removeDraft(prefix+'edits:'+id);boardViews.delete(id);
      announce('草稿已保留，当前显示已保存方案。');render();return;
    }
    if(action==='production-review-resume'&&production){
      const id=production.id,name=`production:parked:${id}`,saved=drafts.get(name);
      if(!saved)return;
      if(saved.reviewVersion!==production.reviewVersion||saved.editVersion!==production.editVersion){announce('已保存方案有新版本，暂存草稿仍完整保留；请先核对差异，避免覆盖。');return;}
      if(saved.review){persist(`production:review:${id}`,saved.review);if(saveError)return;}
      if(saved.edits){persist(`production:edits:${id}`,saved.edits);if(saveError)return;}
      removeDraft(name);boardViews.delete(id);announce('已恢复暂存草稿，可继续编辑。');render();return;
    }
    if(action==='production-review-save'&&production&&returnedResult(production)){
      const name=`production:review:${production.id}`,draft=drafts.get(name)||reviewDraft(production,drafts.get(`production:edits:${production.id}`));
      return perform(async()=>{
        production=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/review`,{method:'PUT',body:draft});
        removeDraft(name);removeDraft(`production:edits:${production.id}`);productionError='';
        announce(production.validationIssues?.length?`修改已保存，还剩 ${production.validationIssues.length} 处待核对；可继续修改。`:'修改已保存，引用与关联检查通过，可以继续制作。');
      });
    }
    if(action==='production-plan'&&production?.status==='ready'){
      if(drafts.get(`production:review:${production.id}`)||drafts.get(`production:edits:${production.id}`)){announce('请先保存当前方案修改，再加入资产清单。');return;}
      if(!root.querySelector('[data-wf-production-reviewed]')?.checked){announce('请先核对物料、状态和创作建议。');return;}
      if(drafts.get(planKey())){announce('已有未保存的清单草稿，请先确认保存，再加入新物料。');return navigate('plan');}
      return perform(async()=>{const candidate=await api.request(`/production-jobs/${encodeURIComponent(production.id)}/plan`);persist(planKey(),{expectedVersion:candidate.expectedVersion,entities:candidate.entities.map(cleanEntity),stylePrompt:candidate.stylePrompt});editing=true;page='plan';persist('page',page);announce(`新增 ${candidate.addedCount} 个状态物料已加入清单草稿；原有条目保留，请核对并保存。`);});
    }
    if(action==='continue')return continueFlow();
    if(action==='prompt-use'){
      const job=entityPrompt();if(!usablePrompt(job))return;
      const current=getCompose();
      if(current?.prompt&&!current.promptJobId)persist(`prompt-backup:${selected}:${selectedEntity}:${page}`,current);
      persist(composeKey(),{...current,prompt:job.result.prompts[page],promptJobId:job.id,manualPrompt:false,prepareKey:key()});
      announce('AI 提示词已填入下方。请核对原文事实与视觉选择，可以继续编辑；尚未提交生图。');render();return;
    }
    if(action==='prompt-retry-rejected'&&entityPrompt())return perform(async()=>{const job=await api.request(`/prompt-jobs/${encodeURIComponent(entityPrompt().id)}/retry-rejected`,{method:'POST',body:{}});promptJobs=promptJobs.map(j=>j.id===job.id?job:j);});
    if(action==='prompt-refresh'&&entityPrompt())return perform(async()=>{const job=await api.request(`/prompt-jobs/${encodeURIComponent(entityPrompt().id)}/refresh`,{method:'POST',body:{}});promptJobs=promptJobs.map(j=>j.id===job.id?job:j);promptError='';});
    if(action==='prompt-generate'){
      const entity=currentEntity();if(!entity)return;
      const modelId=drafts.get('text-model')||capabilities.analysis?.defaultModelId;
      const previous=entityPrompt();
      const requestName=`prompt:${selected}:${entity.id}:${entity.version}:${plan.styleVersion}:${modelId}:${session.selection.revision}:${previous?.id||'first'}`;
      const idempotencyKey=drafts.get(requestName)||key();persist(requestName,idempotencyKey);
      return perform(async()=>{const job=await api.request(`/projects/${encodeURIComponent(selected)}/entities/${encodeURIComponent(entity.id)}/prompts`,{method:'POST',body:{idempotencyKey,expectedSelectionRevision:session.selection.revision,confirmSpend:true,reanalyze:Boolean(previous),modelId}});promptJobs=[job,...promptJobs.filter(j=>j.id!==job.id)];removeDraft(`prompt-view:${selected}:${entity.id}`);promptError='';announce('AI 提示词请求已保存，结果会自动返回到当前资产。');});
    }
    if(action==='analyze'){
      if(!root.querySelector('[data-wf-analysis-spend]')?.checked){announce('请先确认本次 AI 分析使用当前账号积分。');return;}
      const script=scripts.at(-1);if(!script)return;
      const modelId=drafts.get('text-model')||capabilities.analysis?.defaultModelId;
      const requestName=`analysis:${script.id}:${session.selection.revision}:${modelId}:${analysis?.id||'first'}`;
      const idempotencyKey=drafts.get(requestName)||key();persist(requestName,idempotencyKey);
      return perform(async()=>{analysis=await api.request(`/projects/${encodeURIComponent(selected)}/scripts/${encodeURIComponent(script.id)}/analyze`,{method:'POST',body:{idempotencyKey,expectedSelectionRevision:session.selection.revision,confirmSpend:true,reanalyze:Boolean(analysis),modelId}});analysisError='';announce('AI 分析请求已保存，状态将在这里持续更新。');});
    }
    if(action==='analysis-retry-rejected'&&analysis)return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/retry-rejected`,{method:'POST',body:{}});});
    if(action==='analysis-repair'&&analysis)return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/repair`,{method:'POST',body:{confirmSpend:true}});});
    if(action==='analysis-review-original'&&analysis)return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/review-original`,{method:'POST',body:{}});});
    if(action==='analysis-refresh'&&analysis)return perform(async()=>{analysis=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/refresh`,{method:'POST',body:{}});analysisError='';});
    if(action==='analysis-plan'&&analysis?.status==='ready'){
      if(!root.querySelector('[data-wf-analysis-reviewed]')?.checked){announce('请先对照原文核对分析结果和待确认问题。');return;}
      return perform(async()=>{const candidate=await api.request(`/analyses/${encodeURIComponent(analysis.id)}/plan`);persist(planKey(),{expectedVersion:candidate.expectedVersion,entities:candidate.entities,stylePrompt:candidate.stylePrompt});editing=true;page='plan';announce(candidate.hasExistingPlan?'AI 草稿已打开；保存时将更新当前资产清单，请核对原有条目是否需要保留。':'AI 角色与地点草稿已打开，请核对设定和视觉风格后保存。');});
    }
    if(action==='connect'){events.dispatchEvent(new CustomEvent('workflow:connect'));return;}
    if(action==='refresh')return perform(()=>load());
    if(action==='new-project'){canvasDrawer=null;production=null;productionError='';analysis=null;analysisError='';promptJobs=[];promptError='';creating=true;project=null;selected='';selectedEntity='';plan={version:0,entities:[],stylePrompt:''};assets=[];scripts=[];tasks=[];bundles=[];coverage={total:0,ready:0,complete:false};reviewId=null;prepared=null;render();root.querySelector('input[name=name]')?.focus();return;}
    if(action==='edit-plan'){editing=true;if(!drafts.get(planKey()))persist(planKey(),{expectedVersion:plan.version,entities:plan.entities.map(cleanEntity),stylePrompt:plan.stylePrompt});render();return;}
    if(action==='add-entity'){const draft=drafts.get(planKey())||{expectedVersion:plan.version,entities:[],stylePrompt:plan.stylePrompt};if(draft.entities.length>=300){announce('一个项目最多 300 项资产。');return;}draft.entities.push({id:'ent_'+key().replaceAll('-',''),category:'character',name:'',description:'',variant:'',origin:'manual',quote:'',scriptId:''});persist(planKey(),draft);render();root.querySelector('[data-wf-row]:last-of-type input[data-field=name]')?.focus();return;}
    if(action==='close-review'){reviewId=null;rerollId=null;render();focusedBeforeReview?.isConnected&&focusedBeforeReview.focus();return;}
    if(action==='approve')return decide('approved');
    if(action==='reject')return decide('changes_requested');
    if(action==='close-confirmation'){prepared=null;render();return;}
    if(action==='submit-task'&&prepared&&!busy&&session.features?.imageGeneration===true){const targets=prepared.batch||[prepared],editSource=prepared.rerollRevisionId;submittingBatch=true;return perform(async()=>{try{
      const results=await parallelGroups(targets,target=>api.request(`/tasks/${encodeURIComponent(target.task.id)}/submit`,{method:'POST',body:{expectedVersion:target.task.version,confirmationToken:target.confirmation.token},idempotencyKey:target.submitKey||(target.submitKey='ui-submit:'+target.task.id),quietProgress:true}));
      prepared=null;if(editSource){rerollId=null;}persist(`flow:${selected}`,true);await load();
      const unresolved=results.filter(r=>r.status==='rejected'||r.value?.task?.error).length;
      announce(`已处理 ${targets.length} 组提交，最终状态见任务记录。${unresolved?'其中 '+unresolved+' 组需要查询原任务；不会自动重抽。':'生成过程中可以继续准备其他组。'}`);
      }finally{submittingBatch=false;}
    });}
    if(action==='archive')return perform(async()=>{await api.request(`/projects/${encodeURIComponent(selected)}/bundles`,{method:'POST',body:{expectedVersion:project.version}});announce('本次确认的交付包已归档。');await load();});
  }
  function imageFailure(event) {
    const img=event.target;if(img.tagName!=='IMG')return;
    img.hidden=true;
    const choice=img.closest('.creator-candidate-pick');
    if(choice){
      choice.disabled=true;
      const label=choice.querySelector('.creator-candidate-choice span');if(label)label.textContent='缩略图未加载';
      choice.setAttribute('aria-label','缩略图未加载，请先放大查看原图');
    }
    const imageChoice=img.closest('.image-choice-pick');
    if(imageChoice){
      const input=imageChoice.querySelector('input');
      if(input){if(!input.checked)input.disabled=true;}else imageChoice.disabled=true;
      const label=imageChoice.querySelector('.image-choice-off');if(label)label.textContent='预览未加载';
    }
    if(!img.nextElementSibling?.classList.contains('wf-image-error-note')) {
      const note=doc.createElement('span');note.className='wf-image-error-note';
      note.textContent=choice||imageChoice?'缩略图暂未加载，请使用右上角查看原图':'缩略图暂未加载，点击查看原图或刷新状态';img.after(note);
    }
  }
  root.addEventListener('error',imageFailure,true);
  doc.getElementById('warehouseList')?.addEventListener('error',imageFailure,true);
  listeners.push(()=>{root.removeEventListener('error',imageFailure,true);doc.getElementById('warehouseList')?.removeEventListener('error',imageFailure,true);});
  listen(root,'pointerdown',event=>{
    const card=event.target.closest('[data-director-reference]');if(!card||card.disabled||event.button!==0)return;
    directorDrag={pointer:event.pointerId,x:event.clientX,y:event.clientY,assetId:card.dataset.directorReference,stateId:card.dataset.directorState,revisionId:card.dataset.directorRevision};
  });
  listen(root,'dragstart',event=>{if(event.target.closest('[data-director-reference]'))event.preventDefault();});
  listen(root,'pointermove',event=>{if(directorDrag&&Math.hypot(event.clientX-directorDrag.x,event.clientY-directorDrag.y)>8){root.style.cursor='grabbing';if(!root.hasPointerCapture(event.pointerId))root.setPointerCapture(event.pointerId);event.preventDefault();}});
  listen(root,'pointerup',event=>{
    const drag=directorDrag;directorDrag=null;root.style.cursor='';if(!drag)return;
    if(root.hasPointerCapture(event.pointerId))root.releasePointerCapture(event.pointerId);
    if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<8)return;
    suppressDirectorClickUntil=Date.now()+400;
    const target=doc.elementFromPoint(event.clientX,event.clientY)?.closest('[data-director-drop]');
    if(target)insertDirectorAsset(drag.assetId,drag.stateId,drag.revisionId,Number(target.dataset.directorDrop));
  });
  listen(root,'pointercancel',()=>{directorDrag=null;root.style.cursor='';});
  listen(root,'input',onInput);listen(root,'submit',onSubmit);listen(root,'click',onClick);
  listen(root,'change',async event=>{
    const target=event.target;
    if(target.matches('[data-wf-analysis-model]')){
      persist('text-model',target.value);
      const modelName=capabilities.analysis?.models?.find(model=>model.id===target.value)?.name||'文本模型';
      // Update only the selection preview: preserve open editors and checkboxes,
      // and never relabel the model pinned to an existing result or running job.
      root.querySelectorAll('[data-wf-model-preview]').forEach(badge=>{badge.textContent=(badge.dataset.modelPrefix||'')+modelName;});
      return;
    }
    if(target.matches('[data-wf-project]'))return switchProject(target.value);
    if(target.matches('[data-image-reference-upload]')){
      const file=target.files?.[0];if(!file)return;
      if(file.size>8*1024*1024){announce('参考图不能超过 8 MiB。');return;}
      return perform(async()=>{const contentBase64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('无法读取图片。'));reader.readAsDataURL(file);});
        const response=await api.request(`/projects/${encodeURIComponent(selected)}/references`,{method:'POST',body:{name:file.name.slice(0,120),contentBase64,expectedSelectionRevision:session.selection.revision}});
        await load();openReview(response.revision.id);announce('参考图已保存。请看图并保留，再加入本次生成参考。');});
    }
    if(target.matches('[data-wf-upload]'))return upload(target.files?.[0]);
    if(target.matches('[data-wf-quick-upload]'))return startFromFile(target.files?.[0]);
    if(target.matches('[data-wf-entity-select]')){selectedEntity=target.value;persist('selectedEntity',selectedEntity);render();}
    if(target.matches('[data-wf-review-entity]')){selectedEntity=target.value;reviewId=null;render();}
    if(target.name==='sourceRevisionId'){const form=target.closest('form');if(form?.dataset.wfForm==='board-generation'){persist(boardGenerationKey(),{...Object.fromEntries(new FormData(form)),prepareKey:key()});}else if(form?.dataset.wfForm==='compose'){persist(composeKey(),captureCompose(form));}renderImageChoice(target);}
  });
  listen(doc.getElementById('warehouseList'),'click',onClick);
  listen(doc.getElementById('scriptSelect'),'change',e=>switchProject(e.target.value));
  listen(doc.getElementById('warehouseSearch'),'input',e=>{search=e.target.value;renderLibrary();});
  listen(doc.getElementById('warehouseFilters'),'click',e=>{const b=e.target.closest('[data-warehouse-filter]');if(!b)return;filter=b.dataset.warehouseFilter;renderLibrary();});
  listen(doc.getElementById('importScript'),'click',()=>{if(!selected){announce('请先创建项目。');return;}doc.getElementById('scriptFile')?.click();});
  listen(doc.getElementById('scriptFile'),'change',e=>{upload(e.target.files?.[0]);e.target.value='';});
  listen(events,'shell:action',e=>{if(e.detail?.action!=='manual-plan')return;e.preventDefault();if(project){editing=true;navigate('plan');}else{render();root.querySelector('input[name=name]')?.focus();}root.scrollIntoView({behavior:'smooth',block:'start'});});
  listen(doc.getElementById('review-summary-root'),'click',onClick);
  listen(events,'workflow:open-task',async event=>{
    const task=event.detail?.task;if(!task?.projectId||busy)return;
    if(task.projectId!==selected)await switchProject(task.projectId);
    if(task.projectId!==selected)return;selectedEntity=task.entityId;persist('selectedEntity',selectedEntity);
    const revision=assets.flatMap(a=>a.revisions).find(r=>r.taskId===task.id);
    if(revision){page='review';persist('page',page);openReview(revision.id);return;}
    page='review';persist('page',page);render();root.querySelector('[data-wf-task-feedback]')?.scrollIntoView({block:'start'});announce('已定位到这项任务的原档案。');
  });
  listen(root,'keydown',e=>{if(e.key==='Escape'&&canvasDrawer&&!reviewId&&!prepared&&!remoteLibrary.open){e.preventDefault();e.stopPropagation();closeCanvasPanel();}});
  listen(events,'workflow:navigate',e=>navigate(e.detail?.page||'plan'));
  listen(events,'workflow:manual-plan',()=>{if(project){editing=true;navigate('plan');}else{render();root.querySelector('input[name=name]')?.focus();}});
  listen(events,'selection:changed',e=>{session={...session,selection:e.detail?.selection||e.detail};librarySerial++;remoteLibrary={open:false};imageModelSerial++;imageCatalog=null;imageContracts={};imageModelsError='';imageModelsLoading=false;render();});
  listen(events,'session:changed',e=>{
    const next=e.detail?.session?.tenant?e.detail.session:e.detail;
    if(next?.tenant?.id&&next.tenant.id!==session.tenant.id){unmount();root.textContent='本站会话已改变，请重新载入该客户的工作区。';events.dispatchEvent(new CustomEvent('workflow:remount-required'));return;}
    if(next?.tenant)session=next;render();
  });
  listen(events,'tasks:changed',()=>{clearTimeout(timer);timer=setTimeout(()=>{if(alive&&!busy)load();},150);});
  listen(events,'workflow:flush-drafts',e=>{const pending=flushDrafts();if(typeof e.detail?.waitUntil==='function')e.detail.waitUntil(pending);else pending.catch(err=>{error=err.message;render();});});
  listen(doc.defaultView,'beforeunload',e=>{try{drafts.flush();}catch{e.preventDefault();e.returnValue='';}if(busy||reviewing){e.preventDefault();e.returnValue='';}});
  function unmount(){storyCanvas.dispose();canvas.dispose();delete doc.body.dataset.workflowPage;preview.reset();alive=false;requestSerial++;clearTimeout(timer);clearTimeout(flowTimer);clearInterval(progressTimer);clearInterval(pollingTimer);delete doc.body.dataset.workflowMounted;listeners.forEach(remove=>remove());stylesheet.remove();root.replaceChildren();for(const id of ['warehouseList','review-summary-root'])doc.getElementById(id)?.replaceChildren();const chooser=doc.getElementById('scriptSelect');if(chooser)chooser.replaceChildren();}
  const ready=stylesheetReady.then(()=>alive?load({initial:true}):undefined).then(()=>{if(alive&&(stages.includes(page)||page==='production'))void loadImageModels();});
  return {unmount,ready,refresh:load,flushDrafts,hasUnsavedChanges:dirty,getState:()=>({projectId:selected,page,dirty:dirty(),busy,saveError})};
}
