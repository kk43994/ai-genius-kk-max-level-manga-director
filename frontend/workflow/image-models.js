import {escapeHTML as esc} from './model.js';

export const DEFAULT_IMAGE_MODEL='Lib Image 2.5 Pro';
const labels={ratio:'画幅',aspectRatio:'画幅',resolution:'分辨率',quality:'质量',background:'背景',count:'每组张数',seed:'随机种子',negativePrompt:'避免出现',stylize:'风格化程度',style:'风格模式'};
function controlSchema(schema){
 const variants=schema.anyOf||schema.oneOf;
 if(variants){const concrete=variants.filter(s=>s.type!=='null');if(concrete.length===1)return {...schema,anyOf:undefined,oneOf:undefined,...concrete[0]};}
 if(Array.isArray(schema.type)&&schema.type.filter(t=>t!=='null').length===1)return {...schema,type:schema.type.find(t=>t!=='null')};
 return schema;
}
export function selectedImageModel(draft,catalog){
 const requested=draft.modelId||DEFAULT_IMAGE_MODEL;
 return (catalog?.items||[]).find(m=>m.id===requested||m.name===requested)||{id:requested,name:requested};
}
export function settingValue(schema,value){
 schema=controlSchema(schema);
 if(schema.enum){const found=schema.enum.find(v=>String(v)===String(value));if(found===undefined)throw new Error('所选参数已不适用于当前模型，请重新选择。');return found;}
 if(schema.type==='integer'||schema.type==='number'){const n=Number(value);if(!Number.isFinite(n))throw new Error('请填写有效的数字参数。');return n;}
 if(schema.type==='boolean')return value==='true';
 if(schema.type==='object'||schema.type==='array'||schema.anyOf||schema.oneOf)return JSON.parse(value);
 return value;
}
export function collectImageSettings(inputs,contract){
 if(!contract?.verified)throw new Error('请先读取所选模型参数，再准备生成。');
 const settings={};
 for(const [name,schema] of Object.entries(contract.schema.properties||{})){
  const value=inputs['param:'+name];
  if(value!==undefined&&value!=='')settings[name]=settingValue(schema,value);
 }
 settings.count??=1;
 return settings;
}
export function imageModelPicker({draft={},catalog,contracts={},loading,error,ratio}){
 const selected=selectedImageModel(draft,catalog),contract=contracts[selected.id];
 const models=catalog?.items?.length?catalog.items:[selected];
 const extra=models.some(m=>m.id===selected.id)?[]:[selected];
 const options=[...extra,...models].map(m=>`<option value="${esc(m.id)}" ${m.id===selected.id?'selected':''}>${esc(m.name)}${m.name===DEFAULT_IMAGE_MODEL?' · 默认':''}</option>`).join('');
 const controls=Object.entries(contract?.schema?.properties||{}).map(([name,raw])=>{
  const schema=controlSchema(raw);
  const title=labels[name]||schema.title||name,required=contract.schema.required?.includes(name);
  let value=draft['param:'+name]??(name==='count'?(schema.enum?.includes(1)?1:schema.enum?.[0]??1):name==='ratio'&&schema.enum?.includes(ratio)?ratio:schema.default??schema.enum?.[0]??'');
  const common=`name="param:${esc(name)}" ${required?'required':''}`;
  let control;
  if(schema.enum){const choices=schema.enum.filter(v=>name!=='count'||Number.isInteger(v)&&v>=1&&v<=4);control=`<select ${common}>${choices.map(v=>`<option value="${esc(v)}" ${String(value)===String(v)?'selected':''}>${esc(v)}</option>`).join('')}</select>`;}
  else if(schema.type==='boolean')control=`<select ${common}><option value="false" ${String(value)!=='true'?'selected':''}>关闭</option><option value="true" ${String(value)==='true'?'selected':''}>开启</option></select>`;
  else if(['integer','number'].includes(schema.type))control=`<input ${common} type="number" step="${schema.type==='integer'?'1':'any'}" value="${esc(value)}" ${schema.minimum!==undefined?`min="${esc(schema.minimum)}"`:''} ${schema.maximum!==undefined?`max="${esc(name==='count'?Math.min(4,schema.maximum):schema.maximum)}"`:name==='count'?'max="4"':''}>`;
  else if(schema.type==='object'||schema.type==='array'||schema.anyOf||schema.oneOf)control=`<textarea ${common} rows="2" placeholder="JSON">${esc(typeof value==='object'?JSON.stringify(value):value)}</textarea>`;
  else control=`<input ${common} value="${esc(value)}" maxlength="${Math.min(schema.maxLength||4000,20000)}">`;
  return `<label>${esc(title)}${control}</label>`;
 }).join('');
 return `<section class="creator-model-picker" aria-label="图片模型与参数"><label>图片模型<select name="modelId" data-image-model ${loading?'disabled':''}>${options}</select></label><button type="button" data-image-models-refresh ${loading?'disabled':''}>${loading?'正在读取模型…':'刷新 LibTV 模型'}</button>${error?`<p class="wf-note" role="status">${esc(error)}</p>`:''}${contract?.verified?`<details><summary>模型参数 · ${esc(selected.name)}</summary><div class="wf-form-grid">${controls}</div></details>`:'<p class="wf-muted">读取官方模型参数后即可生成。</p>'}</section>`;
}
