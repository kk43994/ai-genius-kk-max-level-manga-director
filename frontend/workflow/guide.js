import {stages, recipes, stageLabels, belongsToSelection, defaultPrompt} from './model.js';

// A projection of saved state. It never marks reviews, submits or changes owner.
export function nextAction({project, plan, assets, tasks, bundles = [], selection, taskError = '', styleCount = 1}) {
  const result = (kind, title, detail, extra = {}) => ({kind, title, detail, ...extra});
  if (!project) return result('start', '输入剧本，开始制作', '支持粘贴正文，或导入 TXT、Markdown、DOCX。');
  if (!project.scriptIds.length) return result('import', '先导入剧本', '原文会保存在这个项目中。');
  if (plan.needsReview || !plan.entities.length) return result('plan', '核对自动拆出的资产清单', '确认角色、场景、道具和统一风格，后续制作要求会自动填写。');
  if (taskError) return result('blocked', '任务状态暂时无法读取', '已暂停准备新任务，恢复状态读取后再继续。');
  if (!selection?.providerAccountId || !selection?.spaceId) return result('connect', '连接你的 LibTV 账号', '首次使用需要授权并选择工作空间，项目和剧本已经保存。');
  // An unresolved paid attempt wins even if the plan changed while it ran.
  const live = tasks.find(t => t.submissionAttempted && !['completed', 'failed', 'cancelled'].includes(t.status));
  if (live) return result(live.canRecover ? 'recover' : 'blocked', '等待原任务返回',
    live.canRecover ? '系统只查询和收取原任务，不重复提交。' : '提交结果尚不明确，需要核对原任务记录。', {task: live});
  const foreign = tasks.find(t => !belongsToSelection(t, selection) && t.submissionAttempted);
  const foreignImage = assets.flatMap(a => a.revisions).find(r => r.status === 'ready' && !belongsToSelection(r, selection));
  if (foreign || foreignImage) return result('connect', '切回本项目原来的账号与空间', '已保存的任务和素材属于原账号，一键流程不会替换归属。');
  let done = 0;
  for (const stage of stages) {
    for (const entity of plan.entities) {
      const asset = assets.find(a => a.active && a.entityId === entity.id);
      const versions = (asset?.revisions || []).filter(r => r.status === 'ready' && belongsToSelection(r, selection));
      if (versions.some(r => r.stage === stage && r.review === 'approved')) { done++; continue; }
      const candidates = versions.filter(r => r.stage === stage);
      const pending = candidates.find(r => r.review === 'pending');
      const extra = {stage, entity, done, total: plan.entities.length * 3};
      if (pending) return result('review', `审核 ${entity.name} · ${stageLabels[stage]}`, '查看候选图，保留后继续下一步；有问题可以填写返修意见。', {...extra, revision: pending});
      const previousStage = stage === 'asset' ? 'style' : stage === 'refine' ? 'asset' : null;
      const source = versions.findLast(r => r.stage === previousStage && r.review === 'approved');
      if (previousStage && !source) return result('blocked', '参考图片需要重新确认', '上一阶段尚无有效的审核版本，请先核对素材。', extra);
      const repair = candidates.findLast(r => r.review === 'changes_requested');
      const matching = tasks.filter(t => t.entityId === entity.id && t.recipe === recipes[stage] && belongsToSelection(t, selection)
        && t.workflowSnapshot?.entityVersion === entity.version && t.workflowSnapshot?.styleVersion === plan.styleVersion
        && JSON.stringify(t.sourceRevisionIds || []) === JSON.stringify(source ? [source.id] : []))
        .sort((a,b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id));
      const current = matching.findLast(t => !repair || t.createdAt >= repair.reviewHistory?.at(-1)?.at);
      if (current?.status === 'cancelled' && current.submissionAttempted) return result('blocked', '核对已提交的原任务',
        '本站处理已停止，官方生成是否停止尚未确认；请核对原任务结果后再决定下一步。', {...extra, task: current});
      if (current?.status === 'cancelled') extra.cancelledTaskId = current.id;
      if (current?.canConfirm) return result('confirm', '确认本次制作', `${entity.name} · ${stageLabels[stage]}，核对账号、数量和费用后提交。`, {...extra, task: current});
      if (current && !['completed','cancelled'].includes(current.status)) return result('blocked', '这一步需要处理', current.error?.message || '任务未完成，请查看任务记录；系统不会自行重试收费生成。', {...extra, task: current});
      if (current?.status === 'completed' && !candidates.length) return result('blocked', '结果尚未接入审核', '任务已返回，但没有可审核素材，请先核对文件收取记录。', {...extra, task: current});
      const spec = {projectId: project.id, entityId: entity.id, recipe: recipes[stage],
        prompt: defaultPrompt(entity, stage, plan.stylePrompt || '根据剧本的时代、环境与氛围保持统一视觉设定，不增改角色身份。'),
        sourceRevisionIds: source ? [source.id] : [], settings: {count: stage === 'style' ? styleCount : 1},
        ...(repair ? {repairOfRevisionId: repair.id} : {})};
      return result('prepare', `${repair ? '返修' : '制作'} ${entity.name} · ${stageLabels[stage]}`,
        `制作要求、参考图和文件归属由系统填写，本次生成 ${stage === 'style' ? styleCount : 1} 张候选图。`, {...extra, spec});
    }
  }
  // A new review invalidates an old download even when the plan did not change.
  const revisionIds = assets.flatMap(a => a.revisions).filter(r => r.status === 'ready' && r.review === 'approved').map(r => r.id).sort();
  const bundle = bundles.find(b => b.planVersion === plan.version && JSON.stringify(b.revisionIds) === JSON.stringify(revisionIds));
  return result(bundle ? 'download' : 'archive', '所有资产已审核，准备交付',
    bundle ? '已整理成下载包，包含图片、原文依据和制作记录。' : '将已确认的当前版本整理为交付包。', {bundle, done, total: plan.entities.length * 3});
}

export async function prepareIdentity(spec, selectionRevision, workflowSnapshot = {}, cryptoAPI = globalThis.crypto) {
  const bytes = new TextEncoder().encode(JSON.stringify({spec, selectionRevision, workflowSnapshot}));
  const hash = await cryptoAPI.subtle.digest('SHA-256', bytes);
  return 'guide-' + [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
}
