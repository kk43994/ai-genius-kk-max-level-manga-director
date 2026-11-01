import {escapeHTML as esc,categories} from './model.js';

// Stored tokens use stable asset IDs; names are presentation only. A shot binds
// one state (and optionally one approved image version) per asset.
const tokenPattern=()=>/\{\{asset:([a-zA-Z0-9_-]{1,80})\}\}/g;
export const assetToken=id=>`{{asset:${id}}}`;
export const referenceFields=['beat','imagePrompt','videoPrompt'];
export function referenceLabel(result,shot,assetId){
  const asset=result.assets.find(a=>a.id===assetId),ref=shot.references.find(r=>r.assetId===assetId);
  if(!asset)return '已移除的物料';
  const duplicate=result.assets.filter(a=>a.name===asset.name).length>1;
  const name=asset.name+(duplicate?' '+String(result.assets.indexOf(asset)+1).padStart(3,'0'):'');
  return name+' · '+(asset.states.find(s=>s.id===ref?.stateId)?.name||'未选状态');
}
export function readableText(text,result,shot){return (text||'').replace(tokenPattern(),(_,id)=>`〔${referenceLabel(result,shot,id)}〕`);}
export function storedText(text,result,shot){
  // Only explicit brackets matching a selected asset become references.
  const entries=shot.references.map(r=>[referenceLabel(result,shot,r.assetId),r.assetId]);
  return text.replace(/〔([^〔〕]+)〕/g,(whole,label)=>{
    const matches=entries.filter(([name])=>name===label);return matches.length===1?assetToken(matches[0][1]):whole;
  });
}
export function linkedText(text,result,shot){
  let html='',at=0;
  for(const match of (text||'').matchAll(tokenPattern())){
    html+=esc(text.slice(at,match.index));const index=result.assets.findIndex(a=>a.id===match[1]);
    html+=index<0?'<span class="wf-note">引用已失效</span>':`<button class="board-mention" data-board-reference-open="${index}" data-shot-id="${esc(shot.id)}" title="打开物料档案">〔${esc(referenceLabel(result,shot,match[1]))}〕</button>`;
    at=match.index+match[0].length;
  }
  return html+esc((text||'').slice(at));
}
export function referenceField(label,path,shot,result,max=3000){
  const key=path.split('.').at(-1),value=shot[key]||'';
  return `<div class="board-reference-field"><div class="board-field-title"><b>${esc(label)}</b><button data-board-reference-picker="${esc(path)}">@ 插入物料</button></div><textarea aria-label="${esc(label)}" rows="4" maxlength="${max}" data-wf-production-field="${esc(path)}" data-reference-text>${esc(readableText(value,result,shot))}</textarea><div class="board-linked-text" data-reference-preview="${esc(path)}" aria-label="${esc(label)}引用预览">${linkedText(value,result,shot)}</div><div data-reference-picker="${esc(path)}" hidden></div></div>`;
}
export function referencePicker(result,shot,path,query=''){
  const filtered=result.assets.flatMap((asset,index)=>asset.states.filter(s=>s.sceneIds?.includes(shot.sceneId)).map(state=>({asset,index,state})))
    .filter(({asset,state})=>(asset.name+' '+state.name).toLowerCase().includes(query.toLowerCase()));
  return `<div class="board-reference-picker" role="group" aria-label="选择引用物料"><div class="board-field-title"><b>选物料与状态</b><button data-board-reference-picker-close>关闭</button></div><input type="search" aria-label="搜索引用物料" placeholder="搜索角色、场景、道具" data-reference-search value="${esc(query)}"><div class="board-reference-options">${filtered.map(({asset,index,state})=>`<button data-reference-insert="${esc(asset.id)}" data-reference-state="${esc(state.id)}" data-reference-path="${esc(path)}"><span>${esc(categories[asset.category])}</span><strong>${esc(asset.name)}${result.assets.filter(a=>a.name===asset.name).length>1?' '+String(index+1).padStart(3,'0'):''}</strong><small>${esc(state.name)}</small></button>`).join('')||'<p class="wf-muted">本场次没有匹配物料，可在档案里补充适用场次。</p>'}</div><p class="wf-muted">选择后绑定档案并连接画布；图片需要单独制作、审核。</p></div>`;
}
export function bindReference(shot,asset,stateId){
  if(!asset?.states.some(s=>s.id===stateId&&s.sceneIds?.includes(shot.sceneId)))return false;
  const found=shot.references.find(r=>r.assetId===asset.id);
  if(found){if(found.stateId!==stateId){found.stateId=stateId;delete found.revisionId;}}
  else {if(shot.references.length>=20)return false;shot.references.push({assetId:asset.id,stateId});}
  return true;
}
export function removeReference(shot,assetId){
  if(referenceFields.some(key=>(shot[key]||'').includes(assetToken(assetId))))return false;
  shot.references=shot.references.filter(r=>r.assetId!==assetId);return true;
}
export function appendManualProp(result,shotIndex,{id,name,design,prompt}){
  const shot=result.shots[shotIndex];
  if(!shot||!name?.trim()||!design?.trim()||prompt?.trim().length<20||!prompt||result.assets.length>=100||shot.references.length>=20)return null;
  const asset={id,category:'prop',origin:'manual',name:name.trim(),sourceIds:[],evidence:structuredClone(shot.evidence.slice(0,1)),
    design:design.trim(),creativeChoices:['用户补充道具，外观属于创作选择；原文引用用于标记使用场次。'],
    states:[{id:'base',name:'基础状态',description:design.trim(),sceneIds:[shot.sceneId],imagePrompt:prompt.trim()}]};
  result.assets.push(asset);bindReference(shot,asset,'base');return asset;
}
