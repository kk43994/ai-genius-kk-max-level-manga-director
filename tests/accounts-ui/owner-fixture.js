import { mount } from '../../frontend/accounts/index.js';
const clone = value => structuredClone(value);
export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const error = code => Object.assign(new Error(code), { code });
const expiry = () => new Date(Date.now() + 600000).toISOString();

export function makeOwnerFake(tenant = `owner_fixture_${Date.now()}`) {
  const source = { id: tenant, label: '当前临时工作区', ownerBound: false, owner: null, boundAt: null,
    content: { revision: 7, hasContent: true, records: 2, blobs: 0, providerAccounts: 1 } };
  const model = {
    source, counter: 0, calls: [], attempts: new Map(), intents: new Map(), intercept: null,
    dirty: false, saved: [], expiredSession: false, hooksLog: [], syncFailure: false,
    candidates: [
      { ...clone(source), id: 'workspace_old_a', label: '原来的角色资产工作区', ownerBound: true, owner: { provider: 'libtv', issuer: 'https://mcp.liblib.tv/', subject: 'synthetic_primary' } },
      { ...clone(source), id: 'workspace_old_b', label: '品牌项目工作区', ownerBound: true, owner: { provider: 'libtv', issuer: 'https://mcp.liblib.tv/', subject: 'synthetic_primary' } },
    ],
    session: { tenant: { id: tenant }, session: { id: `ss_${tenant}_0` }, csrfToken: `csrf_${tenant}_0`, workspace: clone(source),
      features: { providerAuthorization: true, imageGeneration: false, videoGeneration: false },
      selection: { providerAccountId: null, spaceId: null, revision: 0 } },
    account: { id: 'pa_secondary', provider: 'libtv', label: '附加生成账号（不是主账号）', version: 1,
      identity: { verified: true }, authorization: { state: 'connected' }, capabilities: { authorize: true, spaces: true, quota: false } },
  };
  const api = { csrf: model.session.csrfToken, setCsrfToken(value) { this.csrf = value; }, async request(path, options = {}) {
    model.calls.push({ path, ...clone(options), sessionId: model.session.session.id, csrf: api.csrf });
    if (model.intercept) { const value = model.intercept(path, options); if (value !== undefined) return clone(await value); }
    await delay(10);
    if (model.expiredSession) throw error('SESSION_REQUIRED');
    if (path === '/session') return clone(model.session);
    if (options.method && api.csrf !== model.session.csrfToken) throw error('CSRF_FAILED');
    if (path === '/workspace') return clone(model.session.workspace);
    if (path === '/provider-accounts') return { items: [clone(model.account)], nextCursor: null };
    if (path.endsWith('/spaces')) return { items: [{ id: 'space_secondary', name: '附加账号个人空间', kind: 'personal', access: 'available' }], nextCursor: null };
    if (path === '/provider-accounts/authorize') {
      const body = options.body;
      if (!['bind_owner', 'recover_workspace'].includes(body.purpose)) throw error('VALIDATION_FAILED');
      const n = ++model.counter, id = `wi_${n}`, attemptId = `oa_${n}`;
      const intent = { id, purpose: body.purpose, status: 'pending', version: 1, expiresAt: expiry(), error: null };
      model.intents.set(id, intent); model.attempts.set(attemptId, { status: 'pending', providerAccountId: null, error: null, workspaceIntentId: id });
      model.latestIntent = id; model.latestAttempt = attemptId; model.startBody = clone(body);
      return { attemptId, authorizationUrl: `https://mcp.liblib.tv/authorize?scope=${encodeURIComponent(model.authorizationScope || 'libtv:account:read')}&state=synthetic-never-open`, expiresAt: expiry(),
        intent: body.purpose === 'bind_owner' ? 'bind_owner' : 'recover', workspaceIntent: { intentId: id, purpose: body.purpose, expiresAt: expiry() } };
    }
    if (path.startsWith('/authorization-attempts/')) {
      const value = model.attempts.get(path.split('/')[2]); if (!value) throw error('NOT_FOUND');
      if (path.endsWith('/cancel') && value.status === 'pending') {
        value.status = 'failed'; value.error = { code: 'AUTHORIZATION_CANCELLED' };
        model.intents.get(value.workspaceIntentId).status = 'cancelled';
      }
      return clone(value);
    }
    if (path.startsWith('/workspace-intents/')) {
      const value = model.intents.get(path.split('/')[2]); if (!value) throw error('NOT_FOUND');
      if (path.endsWith('/cancel')) { value.status = 'cancelled'; value.version++; return clone(value); }
      if (path.endsWith('/confirm')) {
        const body = options.body;
        if (value.status !== 'awaiting_confirmation') throw error('WORKSPACE_CONFIRMATION_UNAVAILABLE');
        if (body.expectedVersion !== value.version) throw error('VERSION_CONFLICT');
        if (body.expectedContentRevision !== model.source.content.revision) throw error('WORKSPACE_CONTENT_CHANGED');
        if (model.startBody.hasUnsavedChanges === true && body.draftDisposition !== 'saved') throw error('DRAFT_SAVE_REQUIRED');
        if (body.draftDisposition === 'saved' && !body.savedDrafts.every(r => model.saved.some(s => s.id === r.id && s.version === r.version && s.collection === r.collection))) throw error('DRAFT_SAVE_REQUIRED');
        const target = value.purpose === 'bind_owner' ? model.source : model.candidates.find(c => c.id === body.workspaceId);
        if (!target) throw error('WORKSPACE_CHOICE_INVALID');
        if (value.purpose === 'recover_workspace' && body.action !== 'recover_preserve_current') throw error('SOURCE_WORKSPACE_REQUIRES_PRESERVATION');
        if (value.purpose === 'bind_owner' && (body.action !== 'bind_current' || 'workspaceId' in body)) throw error('VALIDATION_FAILED');
        model.source.ownerBound = true; model.source.owner = { provider: 'libtv', issuer: 'https://mcp.liblib.tv/', subject: 'synthetic_primary' };
        model.source.label = model.startBody.workspaceLabel; model.source.boundAt = new Date().toISOString();
        target.ownerBound = true;
        value.status = value.purpose === 'bind_owner' ? 'bound' : 'recovered'; value.version++;
        value.workspaceId = target.id; value.sourceWorkspacePreserved = true;
        model.session = { ...model.session, tenant: { id: target.id }, session: { id: `ss_rotated_${++model.counter}` },
          csrfToken: `csrf_rotated_${model.counter}`, workspace: clone(target), selection: { providerAccountId: null, spaceId: null, revision: 0 } };
        return clone(value);
      }
      if (value.status === 'awaiting_confirmation') value.sourceWorkspace = clone(model.source);
      return clone(value);
    }
    throw error('NOT_IMPLEMENTED');
  } };
  const hooks = {
    enabled: true,
    inspectDrafts: async () => ({ hasUnsavedChanges: model.dirty, items: model.dirty ? [{ label: '当前剧本输入', content: 'NEVER_RENDER_OR_STORE_CONTENT' }] : [] }),
    saveDrafts: async input => { model.hooksLog.push({ type: 'save', ...input }); await delay(10); model.dirty = false;
      const ref = { collection: 'drafts', id: 'synthetic_saved_script', version: model.saved.length + 1 };
      model.saved = [ref]; model.source.content.revision++; return { savedDrafts: clone(model.saved) }; },
    beforeSessionRotation: async input => { model.hooksLog.push({ type: 'quiesce', ...input }); return () => model.hooksLog.push({ type: 'resume' }); },
    onSessionRotated: async input => { if (model.syncFailure) throw error('SYNTHETIC_SYNC_FAILURE'); model.hooksLog.push({ type: 'rotated', ...clone(input) }); },
    bootstrapSession: async input => { model.hooksLog.push({ type: 'bootstrap', ...input }); model.expiredSession = false;
      model.source = { ...clone(source), id: `${tenant}_fresh`, label: '新的临时工作区', content: { revision: 0, hasContent: false } };
      model.session = { ...model.session, tenant: { id: model.source.id }, session: { id: `ss_fresh_${++model.counter}` }, csrfToken: 'csrf_fresh', workspace: clone(model.source) }; return clone(model.session); },
  };
  function verify(status = 'awaiting_confirmation') {
    const intent = model.intents.get(model.latestIntent); if (!intent) return;
    model.attempts.get(model.latestAttempt).status = 'completed';
    Object.assign(intent, { status, version: 2, sourceWorkspace: clone(model.source), proofExpiresAt: expiry(),
      candidates: clone(model.candidates), reasons: ['current_workspace_has_content', 'unsaved_or_unknown_browser_drafts'] });
    if (status === 'blocked') intent.error = { code: 'WORKSPACE_OWNER_MISMATCH' };
    if (status === 'not_found') intent.error = { code: 'OWNER_WORKSPACE_NOT_FOUND' };
  }
  return { model, api, hooks, verify };
}

window.open = () => null;
document.addEventListener('click', event => { if (event.target.closest('[data-owner="official"], [data-view="official-link"]')) event.preventDefault(); }, true);
let instance, fake;
function reset() {
  instance?.unmount();
  Object.keys(localStorage).filter(key => key.includes('owner_manual')).forEach(key => localStorage.removeItem(key));
  fake = makeOwnerFake('owner_manual'); document.querySelector('#owner-draft').value = '';
  instance = mount({ root: document.querySelector('#account-root'), api: fake.api, session: clone(fake.model.session), events: new EventTarget(),
    workspaceRecovery: fake.hooks, pollInterval: 100, publicBasePath: new URLSearchParams(location.search).get('base') || '/' });
}
document.querySelector('#owner-draft').addEventListener('input', () => { if (fake) fake.model.dirty = Boolean(document.querySelector('#owner-draft').value); });
document.querySelector('#owner-tools').addEventListener('click', event => {
  const action = event.target.dataset.scenario;
  if (action === 'reset') reset();
  if (action === 'verified') fake.verify();
  if (action === 'notfound') fake.verify('not_found');
  if (action === 'wrong') fake.verify('blocked');
  if (action === 'expired') fake.model.expiredSession = true;
});
if (new URLSearchParams(location.search).has('suite')) {
  document.querySelector('#owner-tools').hidden = true;
  const { runOwnerSuite } = await import('./owner-browser-suite.js');
  await runOwnerSuite({ mount, makeOwnerFake, delay });
} else reset();
