// Display only observed stages. Elapsed time is never converted to a fake percent.
export function operationLabel(path, method = 'GET') {
  if (/\/workflow\/start|\/analyze$/.test(path)) return '正在解析剧本并整理资产清单';
  if (/\/scripts$/.test(path) && method === 'POST') return '正在导入剧本';
  if (/\/tasks\/prepare$/.test(path)) return '正在核对账号、空间与制作参数';
  if (/\/submit$/.test(path)) return '正在提交制作请求，等待官方回执';
  if (/\/recover$/.test(path)) return '正在查询原任务并收取已生成素材';
  if (/\/reviews$/.test(path)) return '正在保存审核结果';
  if (/\/bundles$/.test(path) && method === 'POST') return '正在整理图片与交付包';
  if (/\/plan$/.test(path) && method === 'PUT') return '正在保存资产清单';
  if (/\/cancel$/.test(path)) return '正在取消未提交的准备记录';
  if (/\/confirm$/.test(path)) return '正在核对原任务与费用';
  return method === 'GET' ? '正在读取已保存的状态' : '正在保存到本地工作台';
}

export function elapsedLabel(start, now = Date.now()) {
  const seconds = Math.max(0, Math.floor((now - start) / 1000));
  return seconds < 60 ? `已用时 ${seconds} 秒` : `已用时 ${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}

export function taskProgress(task) {
  return ({preparing:'核对制作参数',draft:'等待确认制作',submitting:'等待官方回执',
    submitted:'已提交，等待生成',running:'LibTV 正在生成',downloading:'正在下载并校验素材',
    completed:'素材已收取',needs_attention:'需要处理',blocked_authorization:'原账号需要恢复授权',
    failed:'制作未完成',cancelled:'已取消'})[task.status] || '正在核对任务状态';
}

export function reviewProgress(entities, assets, selection, belongs) {
  const total = entities.length * 3;
  const done = entities.reduce((sum,e) => sum + ['style','asset','refine'].filter(stage =>
    assets.some(a => a.active && a.entityId === e.id && a.revisions.some(r =>
      r.stage === stage && r.status === 'ready' && r.review === 'approved' && belongs(r,selection)))).length,0);
  return {done,total};
}
