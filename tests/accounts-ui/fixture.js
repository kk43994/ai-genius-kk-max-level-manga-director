import { mount } from '../../frontend/accounts/index.js';

const clone = value => structuredClone(value);
export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
export const makeAccount = (id, label) => ({ id, provider: 'libtv', label, version: 1,
  identity: { displayName: label, verified: true }, authorization: { state: 'connected' },
  capabilities: { authorize: true, spaces: true, quota: true } });

export function makeFake(mode = 'connected', tenant = 'synthetic-ui') {
  const model = {
    session: { tenant: { id: tenant }, session: { id: `site-${tenant}` },
      features: { providerAuthorization: mode !== 'unconfigured', imageGeneration: false, videoGeneration: false },
      selection: { providerAccountId: mode === 'connected' ? 'pa_a' : null, spaceId: mode === 'connected' ? 'a_personal' : null, revision: 2 } },
    accounts: mode === 'connected' ? [makeAccount('pa_a', '林的个人账号'), makeAccount('pa_b', '工作室账号')] : [],
    spaces: { pa_a: [{ id: 'a_personal', kind: 'personal', name: '我的个人空间', access: 'available' }, { id: 'a_team', kind: 'team', name: '山海工作室', access: 'available' }],
      pa_b: [{ id: 'b_personal', kind: 'personal', name: '工作室个人空间', access: 'available' }, { id: 'b_team', kind: 'team', name: '品牌项目组', access: 'available' }, { id: 'b_revoked', kind: 'team', name: '已退出项目组', access: 'revoked' }] },
    attempt: { status: 'pending', providerAccountId: null, error: null }, attemptSequence: 0, calls: [], intercept: null,
  };
  const api = { async request(path, options = {}) {
    model.calls.push({ path, ...clone(options) });
    if (model.intercept) { const override = model.intercept(path, options); if (override !== undefined) return clone(await override); }
    await delay(15);
    if (path === '/session') return clone(model.session);
    if (path === '/provider-accounts') return { items: clone(model.accounts), nextCursor: null };
    if (path === '/selection') {
      if (options.body.expectedRevision !== model.session.selection.revision) throw Object.assign(new Error('conflict'), { code: 'SELECTION_CHANGED' });
      model.session.selection = { providerAccountId: options.body.providerAccountId, spaceId: options.body.spaceId, revision: model.session.selection.revision + 1 };
      return clone(model.session.selection);
    }
    if (path.endsWith('/authorize') || path.endsWith('/reauthorize')) {
      model.attempt = { status: 'pending', providerAccountId: null, error: null };
      return { attemptId: `attempt_synthetic_${++model.attemptSequence}`, authorizationUrl: 'https://mcp.liblib.tv/authorize?state=synthetic-never-open', expiresAt: new Date(Date.now() + 600000).toISOString() };
    }
    if (path.startsWith('/authorization-attempts/')) return clone(model.attempt);
    const accountId = path.split('/')[2];
    if (path.endsWith('/spaces')) return { items: clone(model.spaces[accountId] || []), nextCursor: null };
    if (path.endsWith('/quota')) {
      const spaceId = path.split('/')[4];
      return { providerAccountId: accountId, spaceId, state: spaceId.endsWith('team') ? 'known' : 'unknown', remaining: spaceId.endsWith('team') ? 0 : null, unit: 'credits', planName: '合成演示套餐', observedAt: new Date().toISOString() };
    }
    if (options.method === 'DELETE') {
      model.accounts = model.accounts.filter(a => a.id !== accountId);
      if (model.session.selection.providerAccountId === accountId) model.session.selection = { providerAccountId: null, spaceId: null, revision: model.session.selection.revision + 1 };
      return { removed: true, remoteRevocation: 'unsupported', affectedTaskIds: ['synthetic-task'] };
    }
    throw Object.assign(new Error('unimplemented fixture'), { code: 'NOT_IMPLEMENTED' });
  } };
  return { model, api };
}

let module, fake;
const events = new EventTarget();
// Synthetic authorization must never navigate to the real provider, even via the visible fallback link.
window.open = () => null;
document.addEventListener('click', event => {
  if (event.target.closest('[data-view="official-link"]')) {
    event.preventDefault(); document.querySelector('#test-results').hidden = false;
    document.querySelector('#test-results').textContent = '合成测试：已拦截官方链接；没有发起真实授权。';
  }
}, true);

function reset(mode) {
  module?.unmount();
  localStorage.removeItem('asset-lab:accounts:v1:synthetic-ui');
  fake = makeFake(mode);
  module = mount({ root: document.querySelector('#account-root'), api: fake.api, events, session: fake.model.session, pollInterval: 200, publicBasePath: new URLSearchParams(location.search).get('base') || '/' });
}
document.querySelector('#fixture-tools').addEventListener('click', async event => {
  const action = event.target.dataset.fixture;
  if (['empty', 'connected', 'unconfigured'].includes(action)) return reset(action);
  if (action === 'complete') { fake.model.accounts = [makeAccount('pa_a', '林的个人账号')]; fake.model.attempt = { status: 'completed', providerAccountId: 'pa_a', error: null }; }
  if (action === 'cancel') fake.model.attempt = { status: 'failed', providerAccountId: null, error: { code: 'ACCESS_DENIED' } };
  if (action === 'expire') fake.model.attempt = { status: 'expired', providerAccountId: null, error: null };
  if (action === 'fail') fake.model.attempt = { status: 'failed', providerAccountId: null, error: { code: 'IDENTITY_MISMATCH' } };
});

if (new URLSearchParams(location.search).has('suite')) {
  document.querySelector('#fixture-tools').hidden = true;
  const { runSuite } = await import('./browser-suite.js');
  await runSuite({ mount, makeFake, makeAccount, delay });
} else reset('connected');
