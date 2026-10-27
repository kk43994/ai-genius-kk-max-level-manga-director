export const stages = ['style', 'asset', 'refine'];
export const stageLabels = {style: 'MJ 风格', asset: 'Image2 资产', refine: 'Nano 精修'};
export const recipes = {style: 'mj_style', asset: 'image2_asset', refine: 'nano_refine'};
export const categories = {character: '角色', scene: '场景', prop: '道具', effect: '异象'};
export const states = {pending: '待人工审核', approved: '已保留', changes_requested: '待返修', superseded: '历史版本', stale: '依据已变更',
  draft: '待确认提交', preparing: '准备中', submitting: '正在提交', queued: '排队中', running: '生成中', downloading: '收取中',
  completed: '已返回 · 需审核', failed: '失败', needs_attention: '需要核对原任务', blocked_authorization: '等待重新授权', cancelled: '已停止本地处理'};
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));

export function localBase(value, fallback) {
  const base = value ?? fallback;
  if (typeof base !== 'string' || !base.startsWith('/') || base.startsWith('//') || /[?#\\\s]/.test(base)
    || base.split('/').some(part => part === '.' || part === '..') || /%2e|%2f|%5c/i.test(base)) throw new Error('网站挂载路径无效。');
  return base.replace(/\/+$/, '');
}
export function assetURL(apiBase, assetId, revisionId, thumbnail = false) {
  return `${localBase(apiBase, '/api/v1')}/assets/${encodeURIComponent(assetId)}/${thumbnail ? 'thumbnail' : 'content'}?revisionId=${encodeURIComponent(revisionId)}`;
}
export function belongsToSelection(revision, selection) {
  return Boolean(selection?.providerAccountId && selection?.spaceId && revision.ownership?.providerAccountId === selection.providerAccountId
    && revision.ownership?.spaceId === selection.spaceId);
}
export function approvedSources(asset, stage, selection) {
  const sourceStage = stage === 'asset' ? 'style' : stage === 'refine' ? 'asset' : null;
  return (asset?.revisions || []).filter(r => r.stage === sourceStage && r.status === 'ready' && r.review === 'approved' && belongsToSelection(r, selection));
}
export function resolveRefineSource(revision, revisions) {
  if (revision.stage === 'asset') return revision;
  if (revision.stage !== 'refine') return null;
  const original = revisions.find(r => r.id === revision.refineSourceRevisionId);
  return original?.stage === 'asset' && original.projectId === revision.projectId && original.entityId === revision.entityId
    && original.ownership?.providerAccountId === revision.ownership?.providerAccountId && original.ownership?.spaceId === revision.ownership?.spaceId ? original : null;
}
export function defaultPrompt(entity, stage, style = '') {
  if (stage === 'refine') return '从原始 Image2 资产保真清理。保留脸、服装纹样、道具结构、画幅与视图数量。宁可变化很小，也不丢失细节。';
  const detail = `${entity.name}：${entity.description || '具体设定待补充'}`;
  if (stage === 'style') return `${detail}\n${style || '请填写希望采用的视觉风格。'}\n生成完整的风格候选图。`;
  const requirement = entity.category === 'scene' ? '固定建筑结构与地标，交代入口、出口和人物活动空间。一个完整机位画面，无拼版。'
    : entity.category === 'prop' ? '正面、侧面和背面三视图，等比例、结构统一、纯色背景。'
      : '同一角色的正面、侧面、背面与面部特写。身份、服装、发型与比例一致，四栏清楚排列。';
  return `${detail}\n依照已审核的 MJ 风格图制作模型资产。${requirement}无多余文字。`;
}

export class DraftStore {
  constructor(storage, tenantId, apiBase) {
    if (!tenantId) throw new Error('缺少本站会话，草稿暂不能安全保存。');
    this.storage = storage;
    this.key = `asset-lab:workflow:v1:${encodeURIComponent(localBase(apiBase, '/api/v1'))}:${encodeURIComponent(tenantId)}`;
    this.data = {};
    try { const raw = JSON.parse(storage?.getItem(this.key) || '{}'); if (raw && typeof raw === 'object' && !Array.isArray(raw)) this.data = raw; }
    catch { /* A damaged cache never reads another tenant's legacy draft key. */ }
  }
  get(key) { return this.data[key]; }
  set(key, value) { this.data[key] = value; return this.flush(); }
  delete(key) { delete this.data[key]; return this.flush(); }
  flush() {
    if (!this.storage) throw new Error('浏览器草稿存储不可用，请先保存到项目再刷新。');
    this.storage.setItem(this.key, JSON.stringify(this.data));
    return {saved: true};
  }
}
