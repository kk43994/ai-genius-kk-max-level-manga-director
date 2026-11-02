import {escapeHTML as esc} from './model.js';
import {analysisArrayItem} from './analysis-records.js';

const labels={name:'名称',title:'标题',summary:'内容',text:'台词内容',value:'内容',status:'依据类型',quote:'引用原文',startLine:'起始行',endLine:'结束行',evidence:'原文依据',identity:'身份',aliases:'别名',appearance:'外貌',costume:'服装',relations:'人物关系',description:'说明',direction:'动作与语气',stateChange:'状态变化',order:'顺序',expression:'时间表达',timeOfDay:'时段',explicitDate:'日期',relativeDescription:'时间关系',narrativeLayer:'叙事层',kind:'台词类型',speakerLabel:'自填说话人',question:'问题',reason:'原因',blocking:'制作前需确认',confidence:'置信度',targetCharacterId:'关联人物',presentCharacterIds:'实际在场人物',mentionedCharacterIds:'仅被提及人物',locationIds:'关联地点',timeIds:'关联时间',parentLocationId:'上级地点',relationToTimeId:'关联时间',speakerId:'说话人',addresseeIds:'对谁说',characterIds:'相关人物',sceneId:'所属场次',eventId:'关联事件',followsEventIds:'前序事件',causedByEventIds:'原因事件',recordIds:'相关记录'};
const enums={status:{explicit:'原文明示',inferred:'推断',unknown:'未说明'},kind:{dialogue:'对白',inner_monologue:'内心独白',narration:'旁白',voiceover:'画外音',offscreen:'画外对白',system_voice:'系统音',unknown:'待确认'},narrativeLayer:{present:'现实',flashback:'闪回',dream:'梦境',imagined:'想象',reported:'转述',unknown:'待确认'}};
export function analysisDraft(job){return {expectedVersion:job.reviewVersion||0,expectedResultHash:job.resultHash,result:structuredClone(job.result||job.draftResult)};}
export function analysisDraftAfterSave(submitted,current,saved){
 if(!current||JSON.stringify([submitted.result,submitted.raw])===JSON.stringify([current.result,current.raw]))return null;
 return {...structuredClone(current),expectedVersion:saved.reviewVersion||0,expectedResultHash:saved.resultHash};
}
export function analysisField(value,path,label=labels[path.split('.').at(-1)]||'内容',result=null){
 const key=path.split('.').at(-1),attr=`data-wf-analysis-field="${esc(path)}"`;
 const foreign={targetCharacterId:'characters',presentCharacterIds:'characters',mentionedCharacterIds:'characters',locationIds:'locations',timeIds:'times',parentLocationId:'locations',relationToTimeId:'times',speakerId:'characters',addresseeIds:'characters',characterIds:'characters',sceneId:'scenes',eventId:'events',followsEventIds:'events',causedByEventIds:'events'}[key];
 if(foreign&&result){const choices=result[foreign]||[],multiple=Array.isArray(value),missing=(multiple?value:[value]).filter(id=>id&&!choices.some(r=>r.id===id));return `<label>${esc(label)}<select ${attr} ${multiple?'multiple size="4"':''}>${multiple?'':'<option value="">未说明</option>'}${missing.map(id=>`<option value="${esc(id)}" selected>关联已缺失，请重新选择</option>`).join('')}${choices.map(r=>`<option value="${esc(r.id)}" ${(multiple?value.includes(r.id):value===r.id)?'selected':''}>${esc(r.name||r.title||r.expression||r.summary||'相关记录')}</option>`).join('')}</select></label>`;}
 if(Array.isArray(value)&&analysisArrayItem(path)!==undefined)return `<details class="analysis-edit-nested"><summary>${esc(label)} · ${value.length}</summary>${value.map((v,i)=>`<div class="analysis-array-row">${analysisField(v,path+'.'+i,`${label} ${i+1}`,result)}<button data-analysis-array-remove="${esc(path)}" data-array-index="${i}">删除这一项</button></div>`).join('')}<button data-analysis-array-add="${esc(path)}">＋ 添加${esc(label)}</button></details>`;
 if(value!==null&&typeof value==='object')return `<details class="analysis-edit-nested"><summary>${esc(label)}</summary>${Object.entries(value).map(([k,v])=>analysisField(v,path+'.'+k,Array.isArray(value)?`${label} ${Number(k)+1}`:labels[k]||'内容',result)).join('')}</details>`;
 if(key==='id'||key==='sourceRevision'||key.endsWith('Id')||key.endsWith('Ids'))return '';
 if(enums[key])return `<label>${esc(label)}<select ${attr}>${Object.entries(enums[key]).map(([v,n])=>`<option value="${v}" ${v===value?'selected':''}>${n}</option>`).join('')}</select></label>`;
 if(typeof value==='boolean')return `<label><input type="checkbox" ${attr} ${value?'checked':''}>${esc(label)}</label>`;
 if(typeof value==='number')return `<label>${esc(label)}<input type="number" ${attr} value="${value}"></label>`;
 if(['name','title','speakerLabel','expression','explicitDate','timeOfDay'].includes(key)&&!String(value??'').includes('\n'))return `<label>${esc(label)}<input type="text" ${attr} ${value===null?'data-analysis-null':''} value="${esc(value??'')}"></label>`;
 return `<label>${esc(label)}<textarea ${attr} ${value===null?'data-analysis-null':''}>${esc(value??'')}</textarea></label>`;
}
export function analysisIssues(issues,{editable=true}={}){
 return issues.length?`<section class="analysis-issues" aria-label="原文核对问题"><h4>${editable?'待核对内容':'AI 初稿的原始问题'} · ${issues.length}</h4>${issues.map((i,n)=>`<article class="analysis-issue"><strong>${esc(i.label||'分析内容')}</strong><p>${esc(i.message)}</p>${i.returnedText!==undefined?`<div class="analysis-compare"><div><b>${editable?'AI 返回内容 · 标红待改':'AI 初稿内容'}</b>${editable?analysisField(i.returnedText,i.path,'修改内容'):`<blockquote>${esc(i.returnedText)}</blockquote>`}</div><div><b>对应原文</b><pre>${esc(i.sourceText||'当前行号未找到原文，请修改引用范围。')}</pre>${editable&&i.sourceText&&i.code==='source_quote'?`<button data-wf-action="analysis-use-source" data-analysis-issue="${n}">采用这段原文</button>`:''}</div></div>`:''}</article>`).join('')}</section>`:'';
}
export function analysisReviewControls(job,draft,busy){
 const returned=job.result||job.draftResult;
 if(!returned&&!job.returnedText)return '';
 return `<div class="wf-actions"><span data-analysis-draft-status>${draft?'有未保存修改':job.manuallyEdited?'人工修改已保存':'可直接修改，不增加 AI 调用'}</span><button class="primary" data-wf-action="analysis-review-save" ${busy||job.canRefresh?'disabled':''}>保存修改并核对</button>${draft?`<button data-wf-action="analysis-review-discard" ${busy?'disabled':''}>恢复上次保存</button>`:''}</div>${job.structuredDraft===false||draft?.raw!==undefined?`<details open><summary>修改返回内容</summary><p>结构尚不完整，原始内容已保留；补齐后保存即可重新核对，无需重新生成。</p><textarea data-wf-analysis-json aria-label="分析完整内容">${esc(draft?.raw??(returned?JSON.stringify(returned,null,2):job.returnedText))}</textarea></details>`:''}`;
}
