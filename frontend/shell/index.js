/** Presentation only: no API calls, provider state, persistence or task submission. */
const mountsByRoot = new WeakMap();
const CONNECTION_STATES = new Set(['unknown', 'disconnected', 'connected', 'expired', 'error']);
const WORKSPACE_STATES = new Set(['empty', 'ready']);

export function mount({ root = document, events = new EventTarget(), session = null } = {}) {
  mountsByRoot.get(root)?.unmount();
  const doc = root.ownerDocument || root;
  const win = doc.defaultView;
  const body = doc.body;
  const byId = id => root.querySelector(`#${id}`);
  const abort = new AbortController();
  const listen = (target, type, fn, options = {}) => target?.addEventListener(type, fn, { ...options, signal: abort.signal });
  const panels = {
    library: { dialog: byId('library-dialog'), content: byId('library-panel'), dock: byId('library-dock'), slot: byId('library-dialog-body'), media: win.matchMedia('(max-width: 819px)') },
    activity: { dialog: byId('activity-dialog'), content: byId('activity-panel'), dock: byId('activity-dock'), slot: byId('activity-dialog-body'), media: win.matchMedia('(max-width: 1199px)') },
    review: { dialog: byId('review-drawer') },
    info: { dialog: byId('shell-info-dialog') },
  };
  const lastFocus = new Map();
  let active = true;
  let bodyOverflow = null;
  // The session remains opaque here; owning modules decide what is authenticated/saved.
  void session;

  function announce(message) {
    if (byId('shell-status')) byId('shell-status').textContent = message;
  }
  function setView(view = {}) {
    if (!active) return;
    if (CONNECTION_STATES.has(view.connectionState)) body.dataset.connectionState = view.connectionState;
    if (WORKSPACE_STATES.has(view.workspaceState)) body.dataset.workspaceState = view.workspaceState;
    if (typeof view.projectName === 'string' && byId('workspace-title')) byId('workspace-title').textContent = view.projectName;
    if (typeof view.saveLabel === 'string' && byId('saveStatus')) byId('saveStatus').textContent = view.saveLabel;
    // This controls presentation only. It never enables any generation capability.
  }
  function restore(panel) {
    if (panel.content && panel.content.parentElement !== panel.dock) panel.dock.append(panel.content);
  }
  function focusVisible(element) {
    if (!element?.isConnected || !element.getClientRects().length) return false;
    element.focus({ preventScroll: true });
    return true;
  }
  function closePanel(name) {
    const panel = panels[name];
    if (!panel?.dialog?.open) return;
    panel.dialog.close();
  }
  function openPanel(name, trigger = doc.activeElement) {
    const panel = panels[name];
    if (!panel?.dialog || !active) return false;
    if (panel.dialog.open) return true;
    // Only one shell modal at a time; preserve the same nodes and form values.
    const source = Object.entries(panels).find(([, item]) => item.dialog?.open && item.dialog.contains(trigger));
    const returnFocus = source ? lastFocus.get(source[0]) || trigger : trigger;
    Object.keys(panels).forEach(other => { if (other !== name) closePanel(other); });
    lastFocus.set(name, returnFocus);
    if (panel.content) panel.slot.append(panel.content);
    if (bodyOverflow === null) { bodyOverflow = body.style.overflow; body.style.overflow = 'hidden'; }
    panel.dialog.showModal();
    panel.dialog.querySelector('[data-shell-close]')?.focus();
    return true;
  }
  function explain(title, message, trigger) {
    byId('shell-info-title').textContent = title;
    const p = doc.createElement('p');
    p.textContent = message;
    byId('shell-info-body').replaceChildren(p);
    openPanel('info', trigger);
  }
  function action(name, trigger) {
    const event = new CustomEvent('shell:action', { detail: { action: name, trigger }, cancelable: true });
    // Integration handles an action by synchronously calling preventDefault().
    if (!events.dispatchEvent(event)) return;
    const fallback = {
      connect: ['连接 LibTV 账号', '通过 LibTV 官方网页授权后，你可以选择自己的账号与个人或团队空间。当前账号模块尚未接入，暂时无法开始授权。'],
      'manual-plan': ['整理资产清单', '手工清单可以从角色、场景与道具开始，不依赖自动剧本分析。当前流程模块尚未接入，暂时无法保存清单。'],
      help: ['从故事到资产', '导入剧本或手工整理清单；用 MJ 确定风格，用 Image2 制作资产，再用 Nano 保真精修。每一步由你审核，通过后再进入下一步。任务保留发起账号与空间，最终视频生成仍暂停。'],
    }[name];
    if (fallback) explain(...fallback, trigger);
  }

  listen(root, 'click', event => {
    const button = event.target.closest?.('button');
    if (!button || button.disabled) return;
    const close = button.hasAttribute('data-shell-close');
    const owned = close || button.dataset.shellAction || ['showWarehouse', 'toggleWarehouse', 'taskButton', 'helpButton'].includes(button.id);
    if (!owned) return;
    event.preventDefault();
    event.stopImmediatePropagation(); // Avoid legacy layout/dialog handlers on these same shell controls.
    if (close) return button.closest('dialog')?.close();
    if (button.dataset.shellAction) return action(button.dataset.shellAction, button);
    if (button.id === 'taskButton') return openPanel('activity', button);
    if (button.id === 'helpButton') return action('help', button);
    if (button.id === 'toggleWarehouse') {
      body.classList.add('warehouse-collapsed');
      button.setAttribute('aria-expanded', 'false');
      byId('showWarehouse')?.focus();
      announce('剧本与资产栏已收起');
    }
    if (button.id === 'showWarehouse') {
      if (panels.library.media.matches) return openPanel('library', button);
      body.classList.remove('warehouse-collapsed');
      byId('toggleWarehouse')?.setAttribute('aria-expanded', 'true');
      byId('toggleWarehouse')?.focus();
      announce('剧本与资产栏已展开');
    }
  }, { capture: true });

  for (const [name, panel] of Object.entries(panels)) {
    // Chromium otherwise consumes Escape to clear a search input before closing.
    // Preserve typed filters/drafts and provide one predictable way out of the drawer.
    listen(panel.dialog, 'keydown', event => {
      if (event.key === 'Escape' && !event.isComposing && panel.dialog.open) {
        event.preventDefault();
        event.stopPropagation();
        panel.dialog.close();
      }
      if (event.key === 'Tab' && panel.dialog.open) {
        const controls = [...panel.dialog.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])')]
          .filter(element => element.getClientRects().length && !element.closest('[hidden], [inert]') && win.getComputedStyle(element).visibility !== 'hidden');
        const first = controls[0], last = controls.at(-1);
        if (!first) { event.preventDefault(); return; }
        if (event.shiftKey && (doc.activeElement === first || !panel.dialog.contains(doc.activeElement))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (doc.activeElement === last || !panel.dialog.contains(doc.activeElement))) {
          event.preventDefault(); first.focus();
        }
      }
    }, { capture: true });
    listen(panel.dialog, 'close', () => {
      if (!panel.dialog.open) restore(panel);
      if (!Object.values(panels).some(item => item.dialog?.open) && bodyOverflow !== null) {
        body.style.overflow = bodyOverflow;
        bodyOverflow = null;
      }
      if (!Object.values(panels).some(item => item.dialog?.open)) {
        if (!focusVisible(lastFocus.get(name))) focusVisible(byId('workspace-main'));
      }
    });
    listen(panel.dialog, 'click', event => {
      if (event.target !== panel.dialog) return;
      const box = panel.dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) panel.dialog.close();
    });
    listen(panel.media, 'change', () => {
      if (!panel.media.matches && panel.dialog.open) closePanel(name);
    });
  }

  // Optional presentation event, intentionally separate from authoritative session/account events.
  listen(events, 'shell:view', event => setView(event.detail));
  listen(events, 'shell:open-panel', event => openPanel(event.detail?.panel));
  // Account modules may wrap their header; measure actual height instead of assuming a fixed row.
  const header = byId('account-root')?.closest('header');
  const observer = win.ResizeObserver && header ? new win.ResizeObserver(entries => {
    const height = entries[0]?.borderBoxSize?.[0]?.blockSize || header.getBoundingClientRect().height;
    if (height > 0) body.style.setProperty('--lab-header', `${Math.ceil(height)}px`);
  }) : null;
  observer?.observe(header);

  const controller = {
    setView, openPanel, closePanel, events,
    roots: Object.fromEntries(['account', 'task', 'update', 'workflow', 'project', 'review', 'review-summary'].map(name => [name, byId(`${name}-root`)])),
    unmount() {
      if (!active) return;
      active = false;
      abort.abort();
      observer?.disconnect();
      for (const panel of Object.values(panels)) { if (panel.dialog?.open) panel.dialog.close(); restore(panel); }
      if (bodyOverflow !== null) body.style.overflow = bodyOverflow;
      body.style.removeProperty('--lab-header');
      mountsByRoot.delete(root);
    },
  };
  mountsByRoot.set(root, controller);
  return controller;
}

export default mount;
