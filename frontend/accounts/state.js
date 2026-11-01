/** Public response presentation only. No provider credentials belong in this module. */
export const AUTHORIZATION_ENDPOINT = 'https://mcp.liblib.tv/authorize';

export const accountLabels = Object.freeze({
  unconfigured: '尚未开放授权', authorizing: '授权进行中', connected: '已授权',
  expired: '授权已过期', revoked: '授权已失效', error: '授权异常', removed: '已移除',
});

export function accountState(account, now = Date.now()) {
  if (account?.removedAt) return 'removed';
  const state = account?.authorization?.state;
  if (!Object.hasOwn(accountLabels, state)) return 'error';
  if (state === 'connected') {
    if (account.identity?.verified !== true) return 'error';
    const expiry = Date.parse(account.authorization.expiresAt);
    if (Number.isFinite(expiry) && expiry <= now) return 'expired';
  }
  return state;
}

export function accountName(account) {
  return account?.label || account?.identity?.displayName || 'LibTV 账号';
}

export function validSelection(value) {
  return value && Number.isSafeInteger(value.revision) && value.revision >= 0
    && (value.providerAccountId === null || typeof value.providerAccountId === 'string')
    && (value.spaceId === null || typeof value.spaceId === 'string')
    && (value.providerAccountId !== null || value.spaceId === null);
}

export function sameSelection(a, b) {
  return a?.providerAccountId === b?.providerAccountId && a?.spaceId === b?.spaceId;
}

export function selectable(account, space) {
  return accountState(account) === 'connected' && account.capabilities?.spaces !== false
    && space?.access === 'available' && ['personal', 'team'].includes(space.kind);
}

export function officialAuthorizationUrl(raw) {
  let url;
  try { url = new URL(raw); } catch { throw new Error('INVALID_AUTHORIZATION_URL'); }
  // This endpoint was read from official OAuth metadata. No wildcard domains or redirects.
  if (url.origin + url.pathname !== AUTHORIZATION_ENDPOINT || url.username || url.password
      || url.hash || url.protocol !== 'https:') throw new Error('INVALID_AUTHORIZATION_URL');
  return url.href;
}

export function publicReturnPath(base = '/') {
  if (typeof base !== 'string' || !/^\/(?!\/)[A-Za-z0-9/_-]*$/.test(base)
      || base.includes('//')) throw new TypeError('Invalid publicBasePath');
  return base.endsWith('/') ? base : `${base}/`;
}

export function attemptState(attempt, now = Date.now()) {
  if (!attempt) return null;
  if (attempt.status === 'failed' && ['ACCESS_DENIED', 'access_denied', 'AUTHORIZATION_CANCELLED',
    'OAUTH_ACCESS_DENIED', 'AUTHORIZATION_DENIED'].includes(attempt.error?.code)) return 'cancelled';
  if (['completed', 'failed', 'expired', 'cancelled'].includes(attempt.status)) return attempt.status;
  const expiry = Date.parse(attempt.expiresAt);
  if (Number.isFinite(expiry) && expiry <= now) return 'expired';
  return attempt.paused ? 'paused' : 'pending';
}

export function activeAttempt(attempt, now = Date.now()) {
  return ['pending', 'paused'].includes(attemptState(attempt, now));
}

export function publicAttemptError(error) {
  if (!error) return null;
  const codes = ['ACCESS_DENIED', 'access_denied', 'AUTHORIZATION_CANCELLED', 'OAUTH_ACCESS_DENIED',
    'AUTHORIZATION_DENIED', 'IDENTITY_MISMATCH', 'AUTHORIZATION_SUBJECT_MISMATCH',
    'PROVIDER_UNAVAILABLE', 'PROVIDER_ACCOUNT_READ_UNAVAILABLE', 'PROVIDER_CAPABILITY_UNAVAILABLE', 'AUTHORIZATION_EXPIRED'];
  return { code: codes.includes(error.code) ? error.code : 'AUTHORIZATION_FAILED' };
}

export function timeLabel(value) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return '未提供时间';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit',
    minute: '2-digit', hour12: false }).format(date);
}

export function quotaPresentation(quota, now = Date.now()) {
  const number = typeof quota?.remaining === 'number' && Number.isFinite(quota.remaining)
    && quota.remaining >= 0;
  const buckets = (Array.isArray(quota?.buckets) ? quota.buckets : []).filter(b =>
    typeof b.remaining === 'number' && Number.isFinite(b.remaining) && b.remaining >= 0);
  const known = ['known', 'stale'].includes(quota?.state) && (number || buckets.length > 0);
  const expiry = Date.parse(quota?.expiresAt);
  const stale = quota?.state === 'stale' || (Number.isFinite(expiry) && expiry <= now);
  const unit = quota?.unit === 'credits' ? '积分' : (quota?.unit || '额度');
  if (known) return {
    value: number ? `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(quota.remaining)} ${unit}` : '分项余额',
    label: stale ? '上次已知余额' : '官方返回余额',
    note: `${stale ? '数据已过期；' : ''}余额更新时间：${timeLabel(quota.observedAt)}。实际可用额度以官方结算为准。`,
    buckets: buckets.map(b => ({name:b.name || '额度', value:`${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(b.remaining)} ${b.unit === 'credits' ? '积分' : b.unit || '额度'}`})),
    state: stale ? 'stale' : 'known',
  };
  return { value: '余额未知', label: '所选空间余额', state: quota?.state === 'unavailable' ? 'unavailable' : 'unknown',
    buckets: [], note: quota?.state === 'unavailable' ? '暂时无法查询余额，请稍后重试。'
      : quota?.reason === 'provider_capability_unavailable' ? '当前 LibTV 授权接口未提供余额数值，请前往 LibTV 查看。'
      : quota ? '官方尚未返回可用余额，套餐信息不能用于推算积分。' : '点击查询余额，核对所选账号与空间的可用额度。' };
}

export function retainQuotaOnFailure(previous, next) {
  // Keep a labelled historical value only for this exact account and space.
  // Authorization, identity and malformed-response failures must clear it.
  return next?.state === 'unavailable' && previous?.providerAccountId && previous?.spaceId
    && sameSelection(previous, next) && ['known', 'stale'].includes(quotaPresentation(previous).state)
    ? { ...previous, state:'stale', checkedAt:next.checkedAt, reason:next.reason } : next;
}

const errors = {
  NOT_IMPLEMENTED: '此功能尚未接入，请稍后再试。',
  PROVIDER_UNAVAILABLE: 'LibTV 暂时无法连接，请稍后重试。',
  PROVIDER_ACCOUNT_READ_UNAVAILABLE: 'LibTV 暂时无法读取原账号资料。已保存的选择和任务仍在，请稍后刷新状态。',
  PROVIDER_CAPABILITY_UNAVAILABLE: 'LibTV 当前尚未提供这项能力。',
  PROVIDER_AUTHORIZATION_REQUIRED: '此账号授权需要更新，请重新授权后查询余额。',
  SPACE_UNAVAILABLE: '所选空间的访问权限需要重新核对，请刷新账号状态。',
  PROVIDER_AUTHORIZATION_UNAVAILABLE: 'LibTV 网页授权尚未开放，请稍后再试。',
  AUTHORIZATION_UNCONFIGURED: 'LibTV 网页授权尚未开放，请稍后再试。',
  AUTHORIZATION_IN_PROGRESS: '已有授权正在进行。请完成或查询这次授权后再添加账号。',
  SESSION_REQUIRED: '本站会话已过期，请刷新页面后重试。',
  CSRF_FAILED: '页面会话需要更新，请刷新状态后重试。',
  VERSION_CONFLICT: '账号状态已发生变化，已重新查询，请核对后再操作。',
  SELECTION_CHANGED: '当前账号或空间已在别处更改。已更新当前选择，请核对后再应用。',
  OWNERSHIP_MISMATCH: '所选空间不属于这个账号，请重新选择。',
  IDENTITY_MISMATCH: '授权身份与原账号不一致。请使用原账号重新授权，或另行添加账号。',
  AUTHORIZATION_SUBJECT_MISMATCH: '授权身份与原账号不一致。请使用原账号重新授权，或另行添加账号。',
  NOT_FOUND: '此账号或授权记录已不可用，请刷新状态。',
  INVALID_AUTHORIZATION_URL: '授权地址未通过官方地址校验，未打开登录页面。',
  INVALID_RESPONSE: '服务返回的状态不完整，请刷新状态后重试。',
};

export function errorText(error) {
  // Do not echo arbitrary backend/transport text: it might contain an upstream URL or secret.
  return errors[error?.code || error?.message] || '暂时无法完成操作。请检查网络后刷新状态；未自动重试。';
}
