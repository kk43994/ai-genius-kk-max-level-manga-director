import {escapeHTML as esc} from './model.js';
import {analysisField,analysisReviewControls} from './analysis-edit.js';

export const recordGroups={characters:'角色',scenes:'场次',locations:'地点',events:'事件',dialogues:'台词',times:'时间',uncertainties:'疑点'};
const fact=()=>({value:null,status:'unknown',evidence:[]});
export function newAnalysisRecord(group,id,result){
 const base={id,status:'unknown',evidence:[]},order=Math.max(0,...(result[group]||[]).map(r=>r.order||0))+1;
 const types={
  characters:{...base,name:'新角色',aliases:[],identity:fact(),appearance:[],costume:[],relations:[]},
  scenes:{...base,title:'新场次',order,locationIds:[],timeIds:[],presentCharacterIds:[],mentionedCharacterIds:[],summary:'',startLine:1,endLine:1},
  locations:{...base,name:'新地点',parentLocationId:null,description:fact()},
  times:{...base,expression:'新时间',timeOfDay:null,explicitDate:null,relationToTimeId:null,relativeDescription:null,narrativeLayer:'unknown'},
  events:{...base,sceneId:'scene_unassigned',order,summary:'新事件',characterIds:[],stateChange:fact(),followsEventIds:[],causedByEventIds:[],narrativeLayer:'unknown'},
  dialogues:{...base,sceneId:'scene_unassigned',eventId:null,order,speakerId:null,speakerLabel:null,addresseeIds:[],kind:'unknown',text:'',direction:fact(),startLine:1,endLine:1},
  uncertainties:{id,recordIds:[],category:'other',question:'新疑点',reason:'',blocking:false,evidence:[]}
 };return types[group];
}
export function recordReferences(result,id){
 const found=[];
 for(const [group,records] of Object.entries(result))if(Array.isArray(records))for(const [index,r] of records.entries()){
  if(!r||typeof r!=='object'||r.id===id)continue;
  const scan=(value,key='')=>Array.isArray(value)?value.some(v=>scan(v,key)):value&&typeof value==='object'?Object.entries(value).some(([k,v])=>k!=='id'&&scan(v,k)):/(Id|Ids)$/.test(key)&&value===id;
  if(scan(r))found.push({group,index,id:r.id,label:r.name||r.title||r.summary||r.text||r.expression||r.question||id});
 }return found;
}
export function analysisArrayItem(path){
 const key=path.split('.').at(-1);
 if(['aliases','appearance','costume'].includes(key))return fact();
 if(key==='relations')return {targetCharacterId:'character_unassigned',description:fact()};
 if(key==='evidence')return {startLine:1,endLine:1,quote:''};
 if(key==='recordIds')return 'record_unassigned';
 return undefined;
}
export function analysisRecordPanel({job,draft,group='characters',recordId,removed=[],pendingDelete,busy}){
 const result=draft?.result||job.result||job.draftResult,rows=result?.[group]||[],index=Math.max(0,rows.findIndex(r=>r.id===recordId)),r=rows[index],path=`${group}.${index}`;
 const title=x=>x.name||x.title||x.expression||x.summary||x.text||x.question||'待填写';
 const fields=r?Object.entries(r).filter(([k])=>k!=='id'):[];
 const mainKeys=['name','title','speakerId','kind','text','summary','expression','question','reason'];
 const renderFields=entries=>entries.map(([k,v])=>analysisField(v,path+'.'+k,undefined,result)).join('');
 const linked=r?recordReferences(result,r.id):[];
 const referenceRows=rows=>rows.map(x=>`<p>${recordGroups[x.group]||x.group} · ${esc(x.label.slice(0,80))}</p>`).join('');
 return `<div class="analysis-record-tabs" role="group" aria-label="剧情内容分类">${Object.entries(recordGroups).map(([key,label])=>`<button data-analysis-open="${key}" aria-pressed="${group===key}">${label} ${result[key]?.length||0}</button>`).join('')}</div><div class="analysis-record-tools"><label>当前${recordGroups[group]}<select data-analysis-record-select>${rows.map(x=>`<option value="${esc(x.id)}" ${x.id===r?.id?'selected':''}>${esc(title(x).slice(0,50))}</option>`).join('')}</select></label><button data-analysis-add="${group}">＋ 添加${recordGroups[group]}</button></div>${r?`${renderFields(mainKeys.map(key=>fields.find(([k])=>k===key)).filter(Boolean))}<details><summary>关联、外貌、状态与原文依据</summary>${renderFields(fields.filter(([k])=>!mainKeys.includes(k)))}</details><button data-analysis-delete="${esc(r.id)}" data-analysis-group="${group}">删除这条${recordGroups[group]}</button>${pendingDelete===r.id?`<div class="wf-note" role="alert"><p>${linked.length?`找到 ${linked.length} 条已建立的关联。删除后保留这些内容，并标出缺失关联供你重新选择。`:'从当前分析移除这条记录，原稿与恢复记录保留。'}</p>${referenceRows(linked.slice(0,6))}${linked.length>6?`<details><summary>查看其余 ${linked.length-6} 处关联</summary>${referenceRows(linked.slice(6))}</details>`:''}<button data-analysis-delete-confirm="${esc(r.id)}" data-analysis-group="${group}">确认删除</button><button data-analysis-delete-cancel>取消</button></div>`:''}`:'<p class="wf-muted">暂无此类内容，可直接添加。</p>'}${removed.some(x=>!(result[x.group]||[]).some(r=>r.id===x.record.id))?`<details><summary>已删除内容 · 可恢复</summary>${removed.filter(x=>!(result[x.group]||[]).some(r=>r.id===x.record.id)).map(x=>`<p>${recordGroups[x.group]} · ${esc(title(x.record).slice(0,70))} <button data-analysis-restore="${esc(x.record.id)}">恢复</button></p>`).join('')}</details>`:''}<footer class="canvas-drawer-footer">${analysisReviewControls(job,draft,busy)}<small>原稿保留。修改不会自动覆盖已有分镜和图片；相关制作内容需要重新核对。</small></footer>`;
}
