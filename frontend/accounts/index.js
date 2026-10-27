import { accountLabels, accountState, accountName, validSelection, sameSelection, selectable,
  officialAuthorizationUrl, publicReturnPath, attemptState, activeAttempt, publicAttemptError, timeLabel, quotaPresentation, errorText } from './state.js';
import { mountWorkspaceOwner } from './workspace-owner.js';

let mountCount = 0;
const e = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const idPath = value => encodeURIComponent(value);
const freshKey = () => globalThis.crypto?.randomUUID?.() || `accounts-${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** Mount only into the shell's account-root; never replace any project/workflow content. */
export function mount({ root, api, events = new EventTarget(), session = null, publicBasePath = '/', pollInterval = 2500, workspaceRecovery = {}, localClient = false }) {
  if (!root?.ownerDocument || typeof api?.request !== 'function') throw new TypeError('accounts.mount requires root and api.request');
  const document = root.ownerDocument;
  const win = document.defaultView;
  const prefix = `al-account-${++mountCount}`;
  const source = freshKey();
  const returnPath = publicReturnPath(publicBasePath);
  let disposed = false, epoch = 0, refreshSequence = 0, spaceSequence = 0, quotaSequence = 0;
  let snapshot = session, accounts = [], spaces = [], quota = null, selectedSpaceLabel = null;
  let loading = true, spacesLoading = false, quotaLoading = false, busy = null;
  let error = '', notice = '', status = '', spacesError = '', quotaError = '';
  let draft = { providerAccountId: null, spaceId: null }, dirty = false;
  let attempt = null, authorizationUrl = null, popup = null, timer = null, polling = false;
  let storageKey = null, initializedTenant = false, removal = null, restoreFocus = null;
  let optionsSignature = '', spacesSignature = '', cardsSignature = '';
  let ownerModule = null;
  const defaults = { providerAccountId: null, spaceId: null, revision: 0 };
  const selection = () => validSelection(snapshot?.selection) ? snapshot.selection : defaults;
  const currentAccount = () => accounts.find(a => a.id === draft.providerAccountId);
  const currentSpace = () => spaces.find(s => s.id === draft.spaceId);
  const canAuthorize = () => snapshot?.features?.providerAuthorization === true;
  const blocked = () => Boolean(busy || loading || activeAttempt(attempt) || ownerModule?.isActive());
  const emit = (name, detail) => events.dispatchEvent(new win.CustomEvent(name, { detail: { ...detail, source } }));
  const request = (path, options) => api.request(path, options);
  const fail = code => Object.assign(new Error(code), { code });

  root.classList.add('al-accounts');
  root.innerHTML = `
    <section aria-labelledby="${prefix}-title" class="al-accounts__panel">
      <header class="al-accounts__header">
        <div class="al-accounts__brand" aria-hidden="true">L</div>
        <div class="al-accounts__heading"><p class="al-accounts__eyebrow">账户与工作空间</p><h2 id="${prefix}-title">LibTV 账号</h2></div>
        <button type="button" data-action="refresh" class="al-accounts__button al-accounts__button--quiet">刷新状态</button>
        <button type="button" data-action="add" class="al-accounts__button al-accounts__button--primary">＋ 添加账号</button>
        <button type="button" data-action="add-creator" class="al-accounts__button al-accounts__button--quiet">授权图片创作</button>
      </header>
      <div data-view="owner-root"></div>
      <div data-view="activity" role="status" aria-live="polite" hidden><span data-view="activity-label"></span><progress aria-label="正在核对账号与空间"></progress></div>
      <h3 class="al-accounts__generation-title">生成账号</h3>
      <p class="al-accounts__intro">在 LibTV 官方页面登录，再选择个人或团队空间。连接账号仅申请账号读取；开启创作权限会另行申请项目、图片生成、参考图上传与素材导出。授权本身不会发起生成。</p>
      <p class="al-accounts__notice" data-view="notice" hidden></p>
      <div data-view="status" class="al-accounts__status" role="status" aria-live="polite" aria-atomic="true"></div>
      <div data-view="error" class="al-accounts__error" role="alert" aria-atomic="true" hidden></div>
      <section data-view="attempt" class="al-accounts__attempt" aria-labelledby="${prefix}-attempt" hidden>
        <div class="al-accounts__row"><h3 id="${prefix}-attempt" tabindex="-1" data-view="attempt-title"></h3><span class="al-accounts__badge" data-view="attempt-badge"></span></div>
        <p data-view="attempt-note"></p>
        <div class="al-accounts__actions">
          <a data-view="official-link" class="al-accounts__button" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" hidden>前往官方授权 ↗</a>
          <button type="button" data-action="check" class="al-accounts__button">检查授权结果</button>
          <button type="button" data-action="pause" class="al-accounts__button al-accounts__button--quiet">取消等待</button>
          <button type="button" data-action="dismiss-attempt" class="al-accounts__button al-accounts__button--quiet" hidden>收起</button>
        </div>
      </section>
      <div class="al-accounts__section-heading"><h3>已添加账号</h3><span data-view="count" class="al-accounts__muted"></span></div>
      <div data-view="accounts" class="al-accounts__list" aria-busy="true"></div>
      <form data-view="form" class="al-accounts__selection" aria-labelledby="${prefix}-selection-title">
        <div class="al-accounts__row"><h3 id="${prefix}-selection-title">新任务使用的账号与空间</h3><span data-view="draft-badge" class="al-accounts__badge" hidden>尚未应用</span></div>
        <p data-view="current" class="al-accounts__current"></p>
        <div class="al-accounts__fields">
          <div><label for="${prefix}-identity">登录账号</label><select id="${prefix}-identity" data-view="identity" aria-describedby="${prefix}-scope"></select></div>
          <div><label for="${prefix}-space">工作空间</label><select id="${prefix}-space" data-view="space" aria-describedby="${prefix}-space-note"></select><p id="${prefix}-space-note" data-view="space-note" class="al-accounts__field-note"></p></div>
        </div>
        <div data-view="quota" class="al-accounts__quota" aria-busy="false"><div><p data-view="quota-label" class="al-accounts__eyebrow"></p><strong data-view="quota-value"></strong><p data-view="quota-note" class="al-accounts__field-note"></p><p data-view="plan" class="al-accounts__field-note" hidden></p></div><button type="button" data-action="quota" class="al-accounts__button al-accounts__button--quiet">查询余额</button></div>
        <div class="al-accounts__selection-footer"><p id="${prefix}-scope">切换仅用于之后的新任务。已有任务与素材保留原账号和空间归属。</p><button type="submit" data-action="apply" class="al-accounts__button al-accounts__button--primary">应用到新任务</button></div>
      </form>
      <dialog data-view="remove-dialog" class="al-accounts__dialog" aria-labelledby="${prefix}-remove-title" aria-describedby="${prefix}-remove-note"><h3 id="${prefix}-remove-title">移除这个账号？</h3><p data-view="remove-name"></p><p id="${prefix}-remove-note">本站将停止使用这个账号的授权。项目、文件和历史任务归属会保留；未完成任务可能需要重新授权。远端正在运行的任务不会因此自动停止。</p><div class="al-accounts__actions"><button type="button" data-action="keep-account" class="al-accounts__button" autofocus>保留账号</button><button type="button" data-action="confirm-remove" class="al-accounts__button al-accounts__button--danger">确认移除</button></div></dialog>
    </section>`;
  const refs = Object.fromEntries([...root.querySelectorAll('[data-view]')].map(el => [el.dataset.view, el]));
  const buttons = Object.fromEntries([...root.querySelectorAll('button[data-action]')].map(el => [el.dataset.action, el]));
  if (localClient) {
    buttons.add.textContent = '授权 LibTV';
    root.querySelector('.al-accounts__generation-title').textContent = '连接我的 LibTV';
    root.querySelector('.al-accounts__intro').textContent = '点击授权 → 在 LibTV 官方页面登录并确认 → 选择账号与空间。首次连接仅读取账号；需要制作时，点击该账号的“开启创作权限”，核对项目、生成、上传与导出权限。授权不会自动开始生成。';
    refs['owner-root'].hidden = true;
  }
  const text = (name, value) => { if (refs[name].textContent !== value) refs[name].textContent = value; };
  const setError = value => { error = value; render(); };

  function saveLocal(updateAttempt = false) {
    if (!storageKey) return true;
    let previous = null, applied = true;
    try { previous = JSON.parse(win.localStorage.getItem(storageKey) || 'null')?.attempt || null; } catch { /* Optional storage. */ }
    if (previous?.siteSessionId !== snapshot?.session?.id) previous = null;
    // Saving an unrelated draft or unmounting an older tab must never erase another
    // tab's in-progress authorization. Terminal results also cannot regress to pending.
    if (updateAttempt && previous && ((activeAttempt(previous) && previous.attemptId !== attempt?.attemptId)
        || (previous.attemptId === attempt?.attemptId && previous.status !== 'pending' && attempt?.status === 'pending'))) {
      attempt = previous; authorizationUrl = null; applied = false;
    }
    const storedAttempt = updateAttempt ? attempt : previous;
    const record = { draft: dirty ? { ...draft } : null, attempt: storedAttempt ? {
      attemptId: storedAttempt.attemptId, expiresAt: storedAttempt.expiresAt, status: storedAttempt.status,
      siteSessionId: storedAttempt.siteSessionId,
      paused: Boolean(storedAttempt.paused), accountId: storedAttempt.accountId || null,
      error: publicAttemptError(storedAttempt.error),
    } : null };
    try { win.localStorage.setItem(storageKey, JSON.stringify(record)); } catch { /* Storage is optional. Server is authoritative. */ }
    return applied;
  }

  function restoreLocal() {
    try {
      const record = JSON.parse(win.localStorage.getItem(storageKey) || 'null');
      if (record?.draft && (typeof record.draft.providerAccountId === 'string' || record.draft.providerAccountId === null)
          && (typeof record.draft.spaceId === 'string' || record.draft.spaceId === null)) {
        draft = { providerAccountId: record.draft.providerAccountId, spaceId: record.draft.spaceId };
        dirty = !sameSelection(draft, selection());
      }
      if (record?.attempt && typeof record.attempt.attemptId === 'string'
          && record.attempt.siteSessionId === snapshot?.session?.id
          && record.attempt.attemptId.length <= 256 && Number.isFinite(Date.parse(record.attempt.expiresAt))) {
        attempt = { ...record.attempt };
      }
    } catch { /* Ignore corrupt or disabled local storage. */ }
  }

  function acceptSession(next) {
    if (!validSelection(next?.selection) || typeof next?.tenant?.id !== 'string') throw fail('INVALID_RESPONSE');
    const nextKey = `asset-lab:accounts:v1:${next.tenant.id}`;
    const changedTenant = storageKey !== nextKey;
    const changedSession = Boolean(snapshot?.session?.id && next.session?.id !== snapshot.session.id);
    if (changedSession && storageKey) {
      try {
        const previous = JSON.parse(win.localStorage.getItem(storageKey) || 'null');
        if (previous) win.localStorage.setItem(storageKey, JSON.stringify({ draft: previous.draft || null, attempt: null }));
      } catch { /* Preserve drafts; only obsolete authorization attempts are cleared. */ }
    }
    if (changedTenant || changedSession) {
      epoch++; refreshSequence++; spaceSequence++; quotaSequence++;
      clearTimeout(timer); timer = null; attempt = null; authorizationUrl = null;
      closePopup(); closeRemove(); accounts = []; spaces = []; quota = null; selectedSpaceLabel = null; error = ''; status = '';
      if (changedTenant) { dirty = false; initializedTenant = false; }
      busy = null; polling = false;
    }
    snapshot = { ...next, selection: { ...(!changedTenant && next.selection.revision < selection().revision
      ? selection() : next.selection) } };
    storageKey = nextKey;
    api.setCsrfToken?.(next.csrfToken);
    if (!dirty) draft = { ...selection() };
    if (!initializedTenant) { restoreLocal(); initializedTenant = true; }
    if (changedTenant && activeAttempt(attempt)) schedulePoll(0);
    ownerModule?.setSession(snapshot);
  }

  function render() {
    if (disposed) return;
    const account = currentAccount(), space = currentSpace();
    const selected = selection(), selectedAccount = accounts.find(a => a.id === selected.providerAccountId);
    const selectedSpace = (selected.providerAccountId === draft.providerAccountId ? spaces.find(s => s.id === selected.spaceId) : null)
      || (selectedSpaceLabel?.providerAccountId === selected.providerAccountId && selectedSpaceLabel?.id === selected.spaceId ? selectedSpaceLabel : null);
    const connectedAccount = accounts.find(a=>accountState(a)==='connected');
    text('status', status || (connectedAccount ? `LibTV 已连接${connectedAccount.grantedScopes?.includes('libtv:task:write')?'，图片创作权限已授权':''}。` : ''));
    const activity = busy ? '正在保存账号操作…' : loading ? '正在读取已连接账号…' : spacesLoading ? '正在向 LibTV 核对空间权限…' : quotaLoading ? '正在查询所选空间余额…' : polling ? '正在检查授权结果…' : '';
    refs.activity.hidden = !activity; text('activity-label', activity);
    refs.error.hidden = !error; text('error', error);
    notice = !canAuthorize() ? 'LibTV 网页授权暂未开放。已保存的项目与素材可继续查看；入口开放后可直接在网页添加账号。' : '';
    refs.notice.hidden = !notice; text('notice', notice);
    buttons.add.disabled = blocked() || !canAuthorize();
    if(localClient)buttons.add.textContent = connectedAccount ? '添加另一个账号' : '授权 LibTV';
    buttons['add-creator'].disabled = blocked() || !canAuthorize();
    buttons.refresh.disabled = Boolean(loading || busy || ownerModule?.isActive());
    refs.accounts.setAttribute('aria-busy', String(loading));
    text('count', loading ? '正在读取…' : `${accounts.length} 个账号`);
    const cards = accounts.map(a => {
      const state = accountState(a), name = accountName(a), selected = a.id === selection().providerAccountId;
      return `<article class="al-accounts__card ${selected ? 'al-accounts__card--selected' : ''}"><div class="al-accounts__avatar" aria-hidden="true">${e(name.slice(0, 1))}</div><div class="al-accounts__card-info"><div class="al-accounts__row"><h4>${e(name)}</h4><span class="al-accounts__badge" data-state="${e(state)}">${accountLabels[state]}</span>${selected ? '<span class="al-accounts__current-tag">当前</span>' : ''}</div><p>${a.identity?.verified ? '官方身份已验证' : '官方身份尚未验证'}${a.identity?.displayName && a.identity.displayName !== name ? ` · ${e(a.identity.displayName)}` : ''}</p></div><div class="al-accounts__actions"><button type="button" class="al-accounts__button al-accounts__button--quiet" data-action="choose" data-id="${e(a.id)}" ${blocked() || state !== 'connected' ? 'disabled' : ''} aria-label="选择账号 ${e(name)}">选择</button><button type="button" class="al-accounts__button al-accounts__button--quiet" data-action="reauthorize" data-id="${e(a.id)}" ${blocked() || !canAuthorize() || a.capabilities?.authorize !== true ? 'disabled' : ''} aria-label="重新授权 ${e(name)}">重新授权</button><button type="button" class="al-accounts__button al-accounts__button--quiet" data-action="creator" data-id="${e(a.id)}" ${blocked() || !canAuthorize() || a.capabilities?.authorize !== true ? 'disabled' : ''}>${a.grantedScopes?.includes('libtv:task:write') ? '更新创作权限' : '开启创作权限'}</button><button type="button" class="al-accounts__button al-accounts__button--quiet" data-action="remove" data-id="${e(a.id)}" ${blocked() ? 'disabled' : ''} aria-label="移除账号 ${e(name)}">移除</button></div></article>`;
    }).join('') || `<div class="al-accounts__empty"><span aria-hidden="true">◎</span><strong>${loading ? '正在读取账号' : '添加你的第一个 LibTV 账号'}</strong><p>${loading ? '稍等片刻，正在恢复账号状态。' : '授权完成后，个人与团队空间会分别显示在下方。'}</p></div>`;
    if (cards !== cardsSignature) {
      const focused = document.activeElement;
      const focus = refs.accounts.contains(focused) ? { action: focused.dataset.action, id: focused.dataset.id } : null;
      refs.accounts.innerHTML = cards; cardsSignature = cards;
      if (focus) [...refs.accounts.querySelectorAll('button')].find(b => b.dataset.action === focus.action && b.dataset.id === focus.id)?.focus();
    }
    const options = `<option value="">请选择登录账号</option>` + accounts.map(a => `<option value="${e(a.id)}" ${accountState(a) !== 'connected' ? 'disabled' : ''}>${e(accountName(a))} · ${accountLabels[accountState(a)]}</option>`).join('');
    if (options !== optionsSignature) { refs.identity.innerHTML = options; optionsSignature = options; }
    refs.identity.value = draft.providerAccountId || ''; refs.identity.disabled = blocked() || !accounts.length;
    const spaceOptions = `<option value="">${spacesLoading ? '正在读取空间…' : '请选择工作空间'}</option>`
      + ['personal', 'team'].map(kind => { const items = spaces.filter(s => s.kind === kind); return items.length ? `<optgroup label="${kind === 'personal' ? '个人空间' : '团队空间'}">${items.map(s => `<option value="${e(s.id)}" ${!selectable(account, s) ? 'disabled' : ''}>${e(s.name)}${s.access === 'revoked' ? ' · 已失去访问权限' : s.access !== 'available' ? ' · 权限待核实' : ''}</option>`).join('')}</optgroup>` : ''; }).join('');
    if (spaceOptions !== spacesSignature) { refs.space.innerHTML = spaceOptions; spacesSignature = spaceOptions; }
    refs.space.value = draft.spaceId || '';
    refs.space.disabled = blocked() || spacesLoading || accountState(account) !== 'connected';
    text('space-note', spacesError || (spacesLoading ? '正在从官方读取此账号的空间。' : !account ? '先选择登录账号，再选择个人或团队空间。' : accountState(account) !== 'connected' ? '请先完成这个账号的官方授权。' : spaces.length ? '选择团队空间不会切换登录身份。' : '暂未获得可用空间，请刷新状态重试。'));
    text('current', selected.providerAccountId ? `当前：${selectedAccount ? accountName(selectedAccount) : '原账号暂不可用'} / ${selected.spaceId ? selectedSpace?.name || '已保存的空间（待核实）' : '未选择空间'}${selectedAccount && accountState(selectedAccount) !== 'connected' ? ' · 请重新授权后再创建任务' : ''}` : '当前尚未选择账号与空间。');
    refs['draft-badge'].hidden = !dirty;
    buttons.apply.disabled = blocked() || spacesLoading || !dirty || !selectable(account, space);
    buttons.apply.textContent = busy === 'selection' ? '正在切换…' : '应用到新任务';
    const q = quotaPresentation(quota);
    text('quota-label', q.label);
    text('quota-value', quotaLoading ? '正在查询…' : !space ? '选择空间后查询' : q.value);
    text('quota-note', quotaError || (!space ? '余额只对应所选账号的这个空间。' : q.note));
    text('plan', quota?.planName ? `套餐：${quota.planName}（不代表可用余额）` : '');
    refs.plan.hidden = !quota?.planName;
    refs.quota.setAttribute('aria-busy', String(quotaLoading));
    buttons.quota.disabled = blocked() || spacesLoading || quotaLoading || !selectable(account, space);
    renderAttempt();
    ownerModule?.render();
  }

  function renderAttempt() {
    refs.attempt.hidden = !attempt;
    if (!attempt) return;
    const state = attemptState(attempt);
    const titles = { pending: '等待 LibTV 官方授权', paused: '已取消等待，授权结果尚未确认', completed: '官方授权已完成', expired: '本次授权已过期', cancelled: '已在官方页面取消授权', failed: '本次授权未完成' };
    const notes = { pending: `请在官方页面完成登录，本站会自动检查结果。有效至 ${timeLabel(attempt.expiresAt)}。`, paused: '已停止自动检查。若官方页面仍然打开，授权仍可能完成；可以继续检查结果。', completed: '账号状态已重新查询。选择该账号和工作空间后，再应用到新任务。', expired: attempt.status === 'pending' ? '授权链接已过期。如果之前已在官方完成，可检查结果；也可重新发起授权。' : '此链接已失效。可以重新点击添加账号或重新授权。', cancelled: '官方返回了取消结果。你可以随时重新发起授权。', failed: errorText(attempt.error) };
    if (state === 'expired' && attempt.status === 'pending') titles.expired = '授权链接已过期，结果待核实';
    text('attempt-title', titles[state]); text('attempt-note', attempt.pollError || notes[state]);
    text('attempt-badge', { pending: '进行中', paused: '已暂停检查', completed: '完成', expired: '已过期', cancelled: '已取消', failed: '失败' }[state]);
    refs['attempt-badge'].dataset.state = state === 'completed' ? 'connected' : state;
    refs['official-link'].hidden = !authorizationUrl || !activeAttempt(attempt);
    if (authorizationUrl && activeAttempt(attempt)) refs['official-link'].href = authorizationUrl;
    else refs['official-link'].removeAttribute('href');
    buttons.check.hidden = attempt.status !== 'pending'; buttons.check.disabled = polling || Boolean(busy);
    buttons.check.textContent = state === 'paused' ? '继续检查结果' : state === 'expired' ? '检查是否已完成' : '检查授权结果';
    buttons.pause.hidden = state !== 'pending'; buttons.pause.disabled = Boolean(busy);
    buttons['dismiss-attempt'].hidden = activeAttempt(attempt);
  }

  async function readList(path) {
    const items = [], seen = new Set(); let cursor = null;
    do {
      const data = await request(path + (cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''));
      if (!Array.isArray(data?.items)) throw fail('INVALID_RESPONSE');
      items.push(...data.items); cursor = data.nextCursor || null;
      if (cursor && (seen.has(cursor) || seen.size >= 99)) throw fail('INVALID_RESPONSE');
      seen.add(cursor);
    } while (cursor);
    return items;
  }

  async function refresh({ rereadSession = true } = {}) {
    if (disposed) return;
    const seq = ++refreshSequence, startedEpoch = epoch;
    let acceptedEpoch = startedEpoch, acceptedSequence = seq;
    loading = true; render();
    try {
      let next = snapshot;
      if (rereadSession || !next) next = await request('/session');
      if (disposed || startedEpoch !== epoch || seq !== refreshSequence) return;
      acceptSession(next);
      acceptedEpoch = epoch; acceptedSequence = refreshSequence;
      const items = await readList('/provider-accounts');
      if (disposed || acceptedEpoch !== epoch || acceptedSequence !== refreshSequence) return;
      accounts = items.filter(a => a.provider === 'libtv' && accountState(a) !== 'removed');
      if (draft.providerAccountId && !accounts.some(a => a.id === draft.providerAccountId)) {
        draft = { providerAccountId: null, spaceId: null }; dirty = !sameSelection(draft, selection()); saveLocal();
      }
      emit('provider-accounts:changed', { items: accounts });
      emit('session:changed', { session: snapshot });
      await loadSpaces();
      if (acceptedEpoch !== epoch || acceptedSequence !== refreshSequence) return;
      error = ''; loading = false; render();
      if (attempt?.status === 'pending' && !attempt.paused) { clearTimeout(timer); timer = setTimeout(() => void poll(), 0); }
    } catch (err) { if (!disposed && acceptedEpoch === epoch && acceptedSequence === refreshSequence) { error = errorText(err); loading = false; render(); } }
  }

  async function loadSpaces() {
    const seq = ++spaceSequence, localEpoch = epoch, account = currentAccount();
    quotaSequence++; spaces = []; quota = null; spacesError = ''; quotaError = ''; quotaLoading = false;
    if (!account || accountState(account) !== 'connected' || account.capabilities?.spaces === false) { spacesLoading = false; render(); return; }
    spacesLoading = true; render();
    try {
      const result = await readList(`/provider-accounts/${idPath(account.id)}/spaces`);
      if (disposed || localEpoch !== epoch || seq !== spaceSequence || draft.providerAccountId !== account.id) return;
      spaces = result; spacesLoading = false;
      const saved = spaces.find(s => s.id === selection().spaceId);
      if (account.id === selection().providerAccountId && saved) selectedSpaceLabel = { id: saved.id, name: saved.name, providerAccountId: account.id };
      if (draft.spaceId && !spaces.some(s => s.id === draft.spaceId)) {
        draft = { ...draft, spaceId: null }; dirty = !sameSelection(draft, selection()); saveLocal();
      }
      render(); await loadQuota();
    } catch (err) { if (!disposed && localEpoch === epoch && seq === spaceSequence) { spacesError = errorText(err); spacesLoading = false; render(); } }
  }

  async function loadQuota() {
    const seq = ++quotaSequence, localEpoch = epoch, account = currentAccount(), space = currentSpace();
    quota = null; quotaError = ''; quotaLoading = false;
    if (!selectable(account, space)) { render(); return; }
    if (account.capabilities?.quota === false) { quota = { state: 'unknown' }; render(); return; }
    quotaLoading = true; render();
    try {
      const result = await request(`/provider-accounts/${idPath(account.id)}/spaces/${idPath(space.id)}/quota`);
      if (disposed || localEpoch !== epoch || seq !== quotaSequence) return;
      if (result?.providerAccountId !== account.id || result?.spaceId !== space.id) throw fail('OWNERSHIP_MISMATCH');
      quota = result;
    } catch (err) { if (!disposed && localEpoch === epoch && seq === quotaSequence) { quotaError = errorText(err); quota = { state: 'unavailable' }; } }
    finally { if (!disposed && localEpoch === epoch && seq === quotaSequence) { quotaLoading = false; render(); } }
  }

  async function chooseAccount(id) {
    if (blocked()) return;
    if (id && accountState(accounts.find(a => a.id === id)) !== 'connected') return;
    draft = { providerAccountId: id || null, spaceId: null };
    dirty = !sameSelection(draft, selection()); saveLocal(); error = '';
    await loadSpaces();
  }

  async function applySelection() {
    if (blocked() || spacesLoading || !dirty || !selectable(currentAccount(), currentSpace())) return;
    const localEpoch = epoch, appliedSpace = currentSpace();
    const body = { providerAccountId: draft.providerAccountId, spaceId: draft.spaceId, expectedRevision: selection().revision };
    busy = 'selection'; error = ''; status = '正在保存新任务的账号与空间…'; render();
    try {
      const result = await request('/selection', { method: 'PUT', body });
      if (disposed || localEpoch !== epoch) return;
      if (!validSelection(result) || !sameSelection(result, body) || result.revision <= body.expectedRevision) throw fail('INVALID_RESPONSE');
      if (result.revision < selection().revision) throw fail('SELECTION_CHANGED');
      snapshot = { ...snapshot, selection: result }; draft = { ...result }; dirty = false; saveLocal();
      selectedSpaceLabel = { id: body.spaceId, name: appliedSpace.name, providerAccountId: body.providerAccountId };
      status = '已应用到之后的新任务。已有任务归属保持不变。';
      emit('selection:changed', { selection: result }); emit('session:changed', { session: snapshot });
    } catch (err) {
      if (disposed || localEpoch !== epoch) return;
      const message = errorText(err);
      if (['SELECTION_CHANGED', 'VERSION_CONFLICT', 'CSRF_FAILED'].includes(err.code)) await refresh();
      if (disposed || localEpoch !== epoch) return;
      error = message; status = '';
    } finally { if (!disposed && localEpoch === epoch) { busy = null; render(); } }
  }

  function closePopup() { try { if (popup && !popup.closed) popup.close(); } catch { /* Detached official window. */ } popup = null; }
  function openBlankPopup() {
    try {
      popup = win.open('about:blank', '_blank', 'popup,width=560,height=760');
      if (popup) { popup.opener = null; popup.document.title = '正在准备 LibTV 官方授权'; popup.document.body.textContent = '正在准备 LibTV 官方授权页面…'; }
    } catch { popup = null; }
  }

  async function beginAuthorization(accountId = null, authorizationProfile = 'account') {
    if (blocked() || !canAuthorize()) return;
    const account = accounts.find(a => a.id === accountId);
    if (accountId && (!account || account.capabilities?.authorize !== true)) return;
    const localEpoch = epoch;
    busy = 'authorization'; error = ''; status = '正在准备官方授权页面…';
    openBlankPopup(); render();
    try {
      const path = accountId ? `/provider-accounts/${idPath(accountId)}/reauthorize` : '/provider-accounts/authorize';
      const body = accountId ? { expectedVersion: account.version, returnPath } : { provider: 'libtv', returnPath };
      if (authorizationProfile === 'creator') body.authorizationProfile = 'creator';
      const begin = async () => {
        // A browser lock plus the shared non-secret attempt marker prevents parallel tabs
        // from starting another attempt while the first tab's POST is in flight.
        let persisted;
        try { persisted = JSON.parse(win.localStorage.getItem(storageKey) || 'null')?.attempt; } catch { /* Optional storage. */ }
        if (persisted?.attemptId && persisted.siteSessionId === snapshot?.session?.id && activeAttempt(persisted)) {
          attempt = persisted; throw fail('AUTHORIZATION_IN_PROGRESS');
        }
        const value = await request(path, { method: 'POST', body, idempotencyKey: freshKey() });
        if (!disposed && localEpoch === epoch && typeof value?.attemptId === 'string' && Number.isFinite(Date.parse(value.expiresAt))) {
          attempt = { attemptId: value.attemptId, expiresAt: value.expiresAt, status: 'pending', accountId, paused: false, siteSessionId: snapshot.session.id };
          if (!saveLocal(true)) throw fail('AUTHORIZATION_IN_PROGRESS');
        }
        return value;
      };
      const result = win.navigator.locks ? await win.navigator.locks.request(`${storageKey}:authorize`, { ifAvailable: true }, lock => {
        if (!lock) throw fail('AUTHORIZATION_IN_PROGRESS');
        return begin();
      }) : await begin();
      if (disposed || localEpoch !== epoch) return;
      if (typeof result?.attemptId !== 'string' || !Number.isFinite(Date.parse(result.expiresAt))) throw fail('INVALID_RESPONSE');
      attempt = { attemptId: result.attemptId, expiresAt: result.expiresAt, status: 'pending', accountId, paused: false, siteSessionId: snapshot.session.id };
      if (!saveLocal(true)) throw fail('AUTHORIZATION_IN_PROGRESS');
      authorizationUrl = officialAuthorizationUrl(result.authorizationUrl);
      if (activeAttempt(attempt)) {
        try { if (popup && !popup.closed) popup.location.replace(authorizationUrl); } catch { closePopup(); }
        status = popup ? '官方授权页面已打开；完成登录后回到这里。' : '浏览器未打开新窗口。请点击“前往官方授权”。';
        schedulePoll(0);
      } else { closePopup(); status = ''; }
    } catch (err) { if (!disposed && localEpoch === epoch) { closePopup(); error = errorText(err); status = ''; if (attempt && err.code !== 'AUTHORIZATION_IN_PROGRESS') { attempt.paused = true; saveLocal(true); } else schedulePoll(0); } }
    finally { if (!disposed && localEpoch === epoch) { busy = null; render(); if (attempt) refs['attempt-title'].focus(); } }
  }

  function schedulePoll(delay = pollInterval) {
    clearTimeout(timer);
    if (!disposed && attempt && !attempt.paused && activeAttempt(attempt)) timer = setTimeout(() => void poll(), Math.max(0, delay));
  }

  async function poll(manual = false) {
    if (disposed || polling || busy || attempt?.status !== 'pending') { render(); return; }
    if (attempt.paused && !manual) return;
    const localEpoch = epoch, id = attempt.attemptId;
    if (manual) { attempt.paused = false; attempt.pollError = ''; if (!saveLocal(true)) { render(); return; } }
    polling = true; render();
    try {
      const result = await request(`/authorization-attempts/${idPath(id)}`);
      if (disposed || localEpoch !== epoch || attempt?.attemptId !== id) return;
      if (!['pending', 'completed', 'failed', 'expired'].includes(result?.status)) throw fail('INVALID_RESPONSE');
      if (result.status === 'completed' && typeof result.providerAccountId !== 'string') throw fail('INVALID_RESPONSE');
      attempt = { ...attempt, status: result.status, error: publicAttemptError(result.error), pollError: '' };
      if (result.status !== 'pending') {
        authorizationUrl = null; closePopup(); if (!saveLocal(true)) return;
        if (result.status === 'completed') {
          status = 'LibTV 已返回授权完成，正在核对账号状态…'; await refresh();
          if (!disposed && localEpoch === epoch && !error) {
            if (localClient && accounts.some(a => a.id === result.providerAccountId && accountState(a) === 'connected')) {
              draft = { providerAccountId: result.providerAccountId,
                spaceId: selection().providerAccountId === result.providerAccountId ? selection().spaceId : null };
              dirty = !sameSelection(draft, selection()); saveLocal();
              await loadSpaces();
            }
            status = localClient ? (spacesError ? 'LibTV 账号已连接，空间暂未读到，请刷新状态重试。' : 'LibTV 账号已连接。请在下方选择要使用的个人或团队空间。') : '官方授权已完成。请选择账号与工作空间，再应用到新任务。';
          }
        }
        else status = '';
      }
    } catch (err) { if (!disposed && localEpoch === epoch && attempt?.attemptId === id) attempt.pollError = `${errorText(err)} 授权结果尚未确认，可手动检查。`; }
    finally {
      if (!disposed && localEpoch === epoch) { polling = false; render(); schedulePoll(attempt?.pollError ? Math.max(15000, pollInterval) : pollInterval); }
    }
  }

  function showRemove(accountId, trigger) {
    if (blocked()) return;
    removal = accounts.find(a => a.id === accountId);
    if (!removal) return;
    restoreFocus = trigger; text('remove-name', accountName(removal)); refs['remove-dialog'].showModal();
  }
  function closeRemove() {
    if (refs['remove-dialog'].open) refs['remove-dialog'].close();
    removal = null; restoreFocus?.focus(); restoreFocus = null;
  }
  async function removeAccount() {
    if (blocked() || !removal) return;
    const account = removal, localEpoch = epoch;
    busy = 'remove'; error = ''; buttons['confirm-remove'].disabled = true; buttons['keep-account'].disabled = true; render();
    try {
      const result = await request(`/provider-accounts/${idPath(account.id)}`, { method: 'DELETE', body: { expectedVersion: account.version } });
      if (disposed || localEpoch !== epoch) return;
      if (result?.removed !== true) throw fail('INVALID_RESPONSE');
      closeRemove();
      status = `已从本站移除 ${accountName(account)}。${result.remoteRevocation === 'confirmed' ? '官方已确认撤销授权。' : '官方侧撤销尚未确认，可在 LibTV 管理授权。'}历史项目、文件和任务归属已保留。`;
      if (draft.providerAccountId === account.id) { dirty = false; draft = { providerAccountId: null, spaceId: null }; saveLocal(); }
      await refresh();
      if (disposed || localEpoch !== epoch) return;
      emit('tasks:changed', { reason: 'provider-account-removed', providerAccountId: account.id });
    } catch (err) { if (!disposed && localEpoch === epoch) { closeRemove(); if (err.code === 'VERSION_CONFLICT') await refresh(); if (!disposed && localEpoch === epoch) error = errorText(err); } }
    finally { if (!disposed && localEpoch === epoch) { busy = null; buttons['confirm-remove'].disabled = false; buttons['keep-account'].disabled = false; render(); buttons.add.focus(); } }
  }

  function onClick(event) {
    const button = event.target.closest('button[data-action]');
    if (!button || !root.contains(button) || button.disabled) return;
    const action = button.dataset.action;
    if (action === 'refresh') void refresh();
    else if (action === 'add') void beginAuthorization();
    else if (action === 'add-creator') void beginAuthorization(null, 'creator');
    else if (action === 'reauthorize') void beginAuthorization(button.dataset.id);
    else if (action === 'creator') void beginAuthorization(button.dataset.id, 'creator');
    else if (action === 'choose') void chooseAccount(button.dataset.id).then(() => { if (!disposed && document.activeElement === button) refs.space.focus(); });
    else if (action === 'quota') void loadQuota();
    else if (action === 'check') void poll(true);
    else if (action === 'pause' && attempt) { attempt.paused = true; clearTimeout(timer); closePopup(); saveLocal(true); status = '已取消等待。官方授权是否完成仍需查询确认。'; render(); buttons.check.focus(); }
    else if (action === 'dismiss-attempt') { attempt = null; authorizationUrl = null; saveLocal(true); render(); buttons.add.focus(); }
    else if (action === 'remove') showRemove(button.dataset.id, button);
    else if (action === 'keep-account') closeRemove();
    else if (action === 'confirm-remove') void removeAccount();
  }
  function onChange(event) {
    if (event.target === refs.identity) void chooseAccount(refs.identity.value);
    else if (event.target === refs.space && !blocked()) {
      draft = { ...draft, spaceId: refs.space.value || null }; dirty = !sameSelection(draft, selection()); saveLocal(); error = ''; void loadQuota();
    }
  }
  function onSubmit(event) { if (event.target === refs.form) { event.preventDefault(); void applySelection(); } }
  function onSession(event) {
    if (disposed || event.detail?.source === source) return;
    const next = event.detail?.session;
    if (!next) return;
    try { acceptSession(next); void refresh({ rereadSession: false }); } catch (err) { setError(errorText(err)); }
  }
  function onSelection(event) {
    if (disposed || event.detail?.source === source || !validSelection(event.detail?.selection)) return;
    const next = event.detail.selection;
    if (next.revision < selection().revision) return;
    snapshot = { ...snapshot, selection: next };
    if (!dirty) { draft = { ...next }; void loadSpaces(); }
    else { status = '当前选择已在别处更新；你尚未应用的选择已保留。'; render(); }
  }
  function onAccounts(event) { if (event.detail?.source !== source) void refresh(); }
  function onFocus() { if (attempt?.status === 'pending' && !attempt.paused) void poll(); }
  function onStorage(event) {
    if (event.key !== storageKey || disposed) return;
    // Another tab may finish OAuth or start an attempt. Only restore attempt, never overwrite an edited form.
    const oldDraft = draft, oldDirty = dirty, previousAttempt = `${attempt?.attemptId}:${attempt?.status}`;
    restoreLocal(); draft = oldDraft; dirty = oldDirty;
    authorizationUrl = null; render();
    if (activeAttempt(attempt) && !attempt.paused) schedulePoll(0);
    else if (attempt && previousAttempt !== `${attempt.attemptId}:${attempt.status}`) void refresh();
  }
  function onDialogCancel(event) { if (busy === 'remove') event.preventDefault(); else closeRemove(); }
  root.addEventListener('click', onClick); root.addEventListener('change', onChange); root.addEventListener('submit', onSubmit);
  refs['remove-dialog'].addEventListener('cancel', onDialogCancel);
  events.addEventListener('session:changed', onSession); events.addEventListener('selection:changed', onSelection);
  events.addEventListener('provider-accounts:changed', onAccounts);
  win.addEventListener('focus', onFocus); win.addEventListener('storage', onStorage);
  ownerModule = mountWorkspaceOwner({ root: refs['owner-root'], api, events, session, publicBasePath: returnPath,
    hooks: workspaceRecovery, pollInterval, onStateChange: render,
    isBlocked: () => Boolean(busy || loading || activeAttempt(attempt) || dirty),
    blockedReason: () => dirty ? '账号或空间选择尚未应用。请先应用或恢复原选择，再绑定／找回工作区。' : '请先完成当前生成账号操作。' });
  render();
  const ready = refresh({ rereadSession: !session });
  return {
    ready, refresh, authorize: () => beginAuthorization(),
    hasConnectedAccount: () => accounts.some(a => accountState(a) === 'connected'),
    // The integration persists this live value even when optional localStorage fails.
    getDraftSelection: () => dirty ? {providerAccountId:draft.providerAccountId, spaceId:draft.spaceId} : null,
    getDirtyState: () => ({ dirty: dirty || Boolean(busy) || ownerModule.getDirtyState().dirty, authorizationActive:activeAttempt(attempt), ownerActive:ownerModule.isActive(), reason: busy ? '账号操作尚未完成，请稍候' : dirty ? '账号或空间选择尚未应用' : ownerModule.getDirtyState().reason }),
    flush: async () => { if (busy) throw fail('ACCOUNT_OPERATION_IN_PROGRESS'); await ownerModule.flush(); saveLocal(); },
    unmount() {
      if (disposed) return;
      saveLocal(); disposed = true; epoch++; clearTimeout(timer); closePopup(); closeRemove();
      ownerModule.unmount();
      root.removeEventListener('click', onClick); root.removeEventListener('change', onChange); root.removeEventListener('submit', onSubmit);
      events.removeEventListener('session:changed', onSession); events.removeEventListener('selection:changed', onSelection);
      events.removeEventListener('provider-accounts:changed', onAccounts); refs['remove-dialog'].removeEventListener('cancel', onDialogCancel);
      win.removeEventListener('focus', onFocus); win.removeEventListener('storage', onStorage);
      root.replaceChildren(); root.classList.remove('al-accounts');
    },
  };
}

export default mount;
