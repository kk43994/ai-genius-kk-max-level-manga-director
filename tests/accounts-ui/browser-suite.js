/** Runs in a real browser against a synthetic API; it never calls any network API. */
export async function runSuite({ mount, makeFake, makeAccount, delay }) {
  const root = document.querySelector('#account-root'), output = document.querySelector('#test-results');
  output.hidden = false;
  let current, fixture, serial = 0;
  const results = [];
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const ref = key => root.querySelector(`[data-view="${key}"]`);
  const button = key => root.querySelector(`[data-action="${key}"]`);
  const change = (key, value) => { ref(key).value = value; ref(key).dispatchEvent(new Event('change', { bubbles: true })); };
  async function until(predicate, message = 'state did not settle') {
    for (let i = 0; i < 100; i++) { if (predicate()) return; await delay(20); }
    throw new Error(message);
  }
  async function setup(mode = 'connected', options = {}, customize = () => {}) {
    current?.unmount();
    fixture = makeFake(mode, `synthetic-suite-${Date.now()}-${++serial}`);
    customize(fixture);
    const events = new EventTarget();
    const eventLog = [];
    ['selection:changed', 'provider-accounts:changed', 'session:changed', 'tasks:changed'].forEach(name => events.addEventListener(name, event => eventLog.push({ name, detail: event.detail })));
    current = mount({ root, api: fixture.api, session: fixture.model.session, events, pollInterval: 100, ...options });
    await current.ready;
    return { ...fixture, events, eventLog };
  }
  async function test(name, run) {
    try { await run(); results.push({ name, passed: true }); }
    catch (err) { results.push({ name, passed: false, error: err.message }); }
    output.textContent = results.map(r => `${r.passed ? 'PASS' : 'FAIL'} ${r.name}${r.error ? `: ${r.error}` : ''}`).join('\n');
  }

  await test('恢复已授权列表；当前空间余额未知不冒充 0；不自动切换', async () => {
    const { model } = await setup();
    assert(ref('identity').value === 'pa_a' && ref('space').value === 'a_personal', 'selection not restored');
    assert(ref('quota-value').textContent === '余额未知', 'unknown balance misrepresented');
    assert(!model.calls.some(c => c.method === 'PUT'), 'mount changed selection');
    assert(ref('status').getAttribute('role') === 'status' && ref('error').getAttribute('role') === 'alert', 'missing accessible live feedback');
  });

  await test('余额能力未开放仍执行查询，显示原因、时间与官方入口', async () => {
    const {model}=await setup('connected',{},({model})=>{
      model.accounts.forEach(a=>a.capabilities.quota=false);
      model.intercept=path=>path.endsWith('/quota')?Promise.resolve({providerAccountId:'pa_a',spaceId:'a_personal',state:'unknown',reason:'provider_capability_unavailable',checkedAt:new Date().toISOString()}):undefined;
    });
    assert(model.calls.some(c=>c.path.endsWith('/quota')),'capability flag skipped query');
    assert(ref('quota-note').textContent.includes('未提供余额数值'),'missing capability explanation');
    assert(!ref('quota-time').hidden && !ref('quota-official').hidden,'missing timestamp or official link');
    const count=model.calls.filter(c=>c.path.endsWith('/quota')).length;
    button('quota').click(); await until(()=>!button('quota').disabled);
    assert(model.calls.filter(c=>c.path.endsWith('/quota')).length===count+1,'manual query did not run');
  });

  await test('账号与空间分开选择；真实 0 保留；双击仅提交一次；外围输入不变', async () => {
    const { model, eventLog } = await setup();
    document.querySelector('#outside-draft').value = '剧本中尚未保存的原始输入';
    change('identity', 'pa_b');
    assert(ref('space').value === '', 'old account space carried over');
    await until(() => !ref('space').disabled);
    change('space', 'b_team'); await until(() => ref('quota-value').textContent === '0 积分');
    button('apply').click(); button('apply').click();
    await until(() => eventLog.some(x => x.name === 'selection:changed'));
    const writes = model.calls.filter(c => c.path === '/selection');
    assert(writes.length === 1 && writes[0].body.expectedRevision === 2, 'duplicate or invalid CAS write');
    assert(writes[0].body.providerAccountId === 'pa_b' && writes[0].body.spaceId === 'b_team', 'wrong selection payload');
    assert(document.querySelector('#outside-draft').value === '剧本中尚未保存的原始输入', 'external draft lost');
    assert(!current.getDirtyState().dirty, 'committed draft remains dirty');
  });

  await test('先前账号的空间响应晚到时不覆盖当前账号', async () => {
    const { model } = await setup();
    let finish;
    model.intercept = path => path === '/provider-accounts/pa_b/spaces' ? new Promise(resolve => { finish = resolve; }) : undefined;
    change('identity', 'pa_b'); await until(() => finish);
    change('identity', 'pa_a'); await until(() => !ref('space').disabled);
    finish({ items: [{ id: 'wrong', name: '绝不能出现', kind: 'team', access: 'available' }], nextCursor: null });
    await delay(50);
    assert(!ref('space').textContent.includes('绝不能出现') && ref('identity').value === 'pa_a', 'stale space response won');
  });

  await test('前一空间的余额响应晚到时不覆盖新空间', async () => {
    const { model } = await setup(); let finish;
    model.intercept = path => path.includes('/a_team/quota') ? new Promise(resolve => { finish = resolve; }) : undefined;
    change('space', 'a_team'); await until(() => finish);
    change('space', 'a_personal'); await until(() => ref('quota-value').textContent === '余额未知');
    finish({ providerAccountId: 'pa_a', spaceId: 'a_team', state: 'known', remaining: 999, unit: 'credits' });
    await delay(40); assert(ref('quota-value').textContent === '余额未知', 'stale quota leaked across spaces');
  });

  await test('409 冲突重新读取状态并保留未提交选择；必须再次点击', async () => {
    const { model } = await setup();
    change('space', 'a_team');
    model.session.selection = { providerAccountId: 'pa_b', spaceId: 'b_team', revision: 9 };
    button('apply').click(); await until(() => !ref('error').hidden && !button('apply').disabled);
    assert(model.calls.filter(c => c.path === '/selection').length === 1, 'POST/PUT was auto-retried');
    assert(ref('space').value === 'a_team', 'unsaved selection lost on conflict');
    button('apply').click(); await until(() => !current.getDirtyState().dirty);
    assert(model.calls.filter(c => c.path === '/selection').at(-1).body.expectedRevision === 9, 'new revision not used after explicit retry');
  });

  await test('首次授权防重入；弹窗阻止后保留安全链接；恢复取消等待状态', async () => {
    const { model, api } = await setup('empty');
    button('add').click(); button('add').click();
    await until(() => !ref('attempt').hidden && !button('pause').disabled);
    assert(model.calls.filter(c => c.path.endsWith('/authorize')).length === 1, 'duplicate authorization');
    assert(ref('official-link').rel.includes('noopener') && ref('official-link').target === '_blank', 'unsafe official link');
    button('pause').click(); assert(ref('attempt-title').textContent.includes('尚未确认'), 'pause falsely claimed cancellation');
    const saved = localStorage.getItem(`asset-lab:accounts:v1:${model.session.tenant.id}`);
    assert(!/authorizationUrl|csrf|synthetic-never-open|access_token|refresh_token/.test(saved), 'secret/URL persisted');
    current.unmount(); current = mount({ root, api, session: model.session, pollInterval: 100 }); await current.ready;
    assert(ref('attempt-title').textContent.includes('取消等待') && button('add').disabled, 'paused pending attempt not restored');
    model.attempt = { status: 'failed', providerAccountId: null, error: { code: 'ACCESS_DENIED' } };
    button('check').click(); await until(() => ref('attempt-title').textContent.includes('官方页面取消'));
    assert(!button('add').disabled, 'terminal cancellation still blocks authorization');
  });

  await test('官方完成后重新核对账号，但不自动改绑新任务', async () => {
    const { model } = await setup('empty');
    button('add').click(); await until(() => !ref('attempt').hidden);
    model.accounts = [makeAccount('pa_a', '新授权账号')]; model.attempt = { status: 'completed', providerAccountId: 'pa_a', error: null };
    await until(() => ref('accounts').textContent.includes('新授权账号') && !ref('identity').disabled);
    assert(ref('attempt-title').textContent === '官方授权已完成', 'completion not rendered');
    assert(!model.calls.some(c => c.path === '/selection') && ref('identity').value === '', 'authorization auto-selected ownership');
  });

  await test('过期与失败有独立状态；失败原始文本不进入页面', async () => {
    const { model } = await setup('empty');
    button('add').click(); await until(() => !ref('attempt').hidden);
    model.attempt = { status: 'expired', error: null };
    await until(() => ref('attempt-title').textContent.includes('已过期'));
    button('add').click(); await until(() => ref('attempt-title').textContent.includes('等待 LibTV'));
    model.attempt = { status: 'failed', error: { code: 'IDENTITY_MISMATCH', message: 'secret_do_not_render' } };
    await until(() => ref('attempt-title').textContent.includes('未完成'));
    assert(root.textContent.includes('原账号不一致') && !root.textContent.includes('secret_do_not_render'), 'unsafe or vague identity mismatch');
  });

  await test('重新授权走原账号版本接口；官方 URL 校验拒绝恶意目的地', async () => {
    const { model } = await setup();
    model.intercept = path => path.endsWith('/reauthorize') ? Promise.resolve({ attemptId: 'unsafe_test', expiresAt: new Date(Date.now() + 60000).toISOString(), authorizationUrl: 'https://evil.example/?token=DO_NOT_RENDER' }) : undefined;
    root.querySelector('[data-action="reauthorize"][data-id="pa_a"]').click();
    await until(() => !ref('error').hidden);
    const call = model.calls.find(c => c.path.endsWith('/reauthorize'));
    assert(call.path === '/provider-accounts/pa_a/reauthorize' && call.body.expectedVersion === 1, 'reauthorize lost identity/version');
    assert(!ref('official-link').hasAttribute('href') && !root.textContent.includes('DO_NOT_RENDER'), 'unsafe URL leaked');
  });

  await test('移除有明确确认与焦点恢复；不宣称远端撤销已成功', async () => {
    const { model, eventLog } = await setup();
    const trigger = root.querySelector('[data-action="remove"][data-id="pa_a"]'); trigger.focus(); trigger.click();
    assert(ref('remove-dialog').open, 'confirmation not opened');
    button('keep-account').click();
    assert(!model.calls.some(c => c.method === 'DELETE') && document.activeElement === trigger, 'cancel removed account or focus lost');
    trigger.click(); button('confirm-remove').click(); button('confirm-remove').click();
    await until(() => eventLog.some(x => x.name === 'tasks:changed'));
    assert(model.calls.filter(c => c.method === 'DELETE').length === 1, 'duplicate removal');
    assert(ref('status').textContent.includes('官方侧撤销尚未确认') && ref('status').textContent.includes('历史项目'), 'removal overclaim');
  });

  await test('读列表失败后释放加载状态，允许用户手动重试', async () => {
    await setup('empty', {}, ({ model }) => { model.intercept = path => path === '/provider-accounts' ? Promise.reject(Object.assign(new Error('raw secret'), { code: 'PROVIDER_UNAVAILABLE' })) : undefined; });
    assert(!button('refresh').disabled && !ref('error').hidden, 'list failure left loading locked');
  });

  await test('切换租户时清除旧输入与未完成响应；旧响应不能回填', async () => {
    const { model, events } = await setup(); let finish;
    model.intercept = path => path === '/provider-accounts/pa_b/spaces' ? new Promise(resolve => { finish = resolve; }) : undefined;
    change('identity', 'pa_b'); await until(() => finish);
    model.session = { ...model.session, tenant: { id: 'synthetic-new-tenant' }, selection: { providerAccountId: null, spaceId: null, revision: 0 } };
    model.accounts = [];
    events.dispatchEvent(new CustomEvent('session:changed', { detail: { session: structuredClone(model.session) } }));
    await until(() => ref('count').textContent === '0 个账号');
    finish({ items: [{ id: 'old_space', kind: 'team', name: '其他租户的空间', access: 'available' }], nextCursor: null });
    await delay(40); assert(!root.textContent.includes('其他租户的空间') && ref('identity').value === '', 'cross-tenant state leaked');
  });

  await test('子路径回调通过显式 publicBasePath 注入，API 仍由公共客户端负责', async () => {
    const { model } = await setup('empty', { publicBasePath: '/asset-lab/' });
    button('add').click(); await until(() => !ref('attempt').hidden);
    const call = model.calls.find(c => c.path === '/provider-accounts/authorize');
    assert(call.body.returnPath === '/asset-lab/', 'subpath return path wrong');
    assert(model.calls.every(c => !c.path.startsWith('/api/')), 'module hardcoded API base');
  });

  await test('失效空间不可应用；错误归属余额不会显示；标签按文本转义', async () => {
    const { model } = await setup('connected', {}, ({ model }) => { model.accounts[0].label = '<img src=x onerror=alert(1)>'; });
    assert(!ref('accounts').querySelector('img') && ref('accounts').textContent.includes('<img'), 'account label injected markup');
    model.intercept = path => path.endsWith('/a_team/quota') ? Promise.resolve({ providerAccountId: 'pa_b', spaceId: 'b_team', state: 'known', remaining: 999999 }) : undefined;
    change('space', 'a_team'); await until(() => ref('quota-note').textContent.includes('不属于'));
    assert(!ref('quota-value').textContent.includes('999999'), 'wrong-owner quota displayed');
    change('identity', 'pa_b'); await until(() => !ref('space').disabled);
    assert(ref('space').querySelector('[value="b_revoked"]').disabled, 'revoked space is selectable');
  });

  await test('授权未开放不能发起授权；已失效账号不能切换', async () => {
    const { model } = await setup('unconfigured'); button('add').click();
    assert(button('add').disabled && !ref('notice').hidden && !model.calls.some(c => c.method === 'POST'), 'unconfigured feature is enabled');
    await setup('connected', {}, ({ model }) => { model.accounts[0].authorization = { state: 'expired' }; });
    assert(ref('identity').querySelector('[value="pa_a"]').disabled && button('apply').disabled, 'expired account can be applied');
  });

  await test('刷新恢复未应用的空间选择；旧 session 事件不能回退选择版本', async () => {
    const { api, model, events } = await setup();
    change('space', 'a_team'); current.unmount();
    current = mount({ root, api, session: model.session, events }); await current.ready;
    assert(ref('space').value === 'a_team' && current.getDirtyState().dirty, 'draft not restored');
    events.dispatchEvent(new CustomEvent('selection:changed', { detail: { selection: { providerAccountId: 'pa_b', spaceId: 'b_team', revision: 10 } } }));
    events.dispatchEvent(new CustomEvent('session:changed', { detail: { session: structuredClone(model.session) } }));
    await delay(100);
    model.session.selection = { providerAccountId: 'pa_b', spaceId: 'b_team', revision: 10 };
    button('apply').click(); await until(() => !current.getDirtyState().dirty);
    assert(model.calls.filter(c => c.path === '/selection').at(-1).body.expectedRevision === 10, 'stale session regressed CAS revision');
  });

  await test('链接本地过期后仍可核对此前已完成的官方结果', async () => {
    const { model, api } = await setup('empty');
    current.unmount();
    localStorage.setItem(`asset-lab:accounts:v1:${model.session.tenant.id}`, JSON.stringify({ attempt: {
      attemptId: 'expired_link', status: 'pending', expiresAt: new Date(Date.now() - 60000).toISOString(), paused: false,
      siteSessionId: model.session.session.id,
    } }));
    model.accounts = [makeAccount('pa_a', '临近到期前完成的账号')];
    model.attempt = { status: 'completed', providerAccountId: 'pa_a', error: null };
    current = mount({ root, api, session: model.session, pollInterval: 100 }); await current.ready;
    await until(() => ref('attempt-title').textContent === '官方授权已完成');
    assert(model.calls.some(c => c.path === '/authorization-attempts/expired_link'), 'expired link skipped authoritative check');
  });

  await test('同源多个实例的授权锁防重复；请求进行中阻止刷新升级', async () => {
    const { model, api } = await setup('empty');
    assert(navigator.locks, 'this browser has no Web Locks support');
    const secondRoot = document.createElement('div'); document.body.append(secondRoot);
    const second = mount({ root: secondRoot, api, session: structuredClone(model.session), pollInterval: 100 });
    try {
      await second.ready;
      let finish;
      model.intercept = path => path === '/provider-accounts/authorize' ? new Promise(resolve => { finish = resolve; }) : undefined;
      button('add').click(); await until(() => finish);
      assert(current.getDirtyState().reason.includes('尚未完成'), 'inflight operation absent from update guard');
      let refused = false;
      try { await current.flush(); } catch (err) { refused = err.code === 'ACCOUNT_OPERATION_IN_PROGRESS'; }
      assert(refused, 'update flush allowed in-flight authorization');
      secondRoot.querySelector('[data-action="add"]').click(); await delay(40);
      assert(model.calls.filter(c => c.path === '/provider-accounts/authorize').length === 1, 'two same-origin instances created two authorizations');
      finish({ attemptId: 'shared_lock_attempt', authorizationUrl: 'https://mcp.liblib.tv/authorize?state=synthetic', expiresAt: new Date(Date.now() + 60000).toISOString() });
      await until(() => !ref('attempt').hidden && !current.getDirtyState().dirty);
    } finally { second.unmount(); secondRoot.remove(); }
    assert(JSON.parse(localStorage.getItem(`asset-lab:accounts:v1:${model.session.tenant.id}`)).attempt?.attemptId === 'shared_lock_attempt', 'unmount of an older instance erased the active attempt');
  });

  current?.unmount();
  document.documentElement.dataset.testStatus = results.every(r => r.passed) ? 'passed' : 'failed';
  document.documentElement.dataset.testCount = String(results.length);
  document.title = `${results.filter(r => r.passed).length}/${results.length} · 账号模块浏览器验证`;
  output.textContent += `\n\n${results.filter(r => r.passed).length}/${results.length} passed. No real authorization or paid generation was performed.`;
  // Clean only this suite's synthetic keys; no account or customer keys are touched.
  Object.keys(localStorage).filter(key => key.startsWith('asset-lab:accounts:v1:synthetic-suite-') || key === 'asset-lab:accounts:v1:synthetic-new-tenant').forEach(key => localStorage.removeItem(key));
}
