export const stages = ['style', 'asset', 'refine'];
export const stageLabels = {reference:'参考图',style: 'MJ 风格', asset: 'Image2 资产', refine: 'Nano 精修', storyboard: '分镜图'};
export const recipes = {style: 'mj_style', asset: 'image25_asset', refine: 'nano_refine'};
export const recipeLabels={mj_style:'MJ 风格',image25_style:'Image2.5 风格',image2_asset:'Image2 资产',image25_asset:'Image2.5 资产',nano_refine:'Nano 精修',storyboard_image:'Image2 分镜图',image25_storyboard:'Image2.5 分镜图'};
export const revisionLabel=revision=>revision.modelLabel||recipeLabels[revision.recipe]||stageLabels[revision.stage]||'图片';
export const categories = {reference:'参考图',character: '角色', scene: '场景', prop: '道具', effect: '异象', shot: '分镜'};
export const states = {pending: '待人工审核', approved: '已保留', changes_requested: '待返修', superseded: '历史版本', stale: '依据已变更',
  draft: '待确认提交', preparing: '准备中', submitting: '正在提交', submitted: '已提交，等待生成', queued: '排队中', running: '生成中', downloading: '收取中',
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
