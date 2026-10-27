import { officialAuthorizationUrl, publicReturnPath } from './state.js';

export const ownerPurposes = ['bind_owner', 'recover_workspace'];
export const ownerStatuses = ['pending', 'awaiting_confirmation', 'bound', 'recovered', 'blocked', 'not_found', 'cancelled', 'expired', 'failed'];
export const ownerError = code => Object.assign(new Error(code), { code });

export function ownerAuthorizationUrl(raw) {
  const url = new URL(officialAuthorizationUrl(raw));
  const scope = url.searchParams.getAll('scope');
  if (scope.length !== 1 || scope[0].trim() !== 'libtv:account:read') throw ownerError('OWNER_READ_ONLY_REQUIRED');
  return url.href;
}

export function draftSummary(value) {
  const known = value?.hasUnsavedChanges === true || value?.hasUnsavedChanges === false;
  return { hasUnsavedChanges: known ? value.hasUnsavedChanges : null,
    items: Array.isArray(value?.items) ? value.items.slice(0, 100).map(item => ({ label: String(item?.label || '未保存的编辑内容').slice(0, 160) })) : [] };
}

export function ownerStartBody({ purpose, label, drafts, publicBasePath }) {
  if (!ownerPurposes.includes(purpose)) throw ownerError('INVALID_OWNER_RESPONSE');
  const workspaceLabel = String(label || '').trim();
  if (!workspaceLabel || workspaceLabel.length > 120 || /[\x00-\x1f]/.test(workspaceLabel)) throw ownerError('WORKSPACE_LABEL_REQUIRED');
  return { purpose, returnPath: publicReturnPath(publicBasePath), workspaceLabel,
    // Even a currently clean editor can change while the official page is open.
    // Unknown forces the documented confirmation boundary instead of an automatic switch.
    hasUnsavedChanges: drafts?.hasUnsavedChanges === true ? true : null };
}

export function savedDraftReferences(value) {
  if (!Array.isArray(value) || !value.length || value.length > 100) throw ownerError('DRAFT_SAVE_REQUIRED');
  const seen = new Set();
  return value.map(item => {
    if (typeof item?.collection !== 'string' || !item.collection || typeof item.id !== 'string' || !item.id
        || !Number.isSafeInteger(item.version) || item.version < 1) throw ownerError('DRAFT_SAVE_REQUIRED');
    const key = `${item.collection}:${item.id}`;
    if (seen.has(key)) throw ownerError('DRAFT_SAVE_REQUIRED');
    seen.add(key);
    return { collection: item.collection, id: item.id, version: item.version };
  });
}

export function ownerConfirmBody({ intent, workspaceId, drafts, savedDrafts, initiallyDirty, acknowledged }) {
  if (!acknowledged || intent?.status !== 'awaiting_confirmation' || !Number.isSafeInteger(intent.version)
      || !Number.isSafeInteger(intent.sourceWorkspace?.content?.revision)) throw ownerError('WORKSPACE_CONFIRMATION_UNAVAILABLE');
  const expiry = Date.parse(intent.proofExpiresAt || intent.expiresAt);
  if (!Number.isFinite(expiry) || expiry <= Date.now()) throw ownerError('WORKSPACE_AUTHORIZATION_EXPIRED');
  if (drafts?.hasUnsavedChanges !== false) throw ownerError('DRAFT_SAVE_REQUIRED');
  const references = savedDrafts?.length ? savedDraftReferences(savedDrafts) : [];
  if (initiallyDirty && !references.length) throw ownerError('DRAFT_SAVE_REQUIRED');
  const body = { action: 'bind_current', expectedVersion: intent.version,
    expectedContentRevision: intent.sourceWorkspace.content.revision,
    draftDisposition: references.length ? 'saved' : 'none', savedDrafts: references };
  if (intent.purpose === 'recover_workspace') {
    if (!intent.candidates?.some(c => c.id === workspaceId)) throw ownerError('WORKSPACE_CHOICE_INVALID');
    body.action = 'recover_preserve_current'; body.workspaceId = workspaceId;
  } else if (intent.purpose !== 'bind_owner') throw ownerError('INVALID_OWNER_RESPONSE');
  return body;
}

export function publicOwnerMarker(value) {
  if (!ownerPurposes.includes(value?.purpose) || typeof value.attemptId !== 'string' || typeof value.intentId !== 'string'
      || typeof value.sourceSessionId !== 'string' || typeof value.sourceWorkspaceId !== 'string'
      || !Number.isFinite(Date.parse(value.expiresAt))) return null;
  return { purpose: value.purpose, attemptId: value.attemptId, intentId: value.intentId,
    sourceSessionId: value.sourceSessionId, sourceWorkspaceId: value.sourceWorkspaceId,
    expiresAt: value.expiresAt, initiallyDirty: value.initiallyDirty === true,
    authorizationRejected: value.authorizationRejected === true,
    status: ownerStatuses.includes(value.status) ? value.status : 'pending' };
}

const messages = {
  OWNER_READ_ONLY_REQUIRED: '主账号授权链接或只读身份范围未通过校验，未打开官方页面。请取消后稍后重试。',
  WORKSPACE_LABEL_REQUIRED: '请填写 1–120 字的工作区名称。',
  INVALID_OWNER_RESPONSE: '工作区状态不完整，请重新检查状态。',
  WORKSPACE_RECOVERY_UNAVAILABLE: '工作区主账号授权尚未开放，暂时不能绑定或找回。',
  WORKSPACE_CONFIRMATION_UNAVAILABLE: '本次工作区授权还不能确认，请重新检查结果。',
  WORKSPACE_AUTHORIZATION_EXPIRED: '身份确认已过期，请重新发起官方授权。',
  WORKSPACE_PROOF_STALE: '身份确认已过期，请重新发起官方授权。',
  WORKSPACE_OWNER_MISMATCH: '这不是当前工作区的主账号，不能转移所有权或接管其他工作区。当前工作区已保留。',
  OWNER_WORKSPACE_NOT_FOUND: '此 LibTV 身份没有绑定过的工作区。附加的生成账号不能用于找回所有权。',
  WORKSPACE_CONTENT_CHANGED: '当前工作区内容刚刚发生变化。请重新核对内容后确认，尚未切换。',
  VERSION_CONFLICT: '确认状态已更新，请重新核对后确认，尚未自动重试。',
  WORKSPACE_CHOICE_INVALID: '请选择本次官方验证返回的工作区。',
  SOURCE_WORKSPACE_REQUIRES_PRESERVATION: '请确认保留当前工作区，再进入所选工作区。',
  DRAFT_SAVE_REQUIRED: '请先把当前未保存内容完整保存到当前工作区，再继续确认。',
  DRAFT_VERSION_CHANGED: '草稿版本已变化，请重新保存并核对。',
  DRAFT_INSPECTION_UNAVAILABLE: '暂时无法核实未保存内容。请保留当前工作，待状态检查可用后继续。',
  WORKSPACE_SESSION_SYNC_REQUIRED: '站点会话已变化。正在重新读取完整会话；完成前请勿继续账号操作。',
  WORKSPACE_SYNC_FAILED: '工作区会话已更新，但页面同步未完成。请点击“重新同步工作区”，不要继续使用旧页面状态。',
  WORKSPACE_AUTHORIZATION_BUSY: '已有工作区授权正在进行，请先完成或取消。',
  PROVIDER_IDENTITY_UNAVAILABLE: '官方身份尚未核验，暂时不能绑定或找回工作区。',
  PROVIDER_UNCONFIGURED: '官方网页授权尚未配置完成，暂时不能绑定或找回。',
  PROVIDER_CAPABILITY_UNAVAILABLE: '官方工作区找回能力尚未接入。',
  SESSION_REQUIRED: '本站会话已失效。需要站点建立新的临时会话后，使用绑定的主账号找回工作区。',
  NOT_FOUND: '此确认记录已不可用。请重新检查当前会话，不会自动进入其他工作区。',
};

export function ownerErrorText(error) {
  return messages[error?.code] || '这次操作未能确认完成。当前页面输入已保留，请检查状态后再操作。';
}
