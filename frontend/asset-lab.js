import {buildArchives,assetCoverage} from './asset-lab-archives.js';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {character:'角色',scene:'场景',prop:'道具',effect:'异象',shot:'分镜'};
const recipes = {analyze:'剧本拆解',style:'MJ 风格探索',asset:'Image2 资产制作',clean:'Nano2 保真清理'};
const statusNames = {draft:'等待提交',preparing:'准备中',running:'生成中',downloading:'收取中',completed:'结果已返回',needs_attention:'需要核对',pending:'待审核',approved:'已定版',changes_requested:'需修改',superseded:'历史版本'};
let data = {scripts:[],jobs:[],plans:[],tasks:[],account:{}}, page='overview', selected='legacy', category='all', search='', entityId='', busy=false, loading=false, selectedJob=null, toastTimer;
let drafts = {};
try { const saved=JSON.parse(localStorage.getItem('asset-lab:drafts')||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))drafts=saved; } catch {}
try { selected=localStorage.getItem('asset-lab:script')||'legacy';page=localStorage.getItem('asset-lab:page')||'overview';entityId=localStorage.getItem('asset-lab:entity:'+selected)||''; } catch {}
if(!['overview','script','style','asset','clean','review','export'].includes(page))page='overview';
if(page==='overview')page='script';
const openSteps=new Set(['script',page]), warehouseSelection=new Set();
let warehouseCategory='all', warehouseQuery='', includeHistory=false;
let archiveStage='all',archiveReview='all',archiveKey='',progressLoading=false,progressOnline=true,lastProgressSync=0,focusedJobId='',pendingRender=false;
const taskStartedAt=new Map();
const activeStatuses=new Set(['preparing','running','downloading']);
const archives=()=>buildArchives(data.tasks,data.jobs,data.plans);
const coverage=()=>assetCoverage(entities(),data.jobs,selected);
const stageLabels={approved:'已定版',running:'制作中',pending:'待审核',needs_attention:'需处理',changes_requested:'需修改',draft:'待提交',missing:'待制作'};
const nextStage=e=>e.stages.asset==='approved'?'clean':e.stages.style==='approved'?'asset':'style';
const media = f => typeof f==='string' && !f.includes('..') && !/^[\\/]|:/.test(f) ? '../dashixiong-image-test/'+f : '';
const thumb = id => '/api/workflow/thumbnail?id='+encodeURIComponent(id);
const tag = s => '<span class="tag '+esc(s)+'"><i class="badge-dot"></i>'+esc(statusNames[s]||s)+'</span>';
const currentScript = () => data.scripts.find(s=>s.id===selected);
const plan = () => data.plans.find(p=>p.scriptId===selected);
const jobs = () => data.jobs.filter(j=>j.scope===selected);
const entities = () => plan()?.entities||[];
const entity = () => entities().find(e=>e.id===entityId);
const approvedSources = () => data.tasks.filter(t=>t.humanReview==='approved'&&!t.staleInput&&!data.jobs.find(j=>j.id===t.workflowJobId)?.stale&&media(t.file)&&!/\.(mp4|wav|mp3)$/i.test(t.file));
const sourceFor = (id,stage) => approvedSources().filter(t=>t.workflowScope===selected && t.catalog?.entityId===id && (!stage||t.phase===stage)).at(-1);
const ownOutputs = (review) => jobs().filter(j=>j.kind==='image'&&(!review||!j.stale)&&(review!=='pending'||!j.outputs.some(o=>o.review==='approved'))).flatMap(j=>j.outputs.filter(o=>!review||o.review===review).map(o=>({job:j,output:o})));
const chosenOutputs = () => {const map=new Map();ownOutputs('approved').forEach(x=>{const key=x.job.entityId+':'+x.job.recipe;const old=map.get(key);if(!old||old.job.createdAt<x.job.createdAt)map.set(key,x)});return [...map.values()];};
function toast(message){$('toast').textContent=message;$('toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),5500);}
async function api(url,body){const r=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(body===undefined?15000:180000),...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});const d=await r.json();if(!r.ok)throw Error(d.error||'操作未完成');return d;}
function dialog(title,body,eyebrow='ASSET LAB'){$('dialog').dataset.view='';$('dialog').dataset.archiveReturn='';$('dialogTitle').textContent=title;$('dialogEyebrow').textContent=eyebrow;$('dialogBody').innerHTML=body;if(!$('dialog').open)$('dialog').showModal();$('closeDialog').focus();}
function empty(title,text,button=''){return '<div class="empty"><div class="empty-icon">◇</div><h3>'+esc(title)+'</h3><p>'+esc(text)+'</p>'+button+'</div>';}
function header(title,subtitle,actions=''){return '<div class="page-heading"><div><span class="eyebrow">ASSET RESEARCH LAB</span><h1>'+title+'</h1><p>'+subtitle+'</p></div><div class="actions">'+actions+'</div></div>';}
function stepButton(text,p,cls='secondary'){return '<button class="'+cls+'" data-nav="'+p+'">'+text+'</button>';}
function navigate(p){saveDraft();page=p==='overview'?'script':p;openSteps.add(page);category='all';try{localStorage.setItem('asset-lab:page',page)}catch{}render();document.getElementById('stage-'+page)?.scrollIntoView({behavior:'smooth',block:'start'});}
function targetEntity(recipe,id,source){saveDraft();page=recipe;entityId=id;if(source)drafts[selected+':'+page+':'+entityId]={sourceIds:[source]};openSteps.add(page);try{localStorage.setItem('asset-lab:page',page);localStorage.setItem('asset-lab:entity:'+selected,entityId);}catch{}render();document.getElementById('stage-'+page)?.scrollIntoView({behavior:'smooth',block:'start'});}
function saveDraft(){const f=$('composeForm');if(f){const fd=new FormData(f);drafts[selected+':'+page+':'+entityId]=Object.fromEntries(fd);drafts[selected+':'+page+':'+entityId].sourceIds=fd.getAll('sourceIds');try{localStorage.setItem('asset-lab:drafts',JSON.stringify(drafts));localStorage.setItem('asset-lab:page',page);localStorage.setItem('asset-lab:entity:'+selected,entityId);}catch{}}}
function referenceCard(t){return '<article class="asset-card"><button class="asset-image" data-preview="'+esc(t.id)+'"><img src="'+thumb(t.id)+'" alt="'+esc(t.title)+'" loading="lazy"><span class="image-tag">'+esc(names[t.catalog?.category||t.entity]||'素材')+'</span></button><div class="asset-info"><h3>'+esc(t.catalog?.entityName||t.title)+'</h3><p><span>'+esc(t.phase==='style'?'风格参考':t.phase==='refine'?'精修资产':'设定资产')+'</span><span>历史已选用</span></p></div></article>';}
function resultCard(x,actions=true){const {job:j,output:o}=x;return '<article class="asset-card '+(o.review==='approved'?'selected':'')+'"><button class="asset-image" data-output="'+o.id+'" data-job="'+j.id+'"><img src="'+thumb(o.id)+'" alt="'+esc(j.title)+' 候选 '+esc(o.id.split('-').at(-1))+'" loading="lazy"><span class="image-tag">'+esc(recipes[j.recipe])+'</span></button><div class="asset-info"><h3>'+esc(j.title)+' · '+String.fromCharCode(64+Number(o.id.split('-').at(-1)))+'版</h3><p>'+tag(o.review==='pending'&&j.outputs.some(other=>other.review==='approved')?'备选版本':o.review)+'<span>'+esc(o.dimensions?.join(' × ')||'')+'</span></p>'+(actions?'<div class="actions"><button data-output="'+o.id+'" data-job="'+j.id+'">'+(o.review==='approved'?'查看定版':'对比 / 审核')+'</button>'+(o.review==='approved'&&j.recipe==='style'?'<button data-next="'+j.id+'" data-output-id="'+o.id+'" data-recipe="asset">制作资产 →</button>':o.review==='approved'&&j.recipe==='asset'?'<button data-next="'+j.id+'" data-output-id="'+o.id+'" data-recipe="clean">Nano2 洗图 →</button>':'')+(o.review==='changes_requested'?'<button data-repair="'+o.id+'" data-job="'+j.id+'">按意见准备返修</button>':'')+'</div>':'')+'</div></article>';}
function overview(){
 const imported=!!currentScript(),es=entities(),approved=chosenOutputs(),pending=ownOutputs('pending'),historical=approvedSources().filter(t=>['character','scene','prop'].includes(t.catalog?.category||t.entity));
 const scenes=historical.filter(t=>(t.catalog?.category||t.entity)==='scene');const hero=scenes.at(-1);
 const recent=imported?ownOutputs().slice(0,6):historical.slice().reverse().slice(0,6);
 return '<section class="hero"><div class="hero-text"><span class="eyebrow">从文字，到可复用的世界</span><h1>让故事里的每一个角色，<br>都有自己的样子。</h1><p>导入剧本，探索风格，定版资产。<br>角色、场景与道具，在同一个研究室里完成。</p><div class="actions"><button class="primary" data-import>'+ (imported?'导入另一份剧本':'＋ 导入你的剧本')+'</button>'+stepButton(imported?'继续资产清单 →':'浏览已有素材 →',imported?'script':'export')+'</div></div><div class="hero-art">'+(hero?'<img src="'+thumb(hero.id)+'" alt="现有场景资产预览"><span class="art-label">来自你的素材库 · '+esc(hero.catalog?.entityName||'场景参考')+'</span>':'')+'</div></section>'+
 '<div class="metrics">'+[['本剧本资产条目',es.length,'角色 / 场景 / 道具'],['待审核候选',pending.length,'生成结果需人工确认'],['已定版资产',approved.length,'可继续制作或打包'],['当前任务',jobs().filter(j=>['preparing','running','downloading'].includes(j.status)).length,'任务记录自动保存']].map(x=>'<div class="metric"><span class="label">'+x[0]+'</span><strong>'+x[1]+'</strong><small>'+x[2]+'</small></div>').join('')+'</div>'+
 '<div class="flow-map">'+[['script','导入与拆解','核对原文'],['style','风格探索','MJ 候选'],['asset','资产制作','Image2'],['clean','保真清理','Nano2'],['review','对比审核','选版与返修'],['export','资产交付','分类打包']].map((s,i)=>'<button class="flow-node" data-nav="'+s[0]+'"><span>0'+(i+1)+'</span><b>'+s[1]+'</b><small>'+s[2]+'</small></button>').join('')+'</div>'+
 '<div class="section-heading"><h2>'+(imported?'最近的研究成果':'你的已有资产')+'</h2><span>'+(imported?'来自当前剧本':'真实历史素材 · 供复用与风格参考')+'</span></div>'+
 (recent.length?'<div class="gallery">'+recent.map(x=>imported?resultCard(x):referenceCard(x)).join('')+'</div>':empty('新的故事，从这里开始','导入剧本后，先核对资产清单，再开始风格探索。',stepButton('前往导入','script','primary')));
}
function uploadPanel(){return '<div class="upload-zone" id="dropZone" role="button" tabindex="0" aria-label="导入剧本"><span class="empty-icon">▤</span><strong>把剧本拖到这里</strong><p>支持 DOCX、TXT、Markdown · 单文件不超过8MB</p><button class="primary" data-import>选择剧本文件</button></div>';}
function scriptPage(){
 const s=currentScript(),p=plan(),analysis=jobs().find(j=>j.recipe==='analyze'&&j.analysis);
 const es=entities().filter(e=>category==='all'||e.category===category);
 let body=header('剧本与资产清单','先确认故事里有什么，再决定它们长什么样。',s?'<button data-import>更换剧本</button>':'');
 if(!s)return body+uploadPanel()+'<div class="notice">剧本仅保存在本地。点击“LibTV 拆解剧本”后，才会将正文提交给 LibTV 文本模型。</div>';
 body+='<div class="panel"><div class="file-tile"><span class="file-icon">'+esc(s.filename.split('.').at(-1).toUpperCase())+'</span><div><h3>'+esc(s.filename)+'</h3><small>'+s.characters.toLocaleString()+' 字 · 原文已保存</small></div><button data-original>查看原文</button></div><div class="actions" style="margin-top:20px"><button class="primary" data-analyze>LibTV 拆解剧本</button><button data-edit-plan>编辑资产清单</button>'+(analysis?'<button data-analysis="'+analysis.id+'">核对最新拆解</button>':'')+'</div><p class="muted" style="font-size:11px;margin:12px 0 0">拆解结果保留原文依据。服装、外观等原文未明确的细节，需要作为创作补充确认。</p></div>';
 body+=filters();
 if(!es.length)return body+empty(p?'当前分类没有条目':'先得到一份可核对的资产清单',p?'可在编辑清单中补充角色、场景、道具和不同状态。':'可调用 LibTV 拆解，也可直接手工整理；两种方式都需要你确认后再制作。');
 return body+'<div class="entity-list">'+es.map(e=>'<article class="entity-item"><div class="entity-icon">'+esc(names[e.category])+'</div><div><h3>'+esc(e.name)+' <span class="tag">'+esc(e.variant)+'</span></h3><p>'+esc(e.description)+'</p><blockquote>'+(e.origin==='script'?'原文：'+esc(e.quote):'创作补充 · 非原文明确设定')+'</blockquote></div><div class="actions"><button data-entity="'+e.id+'" data-recipe="style">探索风格 →</button><button data-entity="'+e.id+'" data-recipe="asset">制作资产</button></div></article>').join('')+'</div>';
}
function filters(){return '<div class="gallery-toolbar"><div class="chips">'+[['all','全部'],['character','角色'],['scene','场景'],['prop','道具'],['effect','异象']].map(([id,n])=>'<button data-filter="'+id+'" class="'+(category===id?'active':'')+'">'+n+'</button>').join('')+'</div></div>';}
function defaultPrompt(e,recipe){
 if(recipe==='clean')return '';
 const desc=e?e.name+'（'+e.variant+'）：'+e.description:'';
 if(recipe==='style')return desc+'\n'+(plan()?.stylePrompt||'电影感三维国漫，整体造型统一，轮廓清晰，细节克制，注重材质与光影。')+'\n生成完整的风格候选图。';
 if(e?.category==='scene')return desc+'\n依照已选风格制作场景主视角参考图，固定建筑结构与地标位置，清楚交代入口、出口及人物活动空间。一个完整机位画面，无文字，无拼版。';
 if(e?.category==='prop')return desc+'\n依照已选风格制作道具正面、侧面和背面三视图，等比例、结构统一、纯色背景。无多余文字。';
 return desc+'\n依照已选风格制作同一角色的正面、侧面、背面与面部特写设定图。身份、服装、发型、比例保持一致，四栏清楚排列，纯色背景。';
}
function studioPage(){
 const es=entities();if(!entityId||!es.some(e=>e.id===entityId))entityId=es[0]?.id||'';
 const e=entity(),d=drafts[selected+':'+page+':'+entityId]||{},sources=approvedSources(),defaultSource=page==='asset'?sourceFor(entityId,'style'):page==='clean'?sourceFor(entityId,'asset'):null;
 const selectedSources=d.sourceIds|| (defaultSource?[defaultSource.id]:[]);
 const sourceList=sources.filter(t=>t.workflowScope===selected||selectedSources.includes(t.id));
 const showLegacy=d.legacyRefs==='on',refs=showLegacy?sources.slice().reverse():sourceList.slice().reverse();
 const relevant=jobs().filter(j=>j.recipe===page&&(!entityId||j.entityId===entityId));
 const out=relevant.flatMap(j=>j.outputs.map(o=>({job:j,output:o})));
 const title={style:'寻找这个故事的视觉语言',asset:'把风格，制作成完整资产',clean:'保留设计，让画面更干净'}[page];
 const sub={style:'MJ 生成风格候选。先选定你愿意继续制作的方向。',asset:'Image2 依据已选参考制作设定图。人物、场景和道具分别管理。',clean:'只清理已选图的噪点与纹理。原图永久保留，结果需要前后对照审核。'}[page];
 if(!currentScript())return header(recipes[page],sub)+empty('先选择一份剧本','每份剧本独立保存资产清单、风格选择和生成记录。',stepButton('导入剧本','script','primary'));
 if(!es.length)return header(recipes[page],sub)+empty('先确认资产清单','把角色、场景、道具核对完整，才能为具体资产建立独立版本。',stepButton('整理资产清单','script','primary'));
 return header(recipes[page],sub)+'<div class="studio-grid"><section class="panel"><div class="panel-head"><h3>本次研究</h3><span class="tag">'+(page==='style'?'MJ · 4张候选':page==='asset'?'Image2 · 单资产':'Nano2 · 单图')+'</span></div><form id="composeForm">'+
 '<div class="field"><label for="entitySelect">制作对象</label><select id="entitySelect" name="entityId">'+es.map(x=>'<option value="'+x.id+'" '+(x.id===entityId?'selected':'')+'>'+esc(names[x.category]+' / '+x.name+' · '+x.variant)+'</option>').join('')+'</select></div>'+
 '<div class="field"><label for="jobTitle">任务名称</label><input id="jobTitle" name="title" maxlength="100" required value="'+esc(d.title||e.name+' · '+e.variant+' · '+recipes[page])+'"></div>'+
 '<div class="field"><label>已审核的参考素材 '+(page==='style'?'（可选）':'（必选）')+'</label><div class="references">'+(refs.length?refs.map(t=>'<label class="ref-option"><input type="'+(page==='clean'?'radio':'checkbox')+'" name="sourceIds" value="'+esc(t.id)+'" '+(selectedSources.includes(t.id)?'checked':'')+'><img src="'+thumb(t.id)+'" loading="lazy" alt=""><span>'+esc(t.title)+'</span></label>').join(''):'<p class="muted" style="font-size:11px;padding:8px">暂无本剧本已选素材。先审核上一步结果，或使用已有素材库。</p>')+'</div><label class="ref-option" style="margin-top:8px"><input type="checkbox" name="legacyRefs" id="legacyRefs" '+(showLegacy?'checked':'')+'>显示历史已选素材，手动复用</label><small>'+(page==='clean'?'只选一张原图，保留原构图与比例。':'只勾选当前对象需要的参考，避免混入无关角色、场景或道具。')+'</small></div>'+
 '<div class="field"><label for="jobPrompt">'+(page==='clean'?'补充清理要求（可不填）':'生成要求')+'</label><textarea id="jobPrompt" name="prompt" rows="6" placeholder="'+(page==='clean'?'例如：减少发丝碎纹理，保留发束轮廓。':'描述外观、构图、材质与需要保留的特征。')+'">'+esc(d.prompt??defaultPrompt(e,page))+'</textarea></div>'+
 '<div class="field-row"><div class="field"><label for="ratio">画幅</label><select id="ratio" name="ratio">'+(page==='clean'?[['auto','跟随原图']]:[['16:9','16:9 · 横版设定图'],['9:16','9:16 · 竖版'],['1:1','1:1 · 方形'],['3:4','3:4 · 人物']]).map(([v,l])=>'<option value="'+v+'" '+(d.ratio===v?'selected':'')+'>'+l+'</option>').join('')+'</select></div><div class="field"><label for="quality">'+(page==='style'?'候选数量':'输出清晰度')+'</label><select id="quality" name="quality">'+(page==='style'?'<option value="4">4 张 · 模型固定</option>':[['2K','2K · 默认'],['4K','4K'],['1K','1K']].map(([v,l])=>'<option value="'+v+'" '+(d.quality===v?'selected':'')+'>'+l+'</option>').join(''))+'</select></div></div>'+
 '<div class="form-footer"><button type="submit" class="primary">检查参数并准备任务 →</button><p>先查看模型、参考素材和数量，再确认生成</p></div></form></section><section class="studio-output"><div class="panel-head"><h3>'+title+'</h3><span class="muted" style="font-size:11px">'+out.length+' 个结果</span></div>'+
 relevant.filter(j=>j.status!=='completed').slice(0,3).map(j=>'<div class="job-progress"><h3>'+tag(j.status)+' '+esc(j.title)+'</h3><p>'+esc(taskMessage(j))+'</p><div class="actions" style="margin-top:12px">'+(j.status==='draft'?'<button data-draft="'+j.id+'">查看提交单</button>':j.status==='needs_attention'?'<button data-recover="'+j.id+'" '+(!j.submissionAttempted?'disabled':'')+'>收取原任务</button>':'')+'</div></div>').join('')+
 (out.length?'<div class="gallery candidate-gallery">'+out.map(x=>resultCard(x)).join('')+'</div>':empty('这里将出现你的候选结果','每次生成保留独立记录。结果返回后，先比较与审核，再送往下一道工序。'))+'</section></div>';
}
function reviewPage(){
 let out=ownOutputs().filter(x=>category==='all'||x.job.category===category);
 out.sort((a,b)=>(a.output.review==='pending'?-1:1)-(b.output.review==='pending'?-1:1));
 return header('对比与审核','看清差异，留下正确的版本。审核意见与当前图像版本一起保存。')+filters()+
 (out.length?'<div class="gallery">'+out.map(x=>resultCard(x)).join('')+'</div>':empty('当前没有待审结果','从风格探索开始，生成的每一版都会自动进入这里。',stepButton('去探索风格','style','primary')));
}
function exportPage(){
 if(!currentScript()){
  const refs=approvedSources().filter(t=>category==='all'||(t.catalog?.category||t.entity)===category).slice().reverse();
  return header('已有资产参考库','这些是历史项目已选用的素材。新剧本可手动复用，不会自动继承成新作品。',stepButton('导入新剧本','script','primary'))+filters()+'<div class="gallery">'+refs.map(referenceCard).join('')+'</div>';
 }
 const out=chosenOutputs().filter(x=>category==='all'||x.job.category===category);
 return header('定版与导出','把审核通过的设计，整理成下游制作可以使用的资产。')+
 '<div class="export-summary"><span class="export-icon">▣</span><div><h2>'+chosenOutputs().length+' 份已定版资产</h2><p>按角色、场景、道具分类，附提示词、参考来源与审核记录。</p></div><button class="primary" data-export '+(!chosenOutputs().length?'disabled':'')+'>下载资产包 ↓</button></div>'+
 '<div class="notice good">资产包保留风格图、设定图和清理图的区别；同一对象同一工序只导出最新已选版本。上游失效或文件变更的结果不会进入资产包。</div>'+filters()+
 (out.length?'<div class="gallery">'+out.map(x=>resultCard(x)).join('')+'</div>':empty('这里等待你的第一份定版资产','先审核候选图。完成生成并不意味着已经定版。',stepButton('前往审核','review','primary')));
}
function withoutHeading(html){const el=document.createElement('div');el.innerHTML=html;el.querySelector('.page-heading')?.remove();return el.innerHTML;}
function stageOutputs(recipe){return ownOutputs().filter(x=>x.job.recipe===recipe);}
function stageBrief(recipe){
 const out=stageOutputs(recipe),pending=ownOutputs('pending').filter(x=>x.job.recipe===recipe).length;
 const active=jobs().filter(j=>j.recipe===recipe&&j.status!=='completed');
 return '<div class="stage-brief"><p>'+({style:'先为角色、场景或道具确定视觉方向。选中的风格图会成为下一步参考。',asset:'沿用已定版风格，制作角色设定、场景参考与道具三视图。',clean:'沿用资产原图，清理噪点与碎纹理，保留人物和构图。'}[recipe])+'</p><button class="primary" data-nav="'+recipe+'">'+(out.length?'继续制作':'展开制作区')+' →</button></div>'+
 active.slice(0,2).map(j=>'<div class="inline-job">'+tag(j.status)+'<span>'+esc(j.title)+'</span>'+(j.status==='draft'?'<button data-draft="'+j.id+'">查看提交单</button>':'')+'</div>').join('')+
 (out.length?'<div class="gallery stage-gallery">'+out.slice(0,4).map(x=>resultCard(x)).join('')+'</div>':'<div class="stage-placeholder"><span>◇</span> '+(recipe==='style'?'风格候选':recipe==='asset'?'资产设定图':'清理前后对照')+'会保存在这里</div>')+(pending?'<p class="stage-footnote">'+pending+' 个候选等待人工审核</p>':'');
}
function coveragePanel(){
 const c=coverage();if(!c.total)return '';
 return '<section class="asset-coverage" aria-label="资产清单完成度"><div class="coverage-heading"><div><span class="caption">ASSET CHECKLIST</span><h2>'+c.ready+' / '+c.total+' 项已完成资产与清理</h2></div><span class="tag">'+(c.missing.length?'还有 '+c.missing.length+' 项待完成':'清单已齐备')+'</span></div><div class="coverage-groups">'+c.groups.map(g=>'<div><b>'+names[g.category]+'</b><strong>'+g.ready+' / '+g.total+'</strong><small>项已完成</small></div>').join('')+'</div><details '+(c.total<=6?'open':'')+'><summary>逐项查看制作进度</summary><div class="coverage-table"><div class="coverage-row coverage-labels"><span>制作对象</span><span>MJ 风格</span><span>Image2 资产</span><span>Nano2 清理</span></div>'+c.rows.map(e=>'<div class="coverage-row"><span><small>'+names[e.category]+'</small><b>'+esc(e.name)+'</b></span>'+['style','asset','clean'].map(stage=>'<button class="coverage-stage '+e.stages[stage]+'" data-entity="'+e.id+'" data-recipe="'+stage+'" aria-label="'+esc(e.name)+' · '+recipes[stage]+' · '+stageLabels[e.stages[stage]]+'">'+stageLabels[e.stages[stage]]+'</button>').join('')+'</div>').join('')+'</div></details></section>';
}
function workflowPage(){
 const s=currentScript(),approved=chosenOutputs(),pending=ownOutputs('pending'),es=entities();
 const stages=[['script','剧本与资产清单','导入 / 拆解 / 核对',s?(es.length?es.length+' 项资产已确认':'已导入 · 待核对'):'等待导入'],['style','选择视觉风格','MIDJOURNEY',approved.filter(x=>x.job.recipe==='style').length+' 项已定版'],['asset','制作模型资产','IMAGE2',approved.filter(x=>x.job.recipe==='asset').length+' 项已定版'],['clean','保真清理','NANO2',approved.filter(x=>x.job.recipe==='clean').length+' 项已定版'],['review','审核与返修','REVIEW',pending.length+' 个待审核'],['export','打包交付','DELIVERY',approved.length+' 份可导出']];
 const c=coverage(),nextObject=c.missing[0],next=!s||!es.length?'script':nextObject?nextStage(nextObject):pending.length?'review':'export';
 let body='<div class="canvas-heading"><div><span class="eyebrow">ASSET WORKFLOW</span><h1>'+(s?esc(s.filename.replace(/\.[^.]+$/,'')):'从一份剧本，开始你的资产制作')+'</h1><p>在这张工作流里制作与审核，定版素材自动归入左侧仓库。</p></div><button class="primary" '+(nextObject?'data-entity="'+nextObject.id+'" data-recipe="'+next+'"':'data-nav="'+next+'"')+'>'+ (nextObject?'继续制作 '+esc(nextObject.name):s?'查看交付':'开始导入剧本')+' ↘</button></div><div class="workflow-summary"><span><i class="badge-dot"></i> '+(s?'当前剧本':'等待新故事')+'</span><span>'+es.length+' 项制作对象</span><span>'+pending.length+' 个待审</span><span>'+approved.length+' 份定版</span><span class="workflow-summary-end">自动保存 · LibTV</span></div>'+coveragePanel()+'<div id="liveProgress" aria-live="polite">'+progressPanel()+'</div><div class="workflow-stack">';
 for(const [index,[id,title,subtitle,status]] of stages.entries()){
  let content;
  if(id==='script')content=withoutHeading(scriptPage());
  else if(['style','asset','clean'].includes(id))content=page===id?withoutHeading(studioPage()):stageBrief(id);
  else if(id==='review')content=withoutHeading(reviewPage());
  else content=(c.missing.length?'<div class="notice"><b>清单尚未齐备：'+c.ready+' / '+c.total+' 项已完成资产与清理</b><br>待完成：'+esc(c.missing.map(e=>names[e.category]+' · '+e.name).join('、'))+'。现在打包只会包含已定版的部分。</div>':'')+'<div class="delivery-row"><span class="delivery-icon">▣</span><div><h3>'+approved.length+' 份已审核资产，按分类整理</h3><p>角色 / 场景 / 道具 · 包含提示词、参考来源与审核记录</p></div><button class="primary" data-export '+(!s||!approved.length?'disabled':'')+'>打包并保存 ↓</button></div>';
  body+='<details class="workflow-stage '+(page===id?'current':'')+'" id="stage-'+id+'" data-stage="'+id+'" '+(openSteps.has(id)?'open':'')+'><summary><span class="step-number">0'+(index+1)+'</span><div class="stage-title"><h2>'+title+'</h2><small>'+subtitle+'</small></div><span class="stage-status">'+status+'</span><span class="fold-icon">⌄</span></summary><div class="stage-content">'+content+'</div></details>';
 }
 return body+'</div><footer class="canvas-footer">每个结果保留版本与来源 · 人工审核后进入下一道工序</footer>';
}
function renderWarehouse(){
 const all=archives().filter(a=>includeHistory||selected==='legacy'||a.scope===selected);
 const items=all.filter(a=>(warehouseCategory==='all'||a.category===warehouseCategory)&&(!warehouseQuery||[a.name,a.series,...a.items.map(t=>t.title+' '+(t.catalog?.variant||''))].join(' ').toLowerCase().includes(warehouseQuery.toLowerCase())));
 $('warehouseCount').textContent=all.length;$('warehouseScope').textContent=selected==='legacy'?'历史档案':'本剧本档案';
 $('warehouseFilters').innerHTML=[['all','全部'],['character','角色'],['scene','场景'],['prop','道具'],['effect','异象']].map(([k,v])=>'<button class="'+(warehouseCategory===k?'active':'')+'" data-warehouse-filter="'+k+'">'+v+'</button>').join('');
 $('warehouseList').innerHTML=items.length?items.map(a=>'<button class="archive-cover" data-open-archive="'+esc(a.key)+'" aria-label="打开'+esc(a.name)+'档案"><div class="archive-cover-image">'+(a.cover?'<img src="'+thumb(a.cover.thumbId)+'" alt="'+esc(a.name)+'档案封面" loading="lazy">':'<div class="archive-placeholder"><b>'+esc(names[a.category])+'</b><small>待制作</small></div>')+'<span class="archive-type">'+esc(names[a.category])+'档案</span><span class="archive-stack">▤</span></div><div class="archive-cover-info"><b>'+esc(a.name)+'</b><small>'+(a.items.length?a.items.length+' 张图片 · '+a.approved.length+' 张已选用':'清单已确认 · 尚未出图')+'</small><span>'+esc(a.scope===selected?'当前剧本':a.series)+'</span></div><span class="archive-open">'+(a.items.length?'查看全部版本':'进入制作')+' →</span></button>').join(''):empty(warehouseQuery?'没有匹配的档案':'这里会建立你的资产档案',warehouseQuery?'可搜索人物名称、场景或服装状态。':'图片返回后，按角色、场景和道具自动归档。');
 updateWarehouseSelection();
}
function showArchive(key,reset=false){
 const a=archives().find(x=>x.key===key);if(!a)return toast('没有找到这份档案。');
 archiveKey=key;if(reset){archiveStage='all';archiveReview='all';}
 const out=a.items.filter(t=>(archiveStage==='all'||t.stage===archiveStage)&&(archiveReview==='all'||(archiveReview==='approved'?t.humanReview==='approved'&&!t.stale:archiveReview==='pending'?t.humanReview==='pending'&&!t.job?.outputs.some(o=>o.review==='approved'):t.stale||['superseded','rejected','changes_requested'].includes(t.humanReview))));
 const kind=names[a.category]||'资产';
 dialog(a.name+' · '+kind+'档案','<div class="archive-profile">'+(a.cover?'<img src="'+thumb(a.cover.thumbId)+'" alt="'+esc(a.name)+'代表图">':'<div class="archive-placeholder"><b>'+esc(kind)+'</b><small>待制作</small></div>')+'<div><span class="caption">'+esc(a.scope?data.scripts.find(s=>s.id===a.scope)?.filename||'当前剧本':a.series)+'</span><h3>'+esc(a.name)+'</h3><p>'+esc(a.description||'风格探索、资产设定、清理结果与历史版本，统一保存在这份档案里。')+'</p><div class="archive-metrics"><span><b>'+a.items.length+'</b> 图片记录</span><span><b>'+a.approved.length+'</b> 已选用</span><span><b>'+(new Set(a.items.map(t=>t.catalog?.variant).filter(Boolean)).size||(a.variant?1:0))+'</b> 造型 / 状态</span></div></div></div>'+
 '<div class="archive-toolbar"><div class="chips">'+[['all','全部图片'],['style','风格图'],['asset','资产设定'],['clean','清理图']].map(([k,n])=>'<button data-archive-stage="'+k+'" class="'+(archiveStage===k?'active':'')+'">'+n+'</button>').join('')+'</div><label class="sr-only" for="archiveReview">版本状态</label><select id="archiveReview">'+[['all','全部状态'],['approved','已选用'],['pending','待审核'],['history','退回 / 历史 / 已失效']].map(([k,n])=>'<option value="'+k+'" '+(archiveReview===k?'selected':'')+'>'+n+'</option>').join('')+'</select></div>'+
 '<p class="archive-hint">按记录从新到旧排列。不同造型分别保留；已选用的图片才可进入生成参考。</p>'+
 (out.length?'<div class="gallery archive-gallery">'+out.map(t=>archiveImageCard(a,t)).join('')+'</div>':empty(a.items.length?'这个分类还没有图片':'这份'+kind+'档案还没有图片',a.items.length?'切换图片类型或版本状态，可以查看其他记录。':'清单已确认，从 MJ 风格开始制作，后续资产、清理与版本会归入这里。',!a.items.length&&a.scope===selected?'<button class="primary" data-entity="'+esc(a.entityId)+'" data-recipe="style">制作'+esc(a.name)+' →</button>':'')),'ASSET DOSSIER');
 $('dialog').dataset.view='archive';$('dialog').dataset.archiveKey=key;
 $('archiveReview').onchange=e=>{archiveReview=e.target.value;showArchive(key)};
}
function archiveImageCard(a,t){
 const usable=approvedSources().some(s=>s.id===t.sourceId),state=t.stale?'已失效':t.humanReview==='approved'?'approved':t.humanReview==='rejected'?'changes_requested':t.humanReview==='pending'&&t.job?.outputs.some(o=>o.review==='approved')?'备选版本':t.humanReview;
 const phase={style:'风格图',asset:'资产设定',clean:'清理图'}[t.stage]||'图片资产';
 const version=(t.catalog?.version?'V'+t.catalog.version:'')+(t.job?.outputs.length>1?' · '+String.fromCharCode(64+Number(t.output.id.split('-').at(-1)))+'版':'');
 return '<article class="asset-card archive-image-card"><button class="asset-image" data-archive-image="'+esc(t.id)+'"><img src="'+thumb(t.thumbId)+'" alt="'+esc(t.title)+'" loading="lazy"><span class="image-tag">'+phase+' '+version+'</span></button>'+(usable?'<label class="archive-select"><input type="checkbox" data-select-source="'+esc(t.sourceId)+'" aria-label="选择 '+esc(t.title)+'" '+(warehouseSelection.has(t.sourceId)?'checked':'')+'>选择</label>':'')+'<div class="asset-info"><h3 title="'+esc(t.title)+'">'+esc(t.title)+'</h3><div class="archive-variant">'+esc(t.catalog?.variant||'基础设定')+'</div><p>'+tag(state)+'<span>'+esc(t.output?.dimensions?.join(' × ')||(Array.isArray(t.actualPixels)?t.actualPixels.join(' × '):t.actualPixels)||'')+'</span></p><div class="actions"><button data-archive-image="'+esc(t.id)+'">查看版本</button>'+(usable?'<button data-archive-reference="'+esc(t.sourceId)+'">用作参考</button>':'')+(t.job&&t.output?'<button data-archive-review="'+esc(t.id)+'">对比 / 审核</button>':'')+'</div></div></article>';
}
function archiveImage(id,review=false){
 const a=archives().find(x=>x.key===archiveKey),t=a?.items.find(x=>x.id===id);if(!t)return;
 const back='<button class="archive-back" data-back-archive="'+esc(a.key)+'">← 返回 '+esc(a.name)+' 档案</button>';
 if(review&&t.job&&t.output){showOutput(t.job,t.output);$('dialogBody').insertAdjacentHTML('afterbegin',back);$('dialog').dataset.archiveReturn=a.key;return;}
 const reviewed=t.reviewedAt?new Date(t.reviewedAt).toLocaleString('zh-CN'):'';
 dialog(t.title,back+'<img src="'+media(t.file)+'" alt="'+esc(t.title)+'"><div class="archive-image-detail"><p>'+tag(t.stale?'已失效':t.humanReview)+' <span>'+esc(t.catalog?.variant||'基础设定')+'</span></p><p>'+esc(t.modelName||t.modelKey||t.job?.modelName||'模型记录未提供')+(reviewed?' · 审核时间 '+esc(reviewed):'')+'</p>'+(t.reviewNote?'<p>审核意见：'+esc(t.reviewNote)+'</p>':'')+'<details><summary>查看生成要求</summary><pre class="contract">'+esc(t.effectivePrompt||t.prompt||t.job?.prompt||'未记录')+'</pre></details></div>','档案中的图片版本');
 $('dialog').dataset.archiveReturn=a.key;
}
function updateWarehouseSelection(){
 for(const id of warehouseSelection)if(!approvedSources().some(t=>t.id===id))warehouseSelection.delete(id);
 $('selectionCount').textContent=warehouseSelection.size?'已选择 '+warehouseSelection.size+' 份资产':'进入档案，勾选已定版图片';
 $('batchClean').disabled=!warehouseSelection.size||!currentScript();
}
function addReference(id){
 const t=approvedSources().find(t=>t.id===id);if(!t)return toast('这份素材需要先审核通过。');
 if(!['style','asset','clean'].includes(page)||!$('composeForm'))return toast('先展开右侧 MJ、Image2 或 Nano2 制作区，再添加参考。');
 saveDraft();const key=selected+':'+page+':'+entityId,d=drafts[key]||{};
 d.sourceIds=page==='clean'?[id]:[...new Set([...(d.sourceIds||[]),id])];drafts[key]=d;render();toast('已放入当前制作对象的参考区。');
}
async function batchClean(){
 if(busy)return;
 const items=[...warehouseSelection].map(id=>approvedSources().find(t=>t.id===id));
 if(items.some(t=>!t||t.workflowScope!==selected||!entities().some(e=>e.id===t.catalog?.entityId)||t.phase!=='asset'))return toast('批量洗图请选择当前剧本中已定版的 Image2 资产图。');
 if(!items.length)return;
 busy=true;const batch=[],errors=[];toast('正在为 '+items.length+' 份资产检查清理参数…');
 for(const t of items){try{const r=await api('/api/workflow/prepare',{recipe:'clean',scope:selected,entityId:t.catalog.entityId,category:t.catalog.category,title:t.title+' · Nano2 清理',prompt:'',sourceIds:[t.id],settings:{ratio:'auto',quality:'2K'}});batch.push(r.job);}catch(e){errors.push(t.title+'：'+e.message);}}
 busy=false;await load(true);
 dialog('批量洗图 · 核对任务','<p class="muted">每张原图独立保留。这里仅准备任务，点击对应的“确认生成”才会调用 LibTV 并产生平台费用。</p>'+batch.map(j=>'<div class="task-row"><div><h3>'+esc(j.title)+'</h3><p>Nano2 · 跟随原图 · 2K</p></div>'+tag(j.status)+'<button data-draft="'+j.id+'">'+(j.status==='draft'?'确认生成':'查看记录')+'</button></div>').join('')+(errors.length?'<div class="notice error">'+errors.map(esc).join('<br>')+'</div>':'')+'<p class="muted">所有任务也已保存到右上角任务中心，尚未提交的任务可稍后继续。</p>','原图保留 · 逐张审核');
}
function taskMessage(j){if(j.status==='completed'){if(j.kind==='text'&&j.analysisReview?.decision==='approved')return '清单已核对，可继续探索风格。';if(j.outputs.some(o=>o.review==='approved'))return '当前版本已定版，可继续制作或打包。';}return j.message||'等待状态更新';}
function taskBadge(j){
 if(j.status==='completed')return tag(j.kind==='text'?(j.analysisReview?.decision==='approved'?'清单已核对':'拆解完成 · 待核对'):j.outputs.some(o=>o.review==='approved')?'生成完成 · 已选用':'生成完成 · 待审核');
 if(j.status==='needs_attention')return tag(j.submissionAttempted?'结果未确认 · 需核对':'准备异常 · 未生成');
 return tag(j.status);
}
function progressTrack(j){
 const stages=['准备素材','发起生成','等待模型','收取结果','生成完成'];
 const step={draft:-1,preparing:0,running:2,downloading:3,completed:4,needs_attention:j.submissionAttempted?2:0,failed:2}[j.status]??0;
 return '<div class="task-progress-track '+(j.status==='needs_attention'||j.status==='failed'?'attention':'')+'" role="progressbar" aria-label="'+esc(j.title)+'阶段进度" aria-valuetext="'+esc(taskMessage(j))+'">'+stages.map((s,i)=>'<span class="'+(j.status==='completed'||i<step?'done':i===step?'current':'')+'"><i></i><small>'+s+'</small></span>').join('')+'</div>';
}
function elapsed(j){
 const start=j.submittedAt?Date.parse(j.submittedAt):taskStartedAt.get(j.id);
 if(!start||!activeStatuses.has(j.status))return '';
 const seconds=Math.max(0,Math.floor((Date.now()-start)/1000));return '已等待 '+Math.floor(seconds/60)+'分'+String(seconds%60).padStart(2,'0')+'秒';
}
function focusedTask(){return jobs().find(j=>j.id===focusedJobId)||jobs().find(j=>activeStatuses.has(j.status))||jobs().find(j=>j.submissionAttempted||j.status==='needs_attention')||jobs()[0];}
function progressPanel(){
 const j=focusedTask(),sync=lastProgressSync?new Date(lastProgressSync).toLocaleTimeString('zh-CN'):'尚未同步';
 if(!j)return '<div class="task-feedback idle"><span class="connection-dot '+(progressOnline?'on':'')+'"></span><span>'+(progressOnline?'任务反馈已就绪 · 提交后在此显示进度、完成结果与异常':'任务状态连接中断 · 等待恢复同步')+'</span><button data-refresh-progress>刷新状态</button></div>';
 return '<section class="task-feedback '+(j.status==='needs_attention'?'attention':'')+'"><div class="task-feedback-title"><div><span class="caption">LIBTV 任务反馈</span><h3>'+esc(j.title)+'</h3></div>'+taskBadge(j)+'</div>'+progressTrack(j)+'<div class="task-feedback-message"><p>'+esc(taskMessage(j))+'</p><span>'+elapsed(j)+'</span></div>'+(!progressOnline?'<div class="notice error">状态同步中断，以上是上次记录；当前生成进度未知。恢复连接后继续核对。</div>':'')+'<div class="task-feedback-footer"><small>'+ (progressOnline?'每 2 秒同步 · 最近同步 '+sync:'最近成功同步 '+sync)+' · '+(j.status==='running'?'模型未提供准确百分比':'阶段进度')+'</small><div class="actions"><button data-refresh-progress>刷新</button><button data-job-details="'+j.id+'">任务详情</button>'+(j.status==='completed'?'<button class="primary" data-job-results="'+j.id+'">查看结果</button>':'')+'</div></div></section>';
}
function showTaskDetails(j){
 if(!j)return;
 focusedJobId=j.id;dialog('任务详情 · '+j.title,'<div id="taskDetailLive"></div>','LIBTV TASK');$('dialog').dataset.view='task-detail';$('dialog').dataset.jobId=j.id;refreshProgress();
}
function detailBody(j){return taskBadge(j)+progressTrack(j)+'<p class="task-detail-message">'+esc(taskMessage(j))+'</p><table class="model-table"><tbody><tr><td>模型</td><td>'+esc(j.modelName)+'</td></tr><tr><td>任务编号</td><td><code>'+j.id+'</code></td></tr><tr><td>发起生成</td><td>'+(j.submissionAttempted?'已发起，重复点击不会再次生成':'尚未发起模型生成')+'</td></tr><tr><td>结果</td><td>'+(j.status==='completed'?(j.kind==='text'?'拆解结果已保存':j.outputs.length+' 张图片已保存'):'等待有效结果返回')+'</td></tr></tbody></table><div class="actions">'+(j.status==='draft'?'<button class="primary" data-draft="'+j.id+'">查看提交单</button>':'')+(j.status==='completed'?'<button class="primary" data-job-results="'+j.id+'">查看结果 / 审核</button>':'')+(j.status==='needs_attention'&&j.submissionAttempted?'<button class="primary" data-recover="'+j.id+'">核对并收取原结果</button>':'')+(j.status==='needs_attention'&&!j.submissionAttempted?'<button class="primary" data-submit="'+j.id+'">继续准备并提交</button>':'')+(j.projectUrl?'<a class="text-button" href="'+esc(j.projectUrl)+'" target="_blank" rel="noopener">查看 LibTV 原任务 ↗</a>':'')+'</div>'+(j.status==='needs_attention'?'<div class="notice error">'+(j.submissionAttempted?'目前不能确认原任务成功或失败。先核对原任务，避免重复生成和扣费。':'生成前准备未完成，本任务没有发起模型生成。修复原因后可继续准备，沿用原画布与已上传素材。')+'</div>':'');}
function refreshProgress(){
 if($('liveProgress'))$('liveProgress').innerHTML=progressPanel();
 const active=jobs().filter(j=>activeStatuses.has(j.status)),j=focusedTask();
 $('taskCount').textContent=active.length?active.length+' 进行中':jobs().some(x=>x.status==='needs_attention')?'需处理':jobs().some(x=>x.status==='completed')?'有结果':'0';
 $('taskSignal').innerHTML=j&&j.status!=='draft'?'<button class="task-signal '+(j.status==='needs_attention'?'attention':'')+'" data-job-details="'+j.id+'"><span class="signal-dot '+(activeStatuses.has(j.status)?'pulsing':'')+'"></span><span><b>'+esc(j.status==='completed'?'生成完成，点击查看结果':j.status==='needs_attention'?'任务异常，需要核对':!progressOnline?'连接中断，状态待核对':statusNames[j.status])+'</b><small>'+esc(j.title)+' '+elapsed(j)+'</small></span>↗</button>':'';
 if($('dialog').open&&$('dialog').dataset.view==='tasks')$('dialogBody').innerHTML=taskList();
 if($('dialog').open&&$('dialog').dataset.view==='task-detail'){
  const current=data.jobs.find(x=>x.id===$('dialog').dataset.jobId);if(current&&$('taskDetailLive'))$('taskDetailLive').innerHTML=detailBody(current);
 }
}
function taskTransitions(previous,next){
 for(const j of next){const old=previous.find(x=>x.id===j.id);if(!old||old.status===j.status)continue;
  if(j.status==='completed'){focusedJobId=j.id;toast(j.title+'：结果已返回，可以查看与审核。');}
  else if(j.status==='needs_attention'){focusedJobId=j.id;toast(j.title+'：'+j.message);}
 }
}
async function pollProgress(){
 if(progressLoading)return;progressLoading=true;
 try{
  const flow=await api('/api/workflow/state');const old=data.jobs,changed=JSON.stringify(old)!==JSON.stringify(flow.jobs);
  progressOnline=true;lastProgressSync=Date.now();taskTransitions(old,flow.jobs);data.jobs=flow.jobs;data.plans=flow.plans;
  if(changed)pendingRender=true;
  if(pendingRender&&!busy&&!$('dialog').open&&!['TEXTAREA','INPUT','SELECT'].includes(document.activeElement?.tagName)){saveDraft();render();pendingRender=false;}
  else refreshProgress();
  if(changed)load();
 }catch(e){progressOnline=false;refreshProgress();}finally{progressLoading=false;}
}
function render(){
 const scrollY=window.scrollY;
 document.querySelectorAll('#steps [data-nav]').forEach(b=>b.classList.toggle('active',b.dataset.nav===page));
 $('scriptSelect').innerHTML='<option value="legacy">选择剧本，开始制作</option>'+data.scripts.map(s=>'<option value="'+s.id+'">'+esc(s.filename)+'</option>').join('');
 $('scriptSelect').value=selected;$('reviewCount').textContent=ownOutputs('pending').length;$('taskCount').textContent=jobs().filter(j=>['preparing','running','downloading'].includes(j.status)).length;
 $('connectionLabel').textContent=data.account.connected?'LibTV 已连接':'连接 LibTV';document.querySelector('.connection-dot').classList.toggle('on',!!data.account.connected);
 $('main').innerHTML=workflowPage();renderWarehouse();window.scrollTo({top:scrollY});
 document.querySelectorAll('.workflow-stage').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)openSteps.add(d.dataset.stage);else openSteps.delete(d.dataset.stage)}));
 const form=$('composeForm');if(form)form.onsubmit=prepareForm;
 const drop=$('dropZone');if(drop){drop.ondragover=e=>{e.preventDefault();drop.classList.add('drag')};drop.ondragleave=()=>drop.classList.remove('drag');drop.ondrop=e=>{e.preventDefault();upload(e.dataTransfer.files[0])};drop.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('scriptFile').click()}};drop.onclick=e=>{if(!e.target.closest('button'))$('scriptFile').click()};}
 refreshProgress();
}
async function load(force=false){
 if(loading||busy)return;
 loading=true;
 try{
  const [scripts,flow,m,a]=await Promise.all([api('/api/scripts'),api('/api/workflow/state'),api('../dashixiong-image-test/manifest.json'),api('/api/execution')]);
  const previous=JSON.stringify([data.scripts,data.jobs,data.plans,data.tasks.length,data.account.connected]);
  taskTransitions(data.jobs,flow.jobs);progressOnline=true;lastProgressSync=Date.now();
  data={scripts:scripts.scripts,jobs:flow.jobs,plans:flow.plans,tasks:m.tasks,account:a};
  if(selected!=='legacy'&&!currentScript())selected='legacy';
  if(force||previous!==JSON.stringify([data.scripts,data.jobs,data.plans,data.tasks.length,data.account.connected])){pendingRender=true;if(force||(!$('dialog').open&&!['TEXTAREA','INPUT','SELECT'].includes(document.activeElement?.tagName))){saveDraft();render();pendingRender=false;}}
  refreshProgress();
  $('saveStatus').textContent='已同步 · '+new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
 }catch(e){$('saveStatus').textContent='连接需要检查';if(force)$('main').innerHTML=empty('本地服务暂未就绪',e.message,'<button data-reload>重新连接</button>');else toast(e.message);}
 finally{loading=false;}
}
async function upload(file){
 if(!file||busy)return;
 if(!/\.(txt|docx|md)$/i.test(file.name)||!file.size||file.size>8*1024*1024)return toast('请选择不超过8MB的 DOCX、TXT 或 Markdown 剧本。');
 busy=true;toast('正在保存剧本原文…');
 try{
  const encoded=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file)});
  const r=await api('/api/scripts/import',{filename:file.name,contentBase64:encoded});selected=r.script.id;entityId='';page='script';
  localStorage.setItem('asset-lab:script',selected);localStorage.setItem('asset-lab:page',page);busy=false;await load(true);toast(r.duplicate?'已切换到这份剧本，原有记录已保留。':'剧本已导入。现在可以用 LibTV 拆解资产清单。');
 }catch(e){toast(e.message)}finally{busy=false;$('scriptFile').value='';}
}
async function prepareForm(e){
 e.preventDefault();if(busy)return;saveDraft();const fd=new FormData(e.target),settings={ratio:fd.get('ratio')};
 if(page==='asset')settings.resolution=fd.get('quality');
 if(page==='clean')settings.quality=fd.get('quality');
 const p={recipe:page,scope:selected,entityId,category:entity().category,title:fd.get('title'),prompt:fd.get('prompt'),sourceIds:fd.getAll('sourceIds'),settings};
 await prepare(p);
}
async function prepare(payload){
 busy=true;const button=$('composeForm')?.querySelector('button[type=submit]');if(button){button.disabled=true;button.textContent='检查模型参数…';}
 try{const r=await api('/api/workflow/prepare',payload);busy=false;await load(true);showDraft(r.job);if(r.reused)toast('已找到相同任务，沿用原记录。');}
 catch(e){toast(e.message)}finally{busy=false;if(button){button.disabled=false;button.textContent='检查参数并准备任务 →';}}
}
function showDraft(j){
 const refs=j.references.map(r=>'<li>'+esc(r.name)+'</li>').join('');
 dialog('确认本次生成','<div class="account-card"><div><h3>'+esc(j.title)+'</h3><p>'+esc(recipes[j.recipe])+' · '+esc(j.modelName)+'</p></div>'+tag(j.status)+'</div>'+
 '<table class="model-table"><tbody><tr><td>生成数量</td><td>'+(j.kind==='text'?'1 份结构化清单':j.settings.count+' 张候选')+'</td></tr><tr><td>画幅 / 清晰度</td><td>'+esc(j.settings.ratio||'文字结果')+' '+esc(j.settings.resolution||j.settings.quality||'')+'</td></tr><tr><td>参考素材</td><td>'+(refs?'<ul>'+refs+'</ul>':'无图片参考')+'</td></tr><tr><td>费用</td><td>平台未返回准确报价，以 LibTV 实际扣费为准</td></tr></tbody></table>'+
 '<details><summary>查看完整生成要求</summary><pre class="contract">'+esc(j.prompt)+'</pre></details>'+
 '<div class="notice">点击确认后才会提交给 LibTV。结果返回后仍需审核；重复打开同一任务不会重复生成。</div>'+
 '<div class="dialog-bottom"><button data-close>稍后提交</button><button class="primary" data-submit="'+j.id+'" '+(j.status!=='draft'?'disabled':'')+'>'+(j.status==='draft'?'确认提交给 LibTV':'此任务已存在，请到任务中心查看')+'</button></div>','任务提交单');
}
function taskList(){return '<p class="muted">每 2 秒同步任务状态。生成完成与人工定版分别显示。</p>'+(jobs().length?jobs().map(j=>'<div class="task-row"><div><h3>'+esc(j.title)+'</h3><p>'+esc(taskMessage(j))+'</p><small class="muted">'+esc(j.modelName)+'</small>'+progressTrack(j)+'</div><div class="task-row-state">'+taskBadge(j)+'<div class="actions"><button data-job-details="'+j.id+'">详情</button>'+(j.status==='draft'?'<button data-draft="'+j.id+'">提交单</button>':'')+(j.status==='completed'?'<button data-job-results="'+j.id+'">查看结果</button>':'')+'</div></div></div>').join(''):empty('暂无任务','提交剧本拆解或生图任务后，状态会持续显示在这里。'));}
function showTasks(){dialog('任务中心',taskList());$('dialog').dataset.view='tasks';}
function showAccount(){
 const a=data.account;
 dialog('LibTV 账号与模型','<div class="account-card"><div><h3>'+esc(a.accountName||'尚未连接账号')+'</h3><p>'+(a.connected?'已通过当前服务连接验证':'请在本机完成 LibTV 官方登录，然后验证连接')+'</p></div>'+tag(a.connected?'approved':'needs_attention')+'</div>'+
 '<table class="model-table"><tbody>'+[['剧本拆解','GVLM 3.1','aurora-3-prime'],['MJ 风格图','Style Image V8.2','mj-v8.2'],['Image2 资产','Lib Image 2.5 Pro','lib-image-2.5-s'],['Nano2 清理','General image V2.1','nebula-2.1']].map(r=>'<tr><td>'+r[0]+'</td><td>'+r[1]+'<code>'+r[2]+'</code></td></tr>').join('')+'</tbody></table>'+
 '<p class="muted" style="font-size:12px">四个工序共用 LibTV 账号。模型能力在准备任务时重新核对，认证信息由官方客户端保存在本机，页面不显示凭证。</p><div id="loginResult"></div><div class="dialog-bottom"><button data-login>登录 / 重新登录</button><button class="primary" data-verify>验证连接</button></div>');
}
function showAnalysis(j){
 const p=plan(),result=j.analysis;
 dialog('核对剧本拆解','<p>'+esc(result.summary)+'</p>'+[['characters','角色'],['scenes','场景'],['props','道具']].map(([key,n])=>'<div class="section-heading"><h2>'+n+' · '+result[key].length+'</h2></div><div class="entity-list">'+result[key].map(e=>'<article class="entity-item" style="grid-template-columns:1fr"><div><h3>'+esc(e.name)+'</h3><p>'+esc(e.description)+'</p><blockquote>原文：'+esc(e.quote)+'</blockquote></div></article>').join('')+'</div>').join('')+
 '<div class="notice"><b>画风建议 · 非原文事实</b><br>'+esc(result.stylePrompt)+'</div>'+
 '<div class="dialog-bottom"><button data-close>暂不定版</button><button class="primary" data-approve-analysis="'+j.id+'" data-plan-version="'+(p?.version||0)+'">确认清单，进入风格探索 →</button></div>','原文与设计分开核对');
}
function editPlan(){
 const p=plan(),es=p?.entities||[];
 dialog('编辑资产清单','<p class="muted">可补充服装、年龄或特殊状态。同一角色的不同状态请新建独立条目；新增设计标为“创作补充”。</p><form id="planForm"><div id="planRows">'+es.map((e,i)=>planRow(e,i)).join('')+'</div><button type="button" data-add-entity>＋ 添加资产条目</button><div class="field" style="margin-top:22px"><label for="stylePrompt">整体画风建议</label><textarea id="stylePrompt" name="stylePrompt" rows="3">'+esc(p?.stylePrompt||'')+'</textarea></div><div class="dialog-bottom"><button type="button" data-close>取消</button><button type="submit" class="primary">保存清单</button></div></form>');
 $('planForm').onsubmit=async e=>{e.preventDefault();const rows=[...$('planRows').children].map(r=>{const get=n=>r.querySelector('[name="'+n+'"]').value;return {id:r.dataset.id,name:get('name'),category:get('category'),variant:get('variant'),description:get('description'),quote:get('quote'),origin:get('origin')}});
  try{await api('/api/workflow/plan',{scriptId:selected,expectedVersion:p?.version||0,entities:rows,stylePrompt:$('stylePrompt').value});$('dialog').close();await load(true);toast('资产清单已保存。')}catch(e){toast(e.message)};
 };
}
function planRow(e,i){return '<section class="panel" style="margin-bottom:12px;padding:17px" data-id="'+esc(e.id)+'"><div class="field-row"><div class="field"><label>名称</label><input name="name" value="'+esc(e.name)+'" required maxlength="80"></div><div class="field"><label>类型</label><select name="category">'+Object.entries(names).filter(([k])=>k!=='shot').map(([k,n])=>'<option value="'+k+'" '+(e.category===k?'selected':'')+'>'+n+'</option>').join('')+'</select></div></div><div class="field-row"><div class="field"><label>状态 / 服装</label><input name="variant" value="'+esc(e.variant)+'" required maxlength="100"></div><div class="field"><label>设定来源</label><select name="origin"><option value="script" '+(e.origin==='script'?'selected':'')+'>原文明确</option><option value="proposal" '+(e.origin==='proposal'?'selected':'')+'>创作补充</option></select></div></div><div class="field"><label>外观与制作要求</label><textarea name="description" rows="2" style="min-height:70px">'+esc(e.description)+'</textarea></div><div class="field"><label>原文依据（连续原文，创作补充可留空）</label><input name="quote" value="'+esc(e.quote)+'"></div><button type="button" data-remove-row class="text-button danger">移除此条</button></section>';}
function showOutput(j,o){
 const checks={
  character:['身份、服装和比例与设定一致','手部、面部和视角没有明显错误'],
  scene:['建筑、空间布局和关键陈设与剧本一致','出入口、行动空间、透视与光向清楚，空场无多余人物'],
  prop:['造型、材质、尺度和连接结构与设定一致','各视图来自同一物体，提柄、开口和底座等结构合理'],
  effect:['形态、颜色和作用范围与设定一致','轮廓与层次清楚，适合后续合成']
 }[j.category]||['外观、结构与设定一致','视角、尺度和关键细节没有明显错误'];
 const reviewChecks=[...checks,'风格与同组资产保持一致','画面没有多余文字和拼接瑕疵',...(j.recipe==='clean'?['清理前后主体、结构、构图和光向保持一致']:[])];
 const source=j.references[0],sourceTask=source&&data.tasks.find(t=>t.id===source.taskId);
 dialog(j.title+' · 候选 '+o.id.split('-').at(-1),'<div class="review-layout"><div><div class="review-preview"><img src="'+media(o.file)+'" alt="'+esc(j.title)+'"></div>'+(j.recipe==='clean'&&sourceTask?'<div class="compare-pair"><figure><img src="'+thumb(sourceTask.id)+'" alt="清理前原图"><figcaption>原图 · 设计基准</figcaption></figure><figure><img src="'+thumb(o.id)+'" alt="清理后结果"><figcaption>Nano2 清理结果</figcaption></figure></div>':'')+'<a class="text-button" style="display:inline-block;margin-top:8px;font-size:12px" href="'+media(o.file)+'" target="_blank" rel="noopener">打开原尺寸图片 ↗</a></div>'+
 '<div class="review-form">'+tag(o.review)+'<h3 style="margin-top:20px">这版是否可以继续制作？</h3><ul class="check-list">'+reviewChecks.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul><label for="reviewNote">审核意见 / 需要修改的地方</label><textarea id="reviewNote" placeholder="写清具体位置、问题和期望修正，并说明需要保留的结构、外观或光向。"></textarea><div class="actions"><button data-review-result="'+o.id+'" data-job="'+j.id+'" data-decision="changes_requested">退回修改</button><button class="primary" data-review-result="'+o.id+'" data-job="'+j.id+'" data-decision="approved">选用并定版</button></div><p class="muted" style="font-size:10px;margin-top:12px">退回只记录意见。后续返修会先生成提交单，由你确认后执行。</p></div></div>','对比与审核');
}
async function showOriginal(){try{const s=await api('/api/scripts/'+selected);dialog(s.filename,'<pre class="script-content">'+esc(s.text)+'</pre>','剧本原文')}catch(e){toast(e.message)}}
async function act(button,fn){if(busy)return;busy=true;button.disabled=true;try{await fn()}catch(e){toast(e.message)}finally{busy=false;if(button.isConnected)button.disabled=false;}}
document.addEventListener('click',async e=>{
 const b=e.target.closest('button,a[data-action]');if(!b)return;
 if(b.dataset.page||b.dataset.nav)return navigate(b.dataset.page||b.dataset.nav);
 if(b.hasAttribute('data-import'))return $('scriptFile').click();
 if(b.hasAttribute('data-close'))return $('dialog').close();
 if(b.hasAttribute('data-reload'))return load(true);
 if(b.dataset.openArchive)return showArchive(b.dataset.openArchive,true);
 if(b.dataset.backArchive)return showArchive(b.dataset.backArchive);
 if(b.dataset.archiveStage){archiveStage=b.dataset.archiveStage;return showArchive(archiveKey);}
 if(b.dataset.archiveImage)return archiveImage(b.dataset.archiveImage);
 if(b.dataset.archiveReview)return archiveImage(b.dataset.archiveReview,true);
 if(b.dataset.archiveReference){if(!['style','asset','clean'].includes(page)||!$('composeForm'))return toast('先展开右侧制作区，再从档案中选择参考。');$('dialog').close();return addReference(b.dataset.archiveReference);}
 if(b.hasAttribute('data-refresh-progress'))return pollProgress();
 if(b.dataset.jobDetails)return showTaskDetails(data.jobs.find(j=>j.id===b.dataset.jobDetails));
 if(b.dataset.jobResults){const j=data.jobs.find(j=>j.id===b.dataset.jobResults);$('dialog').close();if(j?.analysis)return showAnalysis(j);if(j)return targetEntity(j.recipe,j.entityId);return;}
 if(b.dataset.warehouseFilter){warehouseCategory=b.dataset.warehouseFilter;return renderWarehouse();}
 if(b.hasAttribute('data-add-reference'))return addReference(b.dataset.addReference);
 if(b.dataset.filter){saveDraft();category=b.dataset.filter;return render();}
 if(b.dataset.entity){$('dialog').close();return targetEntity(b.dataset.recipe,b.dataset.entity);}
 if(b.hasAttribute('data-original'))return showOriginal();
 if(b.hasAttribute('data-edit-plan'))return editPlan();
 if(b.hasAttribute('data-add-entity'))return $('planRows').insertAdjacentHTML('beforeend',planRow({id:'entity-'+crypto.randomUUID().slice(0,12),name:'',category:'character',variant:'基础设定',description:'',quote:'',origin:'proposal'},$('planRows').children.length));
 if(b.hasAttribute('data-remove-row'))return b.closest('[data-id]').remove();
 if(b.hasAttribute('data-analyze'))return prepare({recipe:'analyze',scriptId:selected,scope:selected,title:currentScript().filename+' · 资产拆解',sourceIds:[]});
 if(b.dataset.analysis)return showAnalysis(data.jobs.find(j=>j.id===b.dataset.analysis));
 if(b.dataset.draft)return showDraft(data.jobs.find(j=>j.id===b.dataset.draft));
 if(b.dataset.preview){const t=data.tasks.find(t=>t.id===b.dataset.preview);if(t)dialog(t.title,'<img src="'+media(t.file)+'" alt="'+esc(t.title)+'"><p class="muted" style="font-size:12px;margin-top:18px">历史已选资产。此处浏览不会改变原项目审核记录。</p>');return;}
 if(b.dataset.output){const j=data.jobs.find(j=>j.id===b.dataset.job);return showOutput(j,j.outputs.find(o=>o.id===b.dataset.output));}
 if(b.dataset.repair){const j=data.jobs.find(j=>j.id===b.dataset.job),note=[...j.reviews].reverse().find(r=>r.outputId===b.dataset.repair&&r.decision==='changes_requested')?.note;if(!note)return toast('请先填写具体修改意见。');return prepare({recipe:j.recipe,scope:j.scope,entityId:j.entityId,category:j.category,title:j.title+' · 返修',prompt:j.prompt,sourceIds:[],settings:j.settings,repairOf:b.dataset.repair,repairNote:note});}
 if(b.dataset.next){const j=data.jobs.find(j=>j.id===b.dataset.next);return targetEntity(b.dataset.recipe,j.entityId,'result-'+b.dataset.outputId);}
 if(b.dataset.submit)return act(b,async()=>{const r=await api('/api/workflow/submit',{jobId:b.dataset.submit});focusedJobId=r.job.id;taskStartedAt.set(r.job.id,Date.now());$('dialog').close();busy=false;await load(true);toast('任务已接收，下面的进度条会持续更新。');});
 if(b.dataset.recover)return act(b,async()=>{const r=await api('/api/workflow/recover',{jobId:b.dataset.recover});focusedJobId=r.job.id;taskStartedAt.set(r.job.id,Date.now());$('dialog').close();busy=false;await load(true);toast('正在核对并收取原任务，不重新生成。');});
 if(b.dataset.approveAnalysis)return act(b,async()=>{await api('/api/workflow/review',{jobId:b.dataset.approveAnalysis,decision:'approved',note:'核对原文后确认清单',planVersion:Number(b.dataset.planVersion)});$('dialog').close();busy=false;await load(true);navigate('script');toast('清单已确认。可以为每个对象探索风格，也可继续编辑设定。');});
 if(b.dataset.reviewResult)return act(b,async()=>{const returnTo=$('dialog').dataset.archiveReturn,j=data.jobs.find(j=>j.id===b.dataset.job),o=j.outputs.find(o=>o.id===b.dataset.reviewResult),note=$('reviewNote').value.trim();await api('/api/workflow/review',{jobId:j.id,outputId:o.id,sha256:o.sha256,decision:b.dataset.decision,note});$('dialog').close();busy=false;await load(true);if(returnTo)showArchive(returnTo);toast(b.dataset.decision==='approved'?'当前版本已定版，可继续制作或导出。':'修改意见已记录。原版本保留。');});
 if(b.hasAttribute('data-export')&&!b.hasAttribute('data-export-partial')&&coverage().missing.length){const c=coverage();dialog('清单尚未全部完成','<p>'+c.ready+' / '+c.total+' 项已完成资产与清理。以下对象仍需制作或审核：</p><ul>'+c.missing.map(e=>'<li>'+esc(names[e.category]+' · '+e.name)+'</li>').join('')+'</ul><p class="muted">可以先导出当前已定版的部分，未完成的对象会列在交付清单中。</p><div class="dialog-bottom"><button data-close>继续制作</button><button class="primary" data-export data-export-partial>仅打包当前已定版部分</button></div>','部分交付');return;}
 if(b.hasAttribute('data-export'))return act(b,async()=>{const {bundle}=await api('/api/workflow/bundle',{scope:selected});const name='资产研究室-'+currentScript().filename.replace(/\.[^.]+$/,'')+'.zip';dialog('资产包已保存到本机','<div class="notice good">'+bundle.assetCount+' 份已审核资产已保存，并通过压缩包完整性检查。</div><p>'+esc(name)+' · '+(bundle.bytes/1024/1024).toFixed(2)+' MB</p><label for="bundlePath">本机保存位置</label><input id="bundlePath" readonly value="'+esc(bundle.localPath)+'"><div class="dialog-bottom"><button data-copy-bundle>复制路径</button><button class="primary" data-open-bundle="'+bundle.id+'" data-scope="'+bundle.scope+'">打开所在文件夹</button><a id="assetDownload" class="text-button" href="'+media(bundle.file)+'" download="'+esc(name)+'">通过浏览器下载 ↓</a></div><p class="muted">本机交付包已经保存。浏览器另存为独立操作；若浏览器未保存，可直接使用上方本机文件。</p>','交付已归档');$('assetDownload').addEventListener('click',()=>toast('已发起浏览器下载；本机交付包仍可直接使用。'));});
 if(b.dataset.openBundle)return act(b,async()=>{await api('/api/workflow/open-bundle',{scope:b.dataset.scope,bundleId:b.dataset.openBundle});toast('已打开交付文件所在位置。');});
 if(b.hasAttribute('data-copy-bundle'))return act(b,async()=>{await navigator.clipboard.writeText($('bundlePath').value);toast('保存路径已复制。');});
 if(b.hasAttribute('data-verify'))return act(b,async()=>{await api('/api/execution/connect',{provider:'libtv'});busy=false;await load(true);showAccount();toast('LibTV 连接已验证。');});
 if(b.hasAttribute('data-login'))return act(b,async()=>{const r=await api('/api/execution/login',{});const u=r.loginUrl;const el=$('loginResult');if(u&&new URL(u).origin==='https://www.liblib.tv')el.innerHTML='<div class="notice"><a href="'+esc(u)+'" target="_blank" rel="noopener">打开 LibTV 官方登录页面 ↗</a><p>完成后点击验证连接。</p></div>';else el.textContent=r.loginPending?'登录正在等待完成，请稍后验证连接。':'请完成官方客户端登录，再验证连接。';});
});
document.addEventListener('input',e=>{if(e.target.closest('#composeForm'))saveDraft();});
window.addEventListener('pagehide',saveDraft);
document.addEventListener('change',e=>{if(e.target.id==='entitySelect'){saveDraft();entityId=e.target.value;try{localStorage.setItem('asset-lab:entity:'+selected,entityId);}catch{}render();}if(e.target.id==='legacyRefs'){saveDraft();render();}});
$('scriptSelect').onchange=e=>{saveDraft();selected=e.target.value;entityId='';warehouseSelection.clear();page='script';openSteps.add('script');localStorage.setItem('asset-lab:script',selected);localStorage.setItem('asset-lab:page',page);render();};
$('scriptFile').onchange=e=>upload(e.target.files[0]);$('importScript').onclick=()=>$('scriptFile').click();$('accountButton').onclick=showAccount;$('taskButton').onclick=showTasks;
$('closeDialog').onclick=()=>$('dialog').close();
$('dialog').addEventListener('click',e=>{if(e.target===$('dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()}});
$('helpButton').onclick=()=>dialog('从剧本到资产的六步','<ol style="line-height:2.4"><li><b>导入剧本：</b>保存原文，调用 LibTV 拆解角色、场景、道具。</li><li><b>核对清单：</b>检查原文依据，补充服装与状态，确认制作对象。</li><li><b>探索风格：</b>MJ 一次提供4张候选，比较后选用。</li><li><b>制作资产：</b>Image2 使用已选风格制作具体设定图。</li><li><b>保真洗图：</b>Nano2 清理已选图，对照前后结果审核。</li><li><b>定版导出：</b>只打包通过审核的有效版本，附来源和记录。</li></ol><div class="notice">研究室制作的是二维图片资产与设定参考。三维模型、骨骼和动画继续在原工作台的建模与导演流程处理。</div>');
$('warehouseSearch').oninput=e=>{warehouseQuery=e.target.value;renderWarehouse();};
$('includeHistory').onchange=e=>{includeHistory=e.target.checked;renderWarehouse();};
$('batchClean').onclick=batchClean;
$('toggleWarehouse').onclick=()=>{document.body.classList.add('warehouse-collapsed');$('toggleWarehouse').setAttribute('aria-expanded','false');};
$('showWarehouse').onclick=()=>{document.body.classList.remove('warehouse-collapsed');$('toggleWarehouse').setAttribute('aria-expanded','true');};
document.addEventListener('change',e=>{if(e.target.dataset.selectSource){const id=e.target.dataset.selectSource;e.target.checked?warehouseSelection.add(id):warehouseSelection.delete(id);updateWarehouseSelection();}});
document.addEventListener('dragstart',e=>{const card=e.target.closest('[data-drag-source]');if(card){e.dataTransfer.setData('application/x-asset-lab-source',card.dataset.dragSource);e.dataTransfer.effectAllowed='copy';}});
document.addEventListener('dragover',e=>{if(e.target.closest('.references')&&e.dataTransfer.types.includes('application/x-asset-lab-source')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
document.addEventListener('drop',e=>{if(e.target.closest('.references')){const id=e.dataTransfer.getData('application/x-asset-lab-source');if(id){e.preventDefault();addReference(id);}}});
load(true);setInterval(()=>{if(!document.hidden)pollProgress()},2000);setInterval(()=>{if(!document.hidden)load()},30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollProgress()});
