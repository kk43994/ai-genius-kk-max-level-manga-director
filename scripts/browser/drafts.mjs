/** Server acknowledgements, not localStorage writes, permit a safe page update. */
const encode = value => JSON.stringify(value);
const parse = value => { try { return JSON.parse(value || 'null'); } catch { return null; } };

export class DraftCoordinator {
  constructor({api, storage, tenantId, apiBase, onState = () => {}}) {
    Object.assign(this, {api, storage, onState});
    this.workflowKey = `asset-lab:workflow:v1:${encodeURIComponent(apiBase)}:${encodeURIComponent(tenantId)}`;
    this.accountKey = `asset-lab:accounts:v1:${tenantId}`;
    this.metaKey = this.workflowKey + ':server-checkpoint';
    this.version = 0; this.ack = null; this.conflict = false; this.pendingSave = null; this.error = '';
    this.adapter = {getItem: key => storage.getItem(key), setItem: (key, value) => {
      storage.setItem(key, value); this.changed();
    }, removeItem: key => {storage.removeItem(key); this.changed();}};
  }
  snapshot() {
    const workflow = parse(this.storage.getItem(this.workflowKey)) || {};
    const raw = parse(this.storage.getItem(this.accountKey));
    const draft = this.readAccountDraft ? this.readAccountDraft() : raw?.draft;
    return {workflow, accountSelection: draft ? {
      providerAccountId: draft.providerAccountId ?? null, spaceId: draft.spaceId ?? null,
    } : null};
  }
  async load() {
    const record = await this.api.request('/drafts/browser');
    const local = this.snapshot(), checkpoint = parse(this.storage.getItem(this.metaKey));
    const hasLocal = Boolean(this.storage.getItem(this.workflowKey) || this.storage.getItem(this.accountKey));
    const localChanged = hasLocal && encode(local) !== checkpoint?.fingerprint;
    this.version = record.version;
    if (record.version && localChanged && encode(local) !== encode(record.content)
        && checkpoint?.version !== record.version) {
      this.conflict = true;
      this.error = '另一个页面保存了不同草稿；本页与服务器内容均已保留。请在原页面完成保存后再更新。';
    } else if (record.version && !localChanged) {
      this.storage.setItem(this.workflowKey, encode(record.content.workflow));
      const account = parse(this.storage.getItem(this.accountKey)) || {};
      if (record.content.accountSelection) account.draft = record.content.accountSelection;
      else delete account.draft;
      this.storage.setItem(this.accountKey, encode(account));
    }
    this.ack = record.version ? encode(record.content) : encode({workflow:{},accountSelection:null});
    if (!this.conflict && encode(this.snapshot()) === this.ack) this.checkpoint();
    this.onState(this); return record;
  }
  checkpoint() {
    this.storage.setItem(this.metaKey, encode({version:this.version, fingerprint:this.ack}));
  }
  hasContent() {
    const {workflow,accountSelection}=this.snapshot();
    return Boolean(accountSelection?.providerAccountId || accountSelection?.spaceId || workflow.selectedProject
      || Object.entries(workflow).some(([key,value]) => key.startsWith('plan:') || key.startsWith('compose:') || key.startsWith('review:')
        || (key==='quick-start' && Boolean(value?.text?.trim()))
        || (key==='new-project' && Object.values(value || {}).some(text=>String(text).trim()))));
  }
  hasPending() { return this.conflict || Boolean(this.pendingSave) || ((this.version>0 || this.hasContent()) && encode(this.snapshot()) !== this.ack); }
  changed() { clearTimeout(this.timer); this.onState(this); if(!this.paused) this.timer = setTimeout(() => this.save().catch(() => {}), 800); }
  async save({force=false}={}) {
    clearTimeout(this.timer);
    if(this.paused) throw new Error('工作区会话正在切换，旧工作区草稿已暂停提交。');
    if (this.pendingSave) { await this.pendingSave; return this.save({force}); }
    if (this.conflict) throw new Error(this.error);
    if (!force && !this.version && !this.hasContent()) return {saved:true,savedDrafts:[]};
    const snapshot = this.snapshot(), fingerprint = encode(snapshot);
    if (!force && fingerprint === this.ack && this.version) return {saved:true, savedDrafts:[{collection:'drafts',id:'browser_drafts_v1',version:this.version}]};
    this.pendingSave = this.api.request('/drafts/browser', {method:'PUT', body:{expectedVersion:this.version,content:snapshot}});
    this.onState(this);
    try {
      const result = await this.pendingSave;
      if (result.saved !== true) throw new Error('服务器未确认保存');
      this.version = result.version; this.ack = fingerprint; this.error = ''; this.checkpoint();
      return {saved:encode(this.snapshot()) === fingerprint, savedDrafts:result.savedDrafts};
    } catch (error) {
      this.error = error.message || '草稿尚未保存到服务器';
      if (error.code === 'VERSION_CONFLICT') this.conflict = true;
      throw error;
    } finally { this.pendingSave = null; this.onState(this); }
  }
  pause() { this.paused=true; clearTimeout(this.timer); }
  resume() { this.paused=false; if(this.hasPending())this.changed(); }
  destroy() { this.pause(); }
}
