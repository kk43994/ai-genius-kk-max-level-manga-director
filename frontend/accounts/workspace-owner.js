import { timeLabel, attemptState } from './state.js';
import { ownerPurposes, ownerStatuses, ownerAuthorizationUrl, ownerStartBody, draftSummary,
  ownerConfirmBody, savedDraftReferences, publicOwnerMarker, ownerError, ownerErrorText } from './owner-state.js';

const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let count = 0;

/** Owner proof lives only on the server. This view sends intent and confirmation choices. */
export function mountWorkspaceOwner({ root, api, events, session, publicBasePath, hooks = {},
  isBlocked = () => false, blockedReason = () => '', onStateChange = () => {}, pollInterval = 2500 }) {
  const document = root.ownerDocument, win = document.defaultView;
  const source = `workspace-owner-${++count}-${crypto.randomUUID()}`, prefix = `al-owner-${count}`;
  let snapshot = null, marker = null, intent = null, authorizationUrl = null, popup = null;
  let busy = false, polling = false, disposed = false, syncing = false, syncFailed = false, epoch = 0, timer = null;
  let error = '', message = '', workspaceId = '', acknowledged = false, savedDrafts = [];
  let drafts = draftSummary(null), optionsSignature = '', labelEdited = false, storageKey = null, initialDirty = false;
  let expectedResult = null, previousSession = null;
  let sessionRequired = false, bootstrapPending = false;
  const request = (path, options) => api.request(path, options);
  const emit = (name, detail) => events.dispatchEvent(new win.CustomEvent(name, { detail: { ...detail, source } }));
  const workspace = () => snapshot?.workspace;
  const sessionId = () => snapshot?.session?.id;
  const ready = () => hooks.enabled === true && typeof hooks.inspectDrafts === 'function'
    && typeof hooks.beforeSessionRotation === 'function' && typeof hooks.onSessionRotated === 'function'
    && !sessionRequired && Boolean(sessionId() && typeof workspace()?.id === 'string' && workspace().id === snapshot?.tenant?.id);
  const phase = () => {
    const state = !intent && marker?.status === 'awaiting_confirmation' ? 'pending' : intent?.status || marker?.status;
    if (['pending', 'awaiting_confirmation'].includes(state)) {
      const expiry = Date.parse(intent?.proofExpiresAt || intent?.expiresAt || marker?.expiresAt);
      if (Number.isFinite(expiry) && expiry <= Date.now()) return 'expired';
    }
    return state;
  };
  const active = () => busy || syncing || syncFailed || ['pending', 'awaiting_confirmation'].includes(phase());

  root.innerHTML = `<section class="al-accounts__owner" aria-labelledby="${prefix}-title">
    <div class="al-accounts__row"><h3 id="${prefix}-title">工作区主账号</h3><span data-owner="bound" class="al-accounts__badge"></span></div>
    <p data-owner="workspace" class="al-accounts__owner-name"></p>
    <p data-owner="explanation" class="al-accounts__owner-note"></p>
    <p class="al-accounts__owner-note">主账号用于找回这个网站的工作区。下面可切换的生成账号仅用于资产制作，不授予工作区所有权。</p>
    <div class="al-accounts__owner-label"><label for="${prefix}-label">当前工作区名称</label><input id="${prefix}-label" data-owner="label" maxlength="120" value="我的工作区" autocomplete="off"></div>
    <div class="al-accounts__actions"><button type="button" data-owner-action="bind" class="al-accounts__button">绑定主账号</button><button type="button" data-owner-action="recover" class="al-accounts__button">找回工作区</button><button type="button" data-owner-action="refresh" class="al-accounts__button al-accounts__button--quiet">检查工作区状态</button></div>
    <p data-owner="availability" class="al-accounts__field-note"></p>
    <div data-owner="bootstrap-note" hidden><p class="al-accounts__owner-note">会话已失效或尚未建立。先建立新的临时会话，再用以前绑定的主账号查找原工作区；当前页面未保存输入会保留到确认步骤。</p><button type="button" data-owner-action="bootstrap" class="al-accounts__button">建立临时会话并继续找回</button></div>
    <p data-owner="message" class="al-accounts__status" role="status" aria-live="polite" aria-atomic="true"></p>
    <p data-owner="error" class="al-accounts__error" role="alert" hidden></p>
    <section data-owner="attempt" class="al-accounts__owner-attempt" hidden aria-labelledby="${prefix}-attempt">
      <h4 id="${prefix}-attempt" data-owner="attempt-title" tabindex="-1"></h4><p data-owner="attempt-note" class="al-accounts__owner-note"></p>
      <div class="al-accounts__actions"><a data-owner="official" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" class="al-accounts__button" hidden>前往官方验证主账号 ↗</a><button type="button" data-owner-action="check" class="al-accounts__button">检查验证结果</button><button type="button" data-owner-action="cancel" class="al-accounts__button al-accounts__button--quiet">取消，留在当前工作区</button><button type="button" data-owner-action="sync" class="al-accounts__button" hidden>重新同步工作区</button><button type="button" data-owner-action="dismiss" class="al-accounts__button al-accounts__button--quiet" hidden>收起</button></div>
      <form data-owner="confirmation" class="al-accounts__owner-confirmation" hidden>
        <p data-owner="source" class="al-accounts__owner-source"></p>
        <div data-owner="choice"><label for="${prefix}-candidate">找到的原工作区</label><select id="${prefix}-candidate" data-owner="candidate"><option value="">请选择要进入的工作区</option></select></div>
        <p data-owner="bind-candidates" class="al-accounts__owner-note" hidden></p>
        <div class="al-accounts__owner-drafts"><h4>当前未保存内容</h4><p data-owner="draft-status"></p><ul data-owner="draft-list"></ul><div class="al-accounts__actions"><button type="button" data-owner-action="inspect" class="al-accounts__button al-accounts__button--quiet">重新检查未保存内容</button><button type="button" data-owner-action="save" class="al-accounts__button">保存当前未保存内容</button></div></div>
        <label class="al-accounts__owner-ack" for="${prefix}-ack"><input id="${prefix}-ack" type="checkbox" data-owner="ack"><span data-owner="ack-label"></span></label>
        <p class="al-accounts__field-note">当前与原工作区保持独立，不合并项目、素材或任务归属。主账号验证不会添加生成账号，也不表示已获得生成权限。</p>
        <button type="submit" data-owner-action="confirm" class="al-accounts__button al-accounts__button--primary">确认保留当前工作区并找回</button>
      </form>
    </section>
  </section>`;
  const refs = Object.fromEntries([...root.querySelectorAll('[data-owner]')].map(el => [el.dataset.owner, el]));
  const buttons = Object.fromEntries([...root.querySelectorAll('[data-owner-action]')].map(el => [el.dataset.ownerAction, el]));
  const text = (key, value) => { if (refs[key].textContent !== value) refs[key].textContent = value; };

  function closePopup() { try { popup?.close(); } catch { /* Official window may have detached. */ } popup = null; }
  function persist() {
    if (!storageKey) return;
    try {
      const existing = publicOwnerMarker(JSON.parse(win.localStorage.getItem(storageKey) || 'null'));
      if (!marker && existing?.sourceSessionId === sessionId() && ['pending', 'awaiting_confirmation'].includes(existing.status)
          && Date.parse(existing.expiresAt) > Date.now()) return;
      if (marker) win.localStorage.setItem(storageKey, JSON.stringify(publicOwnerMarker(marker)));
      else win.localStorage.removeItem(storageKey);
    } catch { /* Only a resumption hint; server remains authoritative. */ }
  }
  function clearOwnMarker() {
    if (!storageKey) return;
    try {
      const stored = publicOwnerMarker(JSON.parse(win.localStorage.getItem(storageKey) || 'null'));
      if (!stored || stored.intentId === marker?.intentId) win.localStorage.removeItem(storageKey);
    } catch { /* No global localStorage clearing. */ }
  }
  function render(notify = true) {
    if (disposed) return;
    const state = phase(), bound = workspace()?.ownerBound === true;
    text('bound', bound ? '已绑定' : '尚未绑定'); refs.bound.dataset.state = bound ? 'connected' : 'unconfigured';
    text('workspace', workspace()?.label || '当前临时工作区');
    text('explanation', bound ? `已绑定经过官方验证的 LibTV 主账号${workspace().boundAt ? ` · ${timeLabel(workspace().boundAt)}` : ''}。换浏览器或会话失效后，请用这个主账号找回。`
      : '当前工作区依赖这个浏览器的临时会话。请在清除 Cookie 或会话到期前绑定主账号；从未绑定且会话已丢失时，无法安全自动找回。');
    text('availability', !ready() ? '工作区账号授权暂未开放。请暂时保留当前浏览器会话；开放后可绑定账号并找回工作区。' : isBlocked() ? blockedReason() || '请先完成当前账号操作。' : '每次绑定或找回都会重新验证官方主账号身份；只申请读取身份的权限。');
    buttons.bind.disabled = !ready() || bound || active() || isBlocked();
    buttons.bind.textContent = bound ? '主账号已绑定' : '绑定主账号';
    buttons.recover.disabled = !ready() || active() || isBlocked();
    buttons.refresh.disabled = busy || polling || syncing || !sessionId();
    refs['bootstrap-note'].hidden = Boolean(sessionId() && !sessionRequired);
    buttons.bootstrap.disabled = busy || syncing || hooks.enabled !== true || typeof hooks.bootstrapSession !== 'function' || typeof hooks.onSessionRotated !== 'function';
    refs.label.disabled = active() || bound;
    refs.label.parentElement.hidden = bound;
    const visibleError = error || (marker?.authorizationRejected ? ownerErrorText({ code: 'OWNER_READ_ONLY_REQUIRED' }) : '');
    text('message', message); refs.error.hidden = !visibleError; text('error', visibleError);
    refs.attempt.hidden = !marker && !intent && !syncFailed;
    const titles = { pending: '等待官方验证工作区主账号', awaiting_confirmation: '官方身份已验证，请确认工作区',
      bound: '工作区主账号已绑定', recovered: '原工作区已找回', blocked: '主账号不匹配，保持当前工作区',
      not_found: '没有找到已绑定的工作区', cancelled: '已取消，继续使用当前工作区', expired: '这次身份确认已过期', failed: '本次主账号验证未完成' };
    text('attempt-title', syncFailed ? '工作区会话已变化，页面等待同步' : syncing ? '正在同步工作区会话' : titles[state] || '工作区状态已更新');
    const notes = { pending: '请在官方页面使用工作区主账号完成验证，返回后仍需确认。关闭官方页面不会自动找回。',
      awaiting_confirmation: '尚未切换。先核对原工作区与当前编辑内容，再决定保留并继续，或取消。',
      bound: '今后可使用这次验证的 LibTV 主账号找回当前工作区。生成账号状态单独管理。',
      recovered: '已进入选定工作区，原工作区及已保存内容已保留。请在下方检查生成账号的授权状态。',
      blocked: ownerErrorText(intent?.error || { code: 'WORKSPACE_OWNER_MISMATCH' }),
      not_found: ownerErrorText({ code: 'OWNER_WORKSPACE_NOT_FOUND' }),
      cancelled: '当前工作区及页面输入保留。需要时可重新发起官方身份验证。',
      expired: '请重新发起官方验证；本页不会继续提交过期的确认。', failed: ownerErrorText(intent?.error) };
    text('attempt-note', notes[state] || '已重新读取当前工作区，请核对后继续。');
    refs.official.hidden = !authorizationUrl || state !== 'pending' || syncing || syncFailed;
    if (!refs.official.hidden) refs.official.href = authorizationUrl; else refs.official.removeAttribute('href');
    buttons.check.hidden = !['pending', 'awaiting_confirmation'].includes(state) || syncFailed;
    buttons.check.disabled = busy || polling || syncing || marker?.authorizationRejected;
    buttons.cancel.hidden = !['pending', 'awaiting_confirmation'].includes(state) || syncFailed;
    buttons.cancel.disabled = busy || polling || syncing;
    buttons.sync.hidden = !syncFailed; buttons.sync.disabled = syncing;
    buttons.dismiss.hidden = !state || active();
    refs.confirmation.hidden = state !== 'awaiting_confirmation' || syncing || syncFailed;
    if (!refs.confirmation.hidden) {
      const sourceWorkspace = intent.sourceWorkspace;
      text('source', `当前工作区：${sourceWorkspace?.label || '当前工作区'}${sourceWorkspace?.content?.hasContent ? '（已有项目、素材或账号记录）' : '（尚无已保存内容）'}。确认后会保留这个工作区。`);
      const recovering = marker.purpose === 'recover_workspace';
      refs.choice.hidden = !recovering; refs['bind-candidates'].hidden = recovering;
      const candidates = intent.candidates || [];
      const options = '<option value="">请选择要进入的工作区</option>' + candidates.map(c => `<option value="${escape(c.id)}">${escape(c.label || '已绑定工作区')} · ${escape(c.id.slice(-8))}${c.id === workspace()?.id ? '（当前）' : ''}</option>`).join('');
      if (options !== optionsSignature) { refs.candidate.innerHTML = options; optionsSignature = options; }
      refs.candidate.value = workspaceId; refs.candidate.disabled = busy;
      text('bind-candidates', candidates.length ? `此主账号已有工作区：${candidates.map(c => c.label || '已绑定工作区').join('、')}。这次只绑定当前工作区；进入原工作区请取消后选择“找回工作区”。` : '这次将主账号绑定到当前工作区。');
      text('draft-status', drafts.hasUnsavedChanges === true ? '以下编辑内容仍需保存到当前工作区。' : drafts.hasUnsavedChanges === false ? savedDrafts.length ? '当前编辑内容已保存到这个工作区。' : '已检查：当前没有未保存的编辑内容。' : '未保存状态尚未核实，确认暂不可用。');
      refs['draft-list'].innerHTML = drafts.items.map(item => `<li>${escape(item.label)}</li>`).join('');
      buttons.inspect.disabled = busy || polling || typeof hooks.inspectDrafts !== 'function';
      buttons.save.disabled = busy || polling || !ready() || typeof hooks.saveDrafts !== 'function' || (drafts.hasUnsavedChanges === false && (!initialDirty || savedDrafts.length));
      refs.ack.checked = acknowledged; refs.ack.disabled = busy || drafts.hasUnsavedChanges !== false;
      text('ack-label', recovering ? '我已核对：保留当前工作区及已保存内容，并进入上面选定的原工作区。' : '我已核对当前内容，并确认将这个工作区绑定到刚刚验证的主账号。');
      buttons.confirm.textContent = recovering ? '确认保留当前工作区并找回' : '确认绑定当前工作区';
      let valid = true;
      try { ownerConfirmBody({ intent, workspaceId, drafts, savedDrafts, initiallyDirty: initialDirty, acknowledged }); } catch { valid = false; }
      buttons.confirm.disabled = busy || polling || !ready() || !valid;
    }
    if (notify) onStateChange();
  }

  async function inspect() {
    const token = epoch;
    try {
      if (typeof hooks.inspectDrafts !== 'function') throw ownerError('DRAFT_INSPECTION_UNAVAILABLE');
      const value = await hooks.inspectDrafts();
      if (!disposed && token === epoch) drafts = draftSummary(value);
    } catch { if (!disposed && token === epoch) drafts = draftSummary(null); }
    render(); return drafts;
  }

  function setSession(next) {
    if (disposed || !next?.session?.id || !next?.tenant?.id) return;
    const changed = snapshot && next.session.id !== sessionId();
    if (changed) {
      epoch++; clearTimeout(timer); closePopup(); clearOwnMarker(); marker = null; intent = null;
      savedDrafts = []; workspaceId = ''; acknowledged = false; initialDirty = false; authorizationUrl = null; labelEdited = false;
      busy = false; polling = false;
    }
    snapshot = { ...next, session: { ...next.session }, tenant: { ...next.tenant } };
    sessionRequired = false;
    storageKey = `asset-lab:workspace-owner:v1:${publicBasePath}:${next.tenant.id}`;
    if (!labelEdited) refs.label.value = next.workspace?.ownerBound ? next.workspace.label : '我的工作区';
    if (!marker) {
      try {
        const stored = publicOwnerMarker(JSON.parse(win.localStorage.getItem(storageKey) || 'null'));
        if (stored?.sourceSessionId === next.session.id) { marker = stored; initialDirty = stored.initiallyDirty; }
        else if (stored) win.localStorage.removeItem(storageKey);
      } catch { /* No ownership decision comes from storage. */ }
    }
    render();
    if (marker && ['pending', 'awaiting_confirmation'].includes(phase())) schedule(0);
  }

  async function synchronize(result = null, fresh = null) {
    if (disposed || syncing) return;
    syncing = true; syncFailed = false; clearTimeout(timer); authorizationUrl = null; closePopup();
    expectedResult = result || expectedResult; previousSession ||= snapshot;
    render();
    try {
      const next = fresh || await request('/session');
      if (!next?.session?.id || !next?.tenant?.id || !next.workspace) throw ownerError('INVALID_OWNER_RESPONSE');
      api.setCsrfToken?.(next.csrfToken);
      const proven = expectedResult && ['bound', 'recovered'].includes(expectedResult.status)
        && next.session.id !== previousSession?.session?.id && next.workspace.id === expectedResult.workspaceId
        && next.workspace.ownerBound === true;
      clearOwnMarker(); setSession(next);
      // The integration callback must retire every old module context before remounting.
      if (typeof hooks.onSessionRotated !== 'function') throw ownerError('WORKSPACE_SYNC_FAILED');
      await hooks.onSessionRotated({ session: next, previousSession, result: proven ? expectedResult : null,
        ...(!proven || bootstrapPending ? { reason: bootstrapPending ? 'anonymous-session-bootstrap' : 'external-session-change', preserveUnsavedInputs: true } : {}) });
      if (disposed) return;
      emit('session:changed', { session: next });
      emit('workspace:changed', { workspace: next.workspace, session: next, previousTenantId: previousSession?.tenant?.id });
      emit('selection:changed', { selection: next.selection });
      emit('provider-accounts:changed', { reason: 'workspace-session-rotated' });
      emit('tasks:changed', { reason: 'workspace-session-rotated' });
      intent = proven ? { ...expectedResult } : null;
      message = proven ? expectedResult.status === 'bound' ? '主账号绑定完成，以后可用它找回这个工作区。' : '原工作区已找回，当前工作区已保留。' : '当前工作区已更新。请核对工作区名称后继续。';
      expectedResult = null; previousSession = null; bootstrapPending = false; error = '';
    } catch (err) { if (!disposed) { syncFailed = true; error = ownerErrorText({ code: 'WORKSPACE_SYNC_FAILED' }); } }
    finally { if (!disposed) { syncing = false; busy = false; render(); } }
  }

  async function readFreshSession() {
    let next;
    try { next = await request('/session'); }
    catch (err) { if (err.code === 'SESSION_REQUIRED') { sessionRequired = true; clearTimeout(timer); } throw err; }
    if (!next?.session?.id || !next?.tenant?.id) throw ownerError('INVALID_OWNER_RESPONSE');
    api.setCsrfToken?.(next.csrfToken);
    if (sessionId() && next.session.id !== sessionId()) { await synchronize(null, next); return false; }
    snapshot = { ...next }; return true;
  }
  async function readIntent() {
    const token = epoch, id = marker?.intentId;
    if (!id) return;
    const value = await request(`/workspace-intents/${encodeURIComponent(id)}`);
    if (disposed || token !== epoch || marker?.intentId !== id) return;
    if (value?.id !== id || value.purpose !== marker.purpose || !ownerStatuses.includes(value.status)) throw ownerError('INVALID_OWNER_RESPONSE');
    if (value.status === 'awaiting_confirmation' && (!Array.isArray(value.candidates)
        || value.sourceWorkspace?.id !== marker.sourceWorkspaceId
        || value.candidates.some(c => typeof c?.id !== 'string' || !c.id))) throw ownerError('INVALID_OWNER_RESPONSE');
    if (value.status !== 'pending' && intent?.status !== value.status) message = '';
    intent = value; marker.status = value.status; persist();
    if (!value.candidates?.some(c => c.id === workspaceId)) { workspaceId = ''; acknowledged = false; }
    if (value.status === 'awaiting_confirmation') { authorizationUrl = null; closePopup(); await inspect(); }
    if (['bound', 'recovered'].includes(value.status)) await synchronize(value);
  }
  function schedule(delay = pollInterval) {
    clearTimeout(timer);
    if (!disposed && !busy && !syncing && !syncFailed && !sessionRequired && !marker?.authorizationRejected && ['pending', 'awaiting_confirmation'].includes(phase())) timer = setTimeout(() => void poll(), delay);
  }
  async function poll() {
    if (disposed || polling || busy || syncing || syncFailed || !marker || marker.authorizationRejected) return;
    const token = epoch;
    polling = true; render();
    try {
      if (!await readFreshSession() || disposed || token !== epoch) return;
      await readIntent();
      if (disposed || token !== epoch || !marker) return;
      if (intent?.status === 'pending') {
        const value = await request(`/authorization-attempts/${encodeURIComponent(marker.attemptId)}`);
        if (disposed || token !== epoch) return;
        if (['failed', 'expired'].includes(value?.status)) {
          intent = { ...intent, status: attemptState(value) === 'cancelled' ? 'cancelled' : value.status, error: { code: value.error?.code } };
          marker.status = intent.status; persist(); closePopup(); authorizationUrl = null;
        }
        // OAuth completed is only identity verification; the workspace intent must decide recovery.
      }
      error = '';
    } catch (err) { if (!disposed && token === epoch) error = ownerErrorText(err); }
    finally { polling = false; if (!disposed && token === epoch) { render(); schedule(error ? 15000 : phase() === 'awaiting_confirmation' ? Math.max(pollInterval, 15000) : pollInterval); } }
  }

  async function begin(purpose) {
    if (!ready() || active() || isBlocked() || (purpose === 'bind_owner' && workspace()?.ownerBound)) return;
    const token = epoch; busy = true; error = ''; message = ''; render();
    try { popup = win.open('about:blank', '_blank', 'popup,width=560,height=760'); if (popup) { popup.opener = null; popup.document.body.textContent = '正在准备官方主账号验证…'; } } catch { popup = null; }
    try {
      const checked = await inspect();
      if (disposed || token !== epoch) return;
      if (!await readFreshSession() || disposed || token !== epoch) return;
      const body = ownerStartBody({ purpose, label: refs.label.value, drafts: checked, publicBasePath });
      const start = async () => {
        let existing;
        try { existing = publicOwnerMarker(JSON.parse(win.localStorage.getItem(storageKey) || 'null')); } catch { /* Optional storage. */ }
        if (existing?.sourceSessionId === sessionId() && ['pending', 'awaiting_confirmation'].includes(existing.status)
            && Date.parse(existing.expiresAt) > Date.now()) throw ownerError('WORKSPACE_AUTHORIZATION_BUSY');
        const value = await request('/provider-accounts/authorize', { method: 'POST', body, idempotencyKey: crypto.randomUUID() });
        if (disposed || token !== epoch) return null;
        const next = publicOwnerMarker({ purpose, attemptId: value?.attemptId, intentId: value?.workspaceIntent?.intentId,
          expiresAt: value?.workspaceIntent?.expiresAt, sourceSessionId: sessionId(), sourceWorkspaceId: workspace().id,
          status: 'pending', initiallyDirty: body.hasUnsavedChanges === true });
        if (!next || value.workspaceIntent.purpose !== purpose) throw ownerError('INVALID_OWNER_RESPONSE');
        marker = next; intent = null; initialDirty = next.initiallyDirty; savedDrafts = []; acknowledged = false; workspaceId = ''; persist();
        return value;
      };
      const value = win.navigator.locks ? await win.navigator.locks.request(`${storageKey}:authorize`, { ifAvailable: true }, lock => {
        if (!lock) throw ownerError('WORKSPACE_AUTHORIZATION_BUSY'); return start();
      }) : await start();
      if (disposed || token !== epoch || !value) return;
      authorizationUrl = ownerAuthorizationUrl(value.authorizationUrl);
      try { if (popup && !popup.closed) popup.location.replace(authorizationUrl); } catch { closePopup(); }
      message = popup ? '官方主账号验证页面已打开。完成后请回到这里确认工作区。' : '请点击“前往官方验证主账号”继续；本站不会要求复制 token。';
    } catch (err) {
      if (!disposed && token === epoch) {
        if (marker && ['OWNER_READ_ONLY_REQUIRED', 'INVALID_AUTHORIZATION_URL'].includes(err.code || err.message)) { marker.authorizationRejected = true; persist(); }
        error = ownerErrorText(err); closePopup();
      }
    }
    finally { if (!disposed && token === epoch) { busy = false; render(); if (marker) refs['attempt-title'].focus(); schedule(0); } }
  }

  async function save() {
    if (busy || polling || !ready() || phase() !== 'awaiting_confirmation' || typeof hooks.saveDrafts !== 'function') return;
    const token = epoch; busy = true; acknowledged = false; error = ''; render();
    try {
      if (!await readFreshSession() || token !== epoch) return;
      const result = await hooks.saveDrafts({ purpose: marker.purpose, intentId: marker.intentId, sourceWorkspaceId: marker.sourceWorkspaceId });
      if (disposed || token !== epoch) return;
      savedDrafts = savedDraftReferences(result?.savedDrafts);
      await inspect();
      if (drafts.hasUnsavedChanges !== false) throw ownerError('DRAFT_SAVE_REQUIRED');
      await readIntent(); message = '当前未保存内容已保存。请核对工作区后重新勾选确认。';
    } catch (err) { if (!disposed && token === epoch) { savedDrafts = []; error = ownerErrorText(err); } }
    finally { if (!disposed && token === epoch) { busy = false; render(); } }
  }

  async function confirm() {
    if (busy || polling || !ready() || syncing || syncFailed || phase() !== 'awaiting_confirmation' || !acknowledged) return;
    const token = epoch; let resume;
    busy = true; error = ''; render();
    try {
      if (!await readFreshSession() || token !== epoch) return;
      await inspect();
      ownerConfirmBody({ intent, workspaceId, drafts, savedDrafts, initiallyDirty: initialDirty, acknowledged });
      // Hook may quiesce other module requests; it must not reset source inputs.
      resume = await hooks.beforeSessionRotation({ purpose: marker.purpose, sourceWorkspaceId: marker.sourceWorkspaceId });
      if (disposed || token !== epoch) return;
      await inspect();
      const body = ownerConfirmBody({ intent, workspaceId, drafts, savedDrafts, initiallyDirty: initialDirty, acknowledged });
      const result = await request(`/workspace-intents/${encodeURIComponent(marker.intentId)}/confirm`, { method: 'POST', body });
      if (disposed || token !== epoch) return;
      if (result?.status !== (marker.purpose === 'bind_owner' ? 'bound' : 'recovered') || result.purpose !== marker.purpose || result.id !== marker.intentId
          || result.workspaceId !== (marker.purpose === 'bind_owner' ? marker.sourceWorkspaceId : workspaceId)
          || (marker.purpose === 'recover_workspace' && result.sourceWorkspacePreserved !== true)) throw ownerError('INVALID_OWNER_RESPONSE');
      expectedResult = result;
      await synchronize(result);
    } catch (err) {
      if (disposed || token !== epoch) return;
      acknowledged = false; error = ownerErrorText(err);
      try {
        // A lost response may still have rotated cookies. Re-read session before any old-intent request.
        if (await readFreshSession() && token === epoch) await readIntent();
      } catch { /* Preserve original failure and input; never retry confirmation. */ }
    } finally { if (!disposed && token === epoch) { if (typeof resume === 'function' && !syncFailed) await resume(); busy = false; render(); } }
  }

  async function bootstrap() {
    if (busy || syncing || typeof hooks.bootstrapSession !== 'function' || typeof hooks.onSessionRotated !== 'function') return;
    busy = true; error = ''; const before = snapshot; let sessionCreated = false; render();
    try {
      // The HTTP/session adapter owns expired-cookie handling. There is no invented reset endpoint here.
      const next = await hooks.bootstrapSession({ preserveUnsavedInputs: true });
      if (!next?.session?.id || !next?.tenant?.id || !next.workspace) throw ownerError('INVALID_OWNER_RESPONSE');
      api.setCsrfToken?.(next.csrfToken); clearOwnMarker(); setSession(next); busy = true; sessionCreated = true;
      previousSession = before; bootstrapPending = true;
      await hooks.onSessionRotated({ session: next, previousSession: before, result: null,
        reason: 'anonymous-session-bootstrap', preserveUnsavedInputs: true });
      if (disposed) return;
      emit('session:changed', { session: next });
      emit('workspace:changed', { session: next, workspace: next.workspace, preserveUnsavedInputs: true });
      previousSession = null; bootstrapPending = false;
      message = '临时会话已建立。请选择“找回工作区”，使用以前绑定的主账号重新验证。';
    } catch (err) { if (!disposed) { syncFailed = sessionCreated; error = ownerErrorText(sessionCreated ? { code: 'WORKSPACE_SYNC_FAILED' } : err); } }
    finally { if (!disposed) { busy = false; render(); } }
  }

  async function cancel() {
    if (busy || polling || syncing || !marker || !['pending', 'awaiting_confirmation'].includes(phase())) return;
    const token = epoch; busy = true; error = ''; render();
    try {
      if (!await readFreshSession() || token !== epoch) return;
      await request(`/authorization-attempts/${encodeURIComponent(marker.attemptId)}/cancel`, { method: 'POST', body: {} });
      if (disposed || token !== epoch) return;
      // Completed identity verification leaves the confirmation intent open; explicitly cancel it too.
      const result = await request(`/workspace-intents/${encodeURIComponent(marker.intentId)}/cancel`, { method: 'POST', body: {} });
      if (disposed || token !== epoch) return;
      if (result.status !== 'cancelled') throw ownerError('WORKSPACE_CONFIRMATION_UNAVAILABLE');
      intent = result; marker.status = 'cancelled'; persist(); acknowledged = false;
      clearTimeout(timer); closePopup(); authorizationUrl = null; message = '已取消工作区找回／绑定，当前工作及输入保留。';
    } catch (err) {
      if (!disposed && token === epoch) {
        error = ownerErrorText(err);
        try { if (await readFreshSession() && token === epoch) await readIntent(); } catch { /* Not a cancellation success. */ }
      }
    } finally { if (!disposed && token === epoch) { busy = false; render(); } }
  }
  async function refresh() {
    if (busy || polling || syncing) return;
    if (syncFailed) return synchronize();
    if (marker && ['pending', 'awaiting_confirmation'].includes(phase())) return poll();
    const token = epoch; busy = true; render();
    try {
      if (!await readFreshSession() || disposed || token !== epoch) return;
      const value = await request('/workspace');
      if (!disposed && token === epoch) { snapshot = { ...snapshot, workspace: value }; error = ''; }
    } catch (err) { if (!disposed && token === epoch) error = ownerErrorText(err); }
    finally { if (!disposed && token === epoch) { busy = false; render(); } }
  }
  function onClick(event) {
    const button = event.target.closest('[data-owner-action]');
    if (!button || !root.contains(button) || button.disabled) return;
    const action = button.dataset.ownerAction;
    if (action === 'bind') void begin('bind_owner');
    else if (action === 'recover') void begin('recover_workspace');
    else if (action === 'refresh') void refresh();
    else if (action === 'check') void poll();
    else if (action === 'cancel') void cancel();
    else if (action === 'inspect') { acknowledged = false; void inspect(); }
    else if (action === 'save') void save();
    else if (action === 'sync') void synchronize();
    else if (action === 'bootstrap') void bootstrap();
    else if (action === 'dismiss' && !active()) { clearOwnMarker(); marker = null; intent = null; error = ''; render(); }
  }
  function onChange(event) {
    if (event.target === refs.candidate) { workspaceId = refs.candidate.value; acknowledged = false; render(); }
    if (event.target === refs.ack) { acknowledged = refs.ack.checked; render(); }
  }
  function onInput(event) { if (event.target === refs.label) labelEdited = true; }
  function onSubmit(event) { if (event.target === refs.confirmation) { event.preventDefault(); void confirm(); } }
  function onFocus() { if (!busy && marker && !syncFailed) void poll(); }
  root.addEventListener('click', onClick); root.addEventListener('change', onChange); root.addEventListener('input', onInput); root.addEventListener('submit', onSubmit);
  win.addEventListener('focus', onFocus);
  setSession(session); render();
  return {
    setSession, render: () => render(false), isActive: active,
    getDirtyState: () => ({ dirty: active(), reason: active() ? '主账号验证或工作区确认尚未结束' : null }),
    flush: async () => { if (busy || syncing || syncFailed) throw ownerError('ACCOUNT_OPERATION_IN_PROGRESS'); persist(); },
    unmount() {
      disposed = true; epoch++; clearTimeout(timer); closePopup();
      root.removeEventListener('click', onClick); root.removeEventListener('change', onChange); root.removeEventListener('input', onInput); root.removeEventListener('submit', onSubmit);
      win.removeEventListener('focus', onFocus); root.replaceChildren();
    },
  };
}
