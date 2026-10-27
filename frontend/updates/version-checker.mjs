import { validateClientBuild, validateManifest, compatibility, compareVersions, trustedEntry } from './version-contract.mjs';

// The app supplies its shared api.request; no provider URLs, tokens or credentials
// are handled here. current is embedded at BUILD time, not read from a live API.
export class VersionChecker {
  constructor({ current, api, origin = globalThis.location?.origin, basePath = '/', getSafetyState, saveDraft,
    onState = () => {}, navigate = url => globalThis.location.assign(url), intervalMs = 21600000,
    timeoutMs = 8000, environment = globalThis, document = globalThis.document, random = Math.random }) {
    this.trust = { origin, basePath }; this.current = validateClientBuild(current);
    if (!api || typeof api.request !== 'function') throw new Error('Shared API client required');
    this.api = api; this.getSafetyState = getSafetyState; this.saveDraft = saveDraft;
    this.onState = onState; this.navigate = navigate; this.intervalMs = Math.max(60000, intervalMs);
    this.timeoutMs = timeoutMs; this.environment = environment; this.document = document; this.random = random;
    this.state = Object.freeze({ status: 'idle', currentVersion: this.current.version, current: this.current,
      latestVersion: null, latest: null, canUpdate: false, checkedAt: null, releaseNotes: [] });
    this.started = false; this.disposed = false; this.lastAttempt = 0; this.applying = false;
    this.onVisible = () => { if ((!this.document || this.document.visibilityState === 'visible') && Date.now() - this.lastAttempt >= this.intervalMs) void this.check(); };
    this.onOnline = () => { if (Date.now() - this.lastAttempt >= 10000) void this.check(); };
  }
  emit(patch) {
    if (this.disposed) return;
    this.state = Object.freeze({ ...this.state, ...patch });
    try { this.onState(this.state); } catch { /* Rendering failures cannot interrupt work. */ }
  }
  start() {
    if (this.started || this.disposed) return;
    this.started = true; this.environment.addEventListener?.('online', this.onOnline);
    this.document?.addEventListener('visibilitychange', this.onVisible);
    void this.check(); this.schedule();
  }
  schedule() {
    if (this.disposed || !this.started) return;
    this.timer = setTimeout(async () => {
      if (!this.document || this.document.visibilityState === 'visible') await this.check();
      this.schedule();
    }, Math.round(this.intervalMs * (1 + this.random() * 0.1)));
    this.timer.unref?.();
  }
  check() {
    if (this.disposed) return Promise.resolve(this.state);
    if (this.pending) return this.pending;
    this.pending = this.performCheck().finally(() => { this.pending = null; });
    return this.pending;
  }
  async performCheck() {
    this.lastAttempt = Date.now(); this.emit({ status: 'checking', canUpdate: false, reason: null });
    const controller = new AbortController(); this.controller = controller;
    let timer;
    try {
      const timeout = new Promise((_, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error('timeout')); }, this.timeoutMs); });
      const options = { cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' } };
      const [currentRaw, latestRaw] = await Promise.race([Promise.all([
        this.api.request('/version', options),
        this.api.request(`/releases/latest?channel=${encodeURIComponent(this.current.channel)}&_check=${Date.now()}`, options),
      ]), timeout]);
      const server = validateManifest(currentRaw, this.trust), latest = validateManifest(latestRaw, this.trust);
      if (server.channel !== this.current.channel || latest.channel !== this.current.channel) throw new Error('Wrong channel');
      const order = compareVersions(latest.version, this.current.version);
      const different = order !== 0 || latest.buildId !== this.current.buildId;
      const compatibleNow = compatibility(this.current, server);
      const compatibleLatest = compatibility(latest, server) && latest.dataSchemaVersion === server.dataSchemaVersion;
      const status = !compatibleNow || !compatibleLatest ? 'incompatible' : different ? 'update_available' : 'up_to_date';
      this.emit({ status, latest, latestVersion: latest.version, server, compatibleNow, compatibleLatest,
        canUpdate: different && compatibleLatest, changeKind: order < 0 ? 'rollback' : 'upgrade',
        checkedAt: new Date().toISOString(), releaseNotes: latest.releaseNotes, reason: null });
    } catch {
      this.emit({ status: this.environment.navigator?.onLine === false ? 'offline' : 'error', canUpdate: false,
        reason: '暂时无法检查版本；当前内容和制作进度会保留。' });
    } finally { clearTimeout(timer); if (this.controller === controller) this.controller = null; }
    return this.state;
  }
  async safety() {
    const state = await this.getSafetyState?.();
    if (!state || typeof state.hasUnsavedChanges !== 'boolean' || !Number.isSafeInteger(state.activeTasks) || state.activeTasks < 0 || (state.activeDownloads !== undefined && (!Number.isSafeInteger(state.activeDownloads) || state.activeDownloads < 0))) throw new Error('Unknown safety state');
    return state;
  }
  // Only an explicit user click calls this. Timers never save, refresh or install.
  async applyUpdate() {
    if (this.applying || this.disposed) return false;
    this.applying = true;
    try {
      await this.check();
      if (!this.state.canUpdate || this.disposed) return false;
      let state;
      try { state = await this.safety(); } catch { this.emit({ reason: '暂时无法确认保存状态，请稍后重试。' }); return false; }
      if (state.hasUnsavedChanges && this.saveDraft) {
        this.emit({ reason: '正在保存草稿，请保留当前页面…' });
        try {
          const result = await this.saveDraft();
          if (result?.saved !== true) throw new Error('Save not confirmed');
          state = await this.safety();
        } catch { this.emit({ reason: '草稿未能保存或出现版本冲突；内容已保留，请处理后重试。' }); return false; }
      }
      if (state.hasUnsavedChanges || state.activeTasks > 0 || state.activeDownloads > 0) {
        this.emit({ reason: state.hasUnsavedChanges ? '请先保存输入，再点击刷新更新。' : '请等待运行中的任务和下载完成，再刷新更新。' }); return false;
      }
      const target = new URL(trustedEntry(this.state.latest.entryUrl, this.trust));
      target.searchParams.set('_release', this.state.latest.buildId);
      if (this.disposed) return false;
      this.navigate(target.href); return true;
    } finally { this.applying = false; }
  }
  destroy() {
    this.disposed = true; this.started = false; clearTimeout(this.timer); this.controller?.abort();
    this.environment.removeEventListener?.('online', this.onOnline);
    this.document?.removeEventListener('visibilitychange', this.onVisible);
  }
}

export function mountVersionNotice(container, options) {
  const doc = container.ownerDocument;
  const box = doc.createElement('section'); box.className = 'asset-version-notice'; box.setAttribute('aria-label', '版本更新');
  const status = doc.createElement('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const versions = doc.createElement('p'), notes = doc.createElement('ul'), reason = doc.createElement('p');
  const check = doc.createElement('button'); check.type = 'button'; check.textContent = '检查更新';
  const apply = doc.createElement('button'); apply.type = 'button'; apply.textContent = '保存并刷新更新'; apply.hidden = true;
  box.append(status, versions, notes, reason, check, apply); container.append(box);
  const labels = { idle: '版本信息', checking: '正在检查版本…', update_available: '有可用版本，刷新由你决定', up_to_date: '当前已是最新版本', incompatible: '页面与服务版本不兼容，请先保存，暂勿新建生成任务', offline: '当前离线，尚未确认最新版本', error: '暂时无法检查更新' };
  const checker = new VersionChecker({ ...options, onState(state) {
    status.textContent = state.changeKind === 'rollback' && state.status === 'update_available' ? '服务已回退到可用版本，可保存后刷新' : labels[state.status];
    const stale = ['offline', 'error'].includes(state.status);
    versions.textContent = `当前 ${state.current.version} · ${state.current.buildId}` + (state.latest ? ` / ${stale ? '上次查询' : '最新'} ${state.latest.version} · ${state.latest.buildId}` : ' / 最新版本未知');
    notes.replaceChildren(...state.releaseNotes.map(text => { const li = doc.createElement('li'); li.textContent = text; return li; }));
    reason.textContent = state.reason || '刷新前会检查保存状态；运行中的任务和下载完成后再更新。';
    apply.hidden = !state.canUpdate; check.disabled = state.status === 'checking'; apply.disabled = state.status === 'checking';
    options.onState?.(state);
  } });
  check.onclick = () => void checker.check(); apply.onclick = () => void checker.applyUpdate();
  checker.start();
  return { checker, destroy() { checker.destroy(); box.remove(); } };
}
