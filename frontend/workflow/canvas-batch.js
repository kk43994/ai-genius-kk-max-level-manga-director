import {escapeHTML as esc} from './model.js';
import {imageModelPicker,selectedImageModel} from './image-models.js';
import {missingStoryboardShots,selectedStoryboardShots} from './generation-batch.js';
import {referenceCards} from './production.js';

export function canvasBatchPanel(o){
 const {job,result,assets,tasks,selection,draft={},catalog,contracts,busy,loading,error,explicit=false}=o;
 const ready=(explicit?selectedStoryboardShots:missingStoryboardShots)({job,result,assets,tasks,selection,limit:Infinity},referenceCards),selected=new Set(draft.shotIds||[]);
 const skipped=explicit?result.shots.map((shot,index)=>({shot,index})).filter(r=>selected.has(r.shot.id)&&!ready.some(v=>v.shot.id===r.shot.id)):[];
 const model=selectedImageModel(draft,catalog);
 return `<p class="wf-muted">勾选本批要制作的镜头，最多 8 镜。${explicit?'这次明确生成新版本，已有图片保留；尚有未结束任务的镜头先恢复原任务。':'参考未齐、已有图片或已有任务的镜头不会重复提交。'}</p>${skipped.length?`<section class="wf-note"><strong>${skipped.length} 个所选镜头暂不能生成</strong><p>请核对制作依据、固定参考或查询未结束的原任务。</p>${skipped.map(({shot,index})=>`<button type="button" data-quick-edit="${index}">核对镜头 ${String(index+1).padStart(3,'0')} · ${esc(shot.purpose)}</button>`).join('')}</section>`:''}<form data-wf-form="board-generation" class="wf-compose">${imageModelPicker({draft,catalog,contracts,loading,error,ratio:result.aspectRatio})}<div class="canvas-batch-list">${ready.map(({shot,index})=>`<label><input type="checkbox" name="shotIds" value="${esc(shot.id)}" ${selected.has(shot.id)?'checked':''}><span><strong>镜头 ${String(index+1).padStart(3,'0')} · ${esc(shot.purpose)}</strong><small>${esc(shot.framing)} · ${shot.references.length} 项参考已固定</small></span></label>`).join('')||'<p class="wf-empty">目前没有可批量补图的镜头。可以关闭面板，点击缺图镜头先补齐并固定参考。</p>'}</div><button class="primary" type="submit" data-generation-missing-shots data-generation-selected-shots ${explicit?'data-generation-explicit-redraw':''} ${busy||!ready.length||!contracts?.[model.id]?.verified?'disabled':''}>准备勾选镜头</button><small class="wf-muted">每镜一组，使用各镜已保存要求。准备后统一核对张数、参考和费用，再并发提交。</small></form>`;
}
