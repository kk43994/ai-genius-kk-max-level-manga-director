# Customer shell integration (module 5)

This module owns the shared page structure, design tokens, responsive panels and transport helper. It never decides whether a provider is authenticated, a project is saved, a task is completed or an update is safe to apply. `tests/ui/` is a local, synthetic visual fixture, not a provider or workflow implementation.

## Mount points

| Target | Owner | Contract |
|---|---|---|
| `#account-root` | 6 accounts | Header account / space / connection / quota UI. Replace its children, not the root. |
| `#project-root` | 8 workflow | Optional project picker enhancement. Existing `#scriptSelect` and `#importScript` are retained. |
| `#warehouseList`, `#warehouseFilters` | 8 workflow | Assets and category controls. All baseline IDs remain present. |
| `#workflow-root` | 8 workflow | Main production flow; includes the legacy `#steps` and `#main` targets. |
| `#task-root` | 7 tasks | Persistent task content, in the right rail or the same DOM nodes in a narrow-screen drawer. |
| `#review-summary-root` | 8 workflow | Compact review summary in the right rail. |
| `#review-root` | 8 workflow | Review form in the shared `#review-drawer` native dialog. |
| `#update-root` | 9 releases | Persistent version / release notes / refresh surface outside all replaceable business roots. |

Modules may replace only their own root contents. Do not replace the entire `.workspace-grid` or bind layout events to root ancestry; panels are reparented into dialogs on demand. DOM nodes, listeners, form values and module instances are preserved. Do not clone `#task-root` for mobile, or it will duplicate IDs and task state.

## Shell controller

```js
import { mount as mountShell } from './shell/index.js';
import { createApiClient } from './api-client.js';

// config comes from the integration bootstrap, not guessed window globals.
const api = createApiClient({ publicBasePath: config.publicBasePath, apiBase: config.apiBase });
const events = new EventTarget();
const session = await api.request('/session'); // captures csrfToken in memory
const shell = mountShell({ root: document, events, session });

// The authoritative account/project modules supply these presentation values.
shell.setView({
  connectionState: 'connected', // unknown | disconnected | connected | expired | error
  workspaceState: 'ready',     // empty | ready; ready preserves work if auth expires
  projectName: '项目名称',
  saveLabel: '已保存',          // only after the owning module verifies persistence
});
shell.openPanel('review'); // library | activity | review
shell.closePanel('review');
// Also supports events 'shell:view' with the same object, and
// 'shell:open-panel' with {panel:'review'}; both are presentation-only.

events.addEventListener('shell:action', event => {
  // Connect these explicitly to the accounts/workflow/help controllers.
  // Possible actions: connect, manual-plan, help. Cancel synchronously.
  if (event.detail.action === 'connect') {
    event.preventDefault();
    accounts.openAccountManager(); // example owner API, not an implementation here
  }
});
```

`shell.roots` maps `account`, `task`, `update`, `workflow`, `project`, `review` and `review-summary` to actual elements. `unmount()` removes its listeners and restores reparented panels. Re-mounting on the same root disposes the previous shell controller. `shell/bootstrap.js` exists only to make the baseline page operable. Module 10 should replace its script tag with the integrated bootstrap, supplying one shared EventTarget to all modules. The baseline `asset-lab.js` auto-load script is still present to preserve the original entry arrangement; module 10/8 must mount the migrated workflow once, avoiding legacy auto-start and new mount side-by-side.

When `workspaceState=empty` and connection is not connected, onboarding is visible. A connected account (even with no project yet) or an existing workspace shows the workflow instead. Expired authorization with `workspaceState=ready` never clears the work area. HTML defaults to unknown/empty and never asserts a verified account. The disabled header fallback is replaced by module 6; unhandled onboarding actions explain that the owning module is unavailable rather than simulating success.

Native dialogs provide inert background semantics. Shell adds one-press Escape, Tab/Shift+Tab cycling, trigger focus restoration, scroll locking and actual-header-height measurement. Resizing moves no feature state and serializes no drafts. Unsaved work across reload/version updates remains the persistence/update modules' responsibility.

## Design and CSS

Keep stylesheet order: `asset-lab.css`, `asset-lab-canvas.css`, `asset-lab-tokens.css`, `asset-lab-customer.css`, then module styles. New styles opt in through `body.customer-shell` or dedicated `.lab-*` / shell classes. Existing workflow CSS and business JS are unchanged. Shared colors/spacing/radii are `--lab-*`; legacy `--green`, `--ink`, `--line`, etc. alias them. Shared button/icon classes are `.lab-button`, `.primary`, `.secondary`, `.text-button`, `.lab-icon-button`, `.lab-icon`.

- At 1200px and above: library + main workflow + task rail.
- 820–1199px: library + main workflow; task drawer.
- Below 820px: main workflow with library and task drawers; header wraps.
- 540px and below: onboarding and content stack vertically; review drawer fills the viewport.
- Keyboard focus uses a visible blue outline, controls use text alongside state colors, reduced-motion preference disables decorative motion.

## Public path and API transport

Every shell asset URL is relative; no `/dashixiong-...` prefix or root-domain URL is introduced. Serve a canonical trailing-slash mount (`/` or `/asset-lab/`) or inject a correct `<base href>` in the integrated entry. Deep links must receive that same explicit base. The shell does not fetch any API.

`createApiClient({publicBasePath:'/', apiBase, csrfToken, fetchImpl})` returns `{request, setCsrfToken, publicBasePath, apiBase}`. Default API is `${publicBasePath}api/v1`; an explicit same-origin `apiBase` overrides it. For example `/asset-lab/` resolves `/session` to `/asset-lab/api/v1/session`. Requests must pass a module-relative path beginning with one slash, e.g. `/tasks?projectId=...`, not `/api/v1/tasks`. Query values and opaque IDs must be encoded by their owning caller. Unsafe destinations/path traversal are rejected before network access.

`api.request(path,{method,body,idempotencyKey,signal,responseType})` includes same-origin cookies, in-memory CSRF for writes and optional caller-owned Idempotency-Key; it returns the v1 `data` or throws `ApiError` with `code`, `message`, `status`, `retryable`, `requestId`, `details`. It does not retry, including POST, and rejects redirects. JSON error text is taken only from the v1 envelope; raw HTML/network exceptions are never shown. `responseType:'blob'` supports authenticated exports; it does not start a browser download itself. `GET /session` captures its returned csrfToken; no provider credentials enter this helper. Set/clear CSRF with `setCsrfToken` when rotating or ending the site session.

## Local checks

```sh
node --test tests/ui/api-client.test.mjs
python3 tests/ui/preview_server.py --port 8875
```

Open `http://127.0.0.1:8875/?state=empty` or `?state=connected` or `?state=expired`. The same fixtures are served at `/asset-lab/` to check a subpath. This test server binds only to loopback, rejects reserved ports 8768/8870, has no write API, provider code, tokens or customer data. Its `__ui__` routes are test-only and must not be deployed.

Chrome verification covered 320/390/1024/1440px widths without document overflow, legacy ID and ARIA target preservation, mobile drawers, Escape/Tab/Shift+Tab, return focus, search text and review draft retention across panel close/reopen and viewport changes. See module-5 delivery report for screenshot paths and exact evidence. This verifies the shell/fixtures, not real OAuth, two-account isolation, persistence after refresh, paid generation or deployment.
