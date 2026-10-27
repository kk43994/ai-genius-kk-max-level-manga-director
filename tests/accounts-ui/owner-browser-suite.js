export async function runOwnerSuite({ mount, makeOwnerFake, delay }) {
  const root = document.querySelector('#account-root'), output = document.querySelector('#owner-results'), draftInput = document.querySelector('#owner-draft');
  output.hidden = false;
  let current, fake, serial = 0;
  const results = [], eventsLog = [];
  const ref = key => root.querySelector(`[data-owner="${key}"]`);
  const button = key => root.querySelector(`[data-owner-action="${key}"]`);
  const assert = (value, message) => { if (!value) throw new Error(message); };
  async function until(predicate, message = 'state did not settle') { for (let i = 0; i < 150; i++) { if (predicate()) return; await delay(20); } throw new Error(message); }
  function choose(id = 'workspace_old_a') { ref('candidate').value = id; ref('candidate').dispatchEvent(new Event('change', { bubbles: true })); }
  function acknowledge() { ref('ack').checked = true; ref('ack').dispatchEvent(new Event('change', { bubbles: true })); }
  async function setup(customize = () => {}, options = {}) {
    current?.unmount(); draftInput.value = ''; eventsLog.length = 0;
    fake = makeOwnerFake(`owner_suite_${Date.now()}_${++serial}`); customize(fake);
    const events = new EventTarget();
    for (const name of ['session:changed', 'workspace:changed', 'tasks:changed', 'selection:changed']) events.addEventListener(name, event => eventsLog.push({ name, detail: event.detail }));
    current = mount({ root, api: fake.api, session: structuredClone(fake.model.session), events,
      workspaceRecovery: fake.hooks, pollInterval: 80, publicBasePath: new URLSearchParams(location.search).get('base') || '/', ...options });
    await current.ready; return fake;
  }
  async function begin(kind = 'recover') {
    button(kind).click(); await until(() => fake.model.latestIntent && (!button('check').disabled || ref('error').textContent.includes('只读身份范围')));
  }
  async function verified(status = 'awaiting_confirmation') {
    fake.verify(status); button('check').click();
    await until(() => status === 'awaiting_confirmation' ? !ref('confirmation').hidden : ref('attempt-title').textContent.includes(status === 'not_found' ? '没有找到' : '不匹配'));
    await until(() => !button('check').disabled || button('check').hidden);
  }
  async function test(name, run) {
    try { await run(); results.push({ name, passed: true }); }
    catch (err) { results.push({ name, passed: false, error: err.message }); }
    output.textContent = results.map(r => `${r.passed ? 'PASS' : 'FAIL'} ${r.name}${r.error ? `: ${r.error}` : ''}`).join('\n');
  }

  await test('主账号与附加生成账号分区；匿名工作区不宣称永久可找回', async () => {
    await setup();
    assert(ref('bound').textContent === '尚未绑定', 'generation account became workspace owner');
    assert(ref('explanation').textContent.includes('无法安全自动找回'), 'anonymous-cookie limitation missing');
    assert(root.querySelector('[data-view="accounts"]').textContent.includes('附加生成账号'), 'generation account missing');
    assert(ref('workspace').textContent === '当前临时工作区', 'owner section copied generation identity');
  });

  await test('主账号 start 参数严格分支，干净编辑器仍等待确认，禁止重复点击', async () => {
    await setup(); button('bind').click(); button('bind').click();
    await until(() => fake.model.latestIntent && !button('check').disabled);
    const starts = fake.model.calls.filter(c => c.path === '/provider-accounts/authorize');
    assert(starts.length === 1, 'duplicate start');
    assert(starts[0].body.purpose === 'bind_owner' && starts[0].body.hasUnsavedChanges === null, 'wrong owner purpose or automatic recovery enabled');
    assert(Object.keys(starts[0].body).sort().join() === ['hasUnsavedChanges', 'purpose', 'returnPath', 'workspaceLabel'].sort().join(), 'forbidden identity/grant input sent');
    assert(root.querySelector('[data-action="add"]').disabled, 'generation mutations not locked during owner flow');
    assert(root.querySelector('[data-action="refresh"]').disabled, 'generation refresh can race owner session rotation');
    const saved = localStorage.getItem(`asset-lab:workspace-owner:v1:${new URLSearchParams(location.search).get('base') || '/'}:${fake.model.source.id}`);
    assert(!/nonce|proof|subject|authorizationUrl|token|csrf/.test(saved), 'private identity evidence persisted');
  });

  await test('OAuth 完成仅表示身份验证；awaiting_confirmation 不轮换会话或默认选择候选', async () => {
    await setup(); await begin(); const oldSession = fake.model.session.session.id;
    fake.model.attempts.get(fake.model.latestAttempt).status = 'completed';
    button('check').click(); await delay(80);
    assert(ref('attempt-title').textContent.includes('等待官方'), 'OAuth completion falsely became workspace recovery');
    await verified();
    assert(fake.model.session.session.id === oldSession && ref('candidate').value === '', 'awaiting confirmation changed session or preselected target');
    assert(!ref('message').textContent.includes('前往官方'), 'completed identity still asks user to open official link');
    assert(!fake.model.calls.some(c => c.path.endsWith('/confirm')), 'automatic confirmation');
  });

  await test('未保存内容必须持久化后明确保留；确认 CAS 与 session 轮换完整同步', async () => {
    await setup(({ model }) => { model.dirty = true; }); draftInput.value = '不能丢失的未保存剧本';
    await begin(); await verified(); choose(); acknowledge();
    assert(button('confirm').disabled && ref('draft-list').textContent.includes('当前剧本输入'), 'dirty draft can bypass saving');
    button('save').click(); await until(() => ref('draft-status').textContent.includes('已保存') && !button('inspect').disabled);
    acknowledge(); button('confirm').click(); button('confirm').click();
    await until(() => ref('attempt-title').textContent === '原工作区已找回');
    const calls = fake.model.calls, confirmations = calls.filter(c => c.path.endsWith('/confirm'));
    assert(confirmations.length === 1, 'confirmation duplicated');
    const body = confirmations[0].body;
    assert(body.action === 'recover_preserve_current' && body.workspaceId === 'workspace_old_a' && body.expectedContentRevision === 8, 'incorrect preservation/CAS payload');
    assert(body.draftDisposition === 'saved' && body.savedDrafts[0].id === 'synthetic_saved_script', 'no persistent draft evidence');
    const after = calls.slice(calls.indexOf(confirmations[0]) + 1);
    assert(after[0]?.path === '/session' && !after.some(c => c.path.startsWith('/workspace-intents/')), 'old intent used after rotation');
    assert(fake.api.csrf === fake.model.session.csrfToken && eventsLog.some(e => e.name === 'workspace:changed'), 'full session/CSRF/other modules not updated');
    assert(fake.model.source.ownerBound && draftInput.value === '不能丢失的未保存剧本', 'source data or local input lost');
    assert(fake.model.calls.filter(c => c.path === '/provider-accounts/authorize').every(c => c.body.purpose === 'recover_workspace'), 'recovery created generation grant');
  });

  await test('取消明确保留当前工作区，关闭 OAuth 与 owner intent，不清空输入', async () => {
    await setup(({ model }) => { model.dirty = true; }); draftInput.value = '取消后仍保留';
    const id = fake.model.session.session.id;
    await begin(); await verified(); button('cancel').click();
    await until(() => ref('attempt-title').textContent.includes('已取消'));
    assert(fake.model.calls.filter(c => c.path.endsWith('/cancel')).length === 2, 'did not cancel both interfaces');
    assert(fake.model.session.session.id === id && draftInput.value === '取消后仍保留', 'cancel changed session/input');
    assert(!fake.model.calls.some(c => c.path.endsWith('/confirm')), 'cancel confirmed instead');
  });

  await test('附加生成身份没有 owner 记录时不能找回；主账号不匹配不能接管', async () => {
    await setup(); await begin(); await verified('not_found');
    assert(ref('attempt-note').textContent.includes('生成账号不能'), 'not-found boundary unclear');
    assert(!fake.model.calls.some(c => c.path.endsWith('/confirm')), 'unbound identity acquired workspace');
    await setup(); await begin(); await verified('blocked');
    assert(ref('attempt-note').textContent.includes('不能转移所有权'), 'owner mismatch boundary unclear');
  });

  await test('绑定已有主账号只绑定当前工作区，不选择或进入旧候选', async () => {
    await setup(); const sourceId = fake.model.source.id; await begin('bind'); await verified();
    localStorage.setItem(`asset-lab:accounts:v1:${sourceId}`, JSON.stringify({ draft: null, attempt: {
      attemptId: 'old_generation_attempt', status: 'pending', siteSessionId: fake.model.session.session.id, expiresAt: new Date(Date.now() + 60000).toISOString(),
    } }));
    assert(ref('choice').hidden && ref('bind-candidates').textContent.includes('原来的角色'), 'binding incorrectly offered recovery choice');
    acknowledge(); button('confirm').click(); await until(() => ref('attempt-title').textContent === '工作区主账号已绑定');
    const body = fake.model.calls.find(c => c.path.endsWith('/confirm')).body;
    assert(body.action === 'bind_current' && !('workspaceId' in body) && fake.model.session.tenant.id === sourceId, 'bind switched target');
    assert(button('bind').disabled && ref('bound').textContent === '已绑定', 'bound state not refreshed');
    assert(!JSON.parse(localStorage.getItem(`asset-lab:accounts:v1:${sourceId}`) || '{}').attempt, 'same-tenant session rotation retained old generation authorization context');
  });

  await test('授权期间新增草稿也会挡住确认；开始时 dirty 不能用清空编辑器绕过', async () => {
    await setup(); await begin(); fake.model.dirty = true; await verified(); choose(); acknowledge();
    assert(button('confirm').disabled, 'late draft bypassed confirmation');
    await setup(({ model }) => { model.dirty = true; }); await begin(); fake.model.dirty = false; await verified(); choose(); acknowledge();
    assert(button('confirm').disabled && !button('save').disabled, 'initially dirty flow accepted none without persistent save');
  });

  await test('内容 revision 冲突保留候选与输入，重新核对后才允许再次确认', async () => {
    await setup(); await begin(); await verified(); choose(); acknowledge();
    fake.model.source.content.revision++;
    button('confirm').click(); await until(() => ref('error').textContent.includes('刚刚发生变化') && !button('inspect').disabled);
    assert(fake.model.calls.filter(c => c.path.endsWith('/confirm')).length === 1, 'confirmation was silently retried');
    assert(ref('candidate').value === 'workspace_old_a' && !ref('ack').checked, 'conflict lost choice or retained stale ack');
    acknowledge(); button('confirm').click(); await until(() => ref('attempt-title').textContent === '原工作区已找回');
    assert(fake.model.calls.filter(c => c.path.endsWith('/confirm')).at(-1).body.expectedContentRevision === 8, 'fresh content revision missing');
  });

  await test('写入权限的主账号 OAuth URL 被拒绝；没有真实授权链接泄露到本地存储', async () => {
    await setup(({ model }) => { model.authorizationScope = 'libtv:account:read libtv:task:write'; }); await begin();
    assert(ref('error').textContent.includes('只读身份范围') && !ref('official').hasAttribute('href'), 'write scope authorization opened');
    assert(!Object.keys(localStorage).filter(k => k.includes(fake.model.source.id)).some(k => localStorage.getItem(k).includes('scope=')), 'authorization URL stored');
  });

  await test('刷新恢复 awaiting_confirmation 需服务端重新读取；旧 session marker 不可复用', async () => {
    await setup(); await begin(); await verified();
    const sourceId = fake.model.source.id, hooks = fake.hooks, api = fake.api;
    current.unmount();
    current = mount({ root, api, session: structuredClone(fake.model.session), events: new EventTarget(), workspaceRecovery: hooks, pollInterval: 80,
      publicBasePath: new URLSearchParams(location.search).get('base') || '/' });
    await current.ready; await until(() => !ref('confirmation').hidden);
    assert(ref('candidate').value === '', 'persisted choice silently became confirmation');
    current.unmount(); fake.model.session.session.id = 'ss_new_without_proof';
    const before = fake.model.calls.length;
    current = mount({ root, api, session: structuredClone(fake.model.session), events: new EventTarget(), workspaceRecovery: hooks,
      publicBasePath: new URLSearchParams(location.search).get('base') || '/' });
    await current.ready; await delay(60);
    assert(!fake.model.calls.slice(before).some(c => c.path.startsWith('/workspace-intents/')), 'old session proof marker reused');
  });

  await test('会话失效通过注入 adapter 建临时会话，保留输入并重新走官方 owner 验证', async () => {
    await setup(({ model }) => { model.dirty = true; }); draftInput.value = '失效会话的未保存输入';
    fake.model.expiredSession = true; button('refresh').click();
    await until(() => !ref('bootstrap-note').hidden);
    button('bootstrap').click(); await until(() => fake.model.hooksLog.some(x => x.type === 'bootstrap') && ref('bootstrap-note').hidden);
    assert(draftInput.value === '失效会话的未保存输入', 'bootstrap erased local input');
    assert(fake.model.hooksLog.find(x => x.type === 'rotated').preserveUnsavedInputs === true, 'bootstrap did not tell integrator to retain drafts');
    await until(() => !button('recover').disabled); await begin();
    assert(fake.model.startBody.purpose === 'recover_workspace' && fake.model.startBody.hasUnsavedChanges === true, 'fresh session bypassed owner verification/drafts');
  });

  await test('轮换后其他模块同步失败保持锁定，重试同步而不重发确认', async () => {
    await setup(); await begin(); await verified(); choose(); acknowledge(); fake.model.syncFailure = true;
    button('confirm').click(); await until(() => !button('sync').hidden);
    assert(root.querySelector('[data-action="add"]').disabled && current.getDirtyState().dirty, 'stale context remained usable after sync failure');
    fake.model.syncFailure = false; button('sync').click(); await until(() => ref('attempt-title').textContent === '原工作区已找回');
    assert(fake.model.calls.filter(c => c.path.endsWith('/confirm')).length === 1, 'sync retry resent confirmation');
  });

  await test('尚未接线的 owner 能力不因已有生成账号而开放；过期确认不能提交', async () => {
    await setup(({ hooks }) => { hooks.enabled = false; });
    assert(button('bind').disabled && button('recover').disabled, 'generation authorization enabled workspace recovery');
    await setup(); await begin(); await verified();
    fake.model.intents.get(fake.model.latestIntent).proofExpiresAt = '2020-01-01T00:00:00Z';
    button('check').click(); await until(() => ref('attempt-title').textContent.includes('已过期'));
    assert(ref('confirmation').hidden && !fake.model.calls.some(c => c.path.endsWith('/confirm')), 'expired proof can submit');
  });

  await test('其他标签页轮换 session 时停止旧 intent 请求，未保存输入交给集成层保留', async () => {
    await setup(({ model }) => { model.dirty = true; }); draftInput.value = '其他标签页切换时仍要保留'; await begin();
    await until(() => !button('check').disabled);
    const next = structuredClone(fake.model.candidates[1]);
    fake.model.session = { ...fake.model.session, tenant: { id: next.id }, session: { id: 'ss_external_rotation' }, csrfToken: 'csrf_external', workspace: next };
    const before = fake.model.calls.length; button('check').click();
    await until(() => fake.model.hooksLog.some(x => x.type === 'rotated'));
    const notification = fake.model.hooksLog.find(x => x.type === 'rotated');
    assert(notification.preserveUnsavedInputs === true && notification.result === null, 'unexpected rotation discarded drafts or claimed recovery');
    assert(!fake.model.calls.slice(before).some(c => c.path.startsWith('/workspace-intents/')), 'old intent read with rotated context');
    assert(draftInput.value === '其他标签页切换时仍要保留', 'external rotation lost input');
  });

  await test('状态请求未完成时禁止并发确认与取消，轮换后不遗留旧 intent 请求', async () => {
    await setup(); await begin(); await verified(); choose(); acknowledge();
    let release, reading = false;
    fake.model.intercept = (path, options) => {
      if (path === `/workspace-intents/${fake.model.latestIntent}` && !options.method) {
        reading = true;
        return new Promise(resolve => { release = () => resolve(structuredClone(fake.model.intents.get(fake.model.latestIntent))); });
      }
    };
    button('check').click(); await until(() => reading);
    assert(button('confirm').disabled && button('cancel').disabled && button('save').disabled, 'owner mutation raced status request');
    button('confirm').click(); button('cancel').click();
    assert(!fake.model.calls.some(c => c.path.endsWith('/confirm') || c.path.endsWith('/cancel')), 'disabled mutation was sent');
    fake.model.intercept = null; release(); await until(() => !button('confirm').disabled);
    button('confirm').click(); await until(() => ref('attempt-title').textContent === '原工作区已找回');
    const calls = fake.model.calls, index = calls.findIndex(c => c.path.endsWith('/confirm'));
    assert(calls[index + 1]?.path === '/session' && !calls.slice(index + 1).some(c => c.path.startsWith('/workspace-intents/')), 'old intent request followed cookie rotation');
  });

  await test('恢复本地等待记录不能绕过已关闭的 owner 接线', async () => {
    await setup(); await begin(); await verified(); current.unmount(); fake.hooks.enabled = false;
    current = mount({ root, api: fake.api, session: structuredClone(fake.model.session), events: new EventTarget(),
      workspaceRecovery: fake.hooks, publicBasePath: new URLSearchParams(location.search).get('base') || '/' });
    await current.ready; await until(() => !ref('confirmation').hidden && !button('check').disabled);
    choose(); acknowledge();
    assert(button('confirm').disabled && button('save').disabled, 'restored intent enabled closed capability');
    button('confirm').click(); assert(!fake.model.calls.some(c => c.path.endsWith('/confirm')), 'disabled recovery submitted');
    button('cancel').click(); await until(() => ref('attempt-title').textContent.includes('已取消'));
  });

  current?.unmount();
  document.documentElement.dataset.testStatus = results.every(r => r.passed) ? 'passed' : 'failed';
  document.documentElement.dataset.testCount = String(results.length);
  document.title = `${results.filter(r => r.passed).length}/${results.length} · 主账号恢复浏览器验证`;
  output.textContent += `\n\n${results.filter(r => r.passed).length}/${results.length} passed. Synthetic owner proof only; no real OAuth, grant storage or paid generation.`;
  Object.keys(localStorage).filter(key => key.includes('owner_suite_')).forEach(key => localStorage.removeItem(key));
}
