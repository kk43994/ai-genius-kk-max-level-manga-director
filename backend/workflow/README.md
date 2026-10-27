# Module 8: customer workflow integration

This module owns projects, scripts, manual entity plans, image versions/reviews and ZIP delivery. It imports no legacy engine, CLI, provider credential directory or production manifest. Every generated revision begins `pending`; only approved, current references continue downstream. Script import deliberately reports analysis unavailable. Final video has no workflow recipe.

## Compose

```python
from backend.workflow import WorkflowRepository, WorkflowService, WorkflowOutputStore, register_routes
workflow = WorkflowService(WorkflowRepository(services.storage), api_base=config.api_base)
outputs = WorkflowOutputStore(workflow, task_repository)
# Pass inputs=workflow and outputs=outputs to module 7's TaskService.
workflow.tasks = services.tasks
services.workflow = workflow
register_routes(router, services)
```

`WorkflowRepository` uses module 3 Store's `transaction`, tenant-scoped records and `blob_put/get`. It does not create a second database or migrations. Namespaces are `workflow.projects`, `workflow.scripts`, `workflow.assets`, `workflow.revisions`, `workflow.bundles` and a tenant CAS sentinel `workflow.control/workflow_state`. All workflow metadata mutations compare the sentinel before commit. Blobs are written first, outside the metadata writer to avoid nested SQLite writers. A cancelled/conflicting operation may leave an unreferenced private blob for later storage GC; it never leaves a committed asset pointing at missing bytes. Reads do not modify records.

Install `backend/workflow/requirements.txt` in the service runtime for verified raster decoding and thumbnails. Real downloads are decoded as single-frame PNG/JPEG/WebP, max 40 MiB and 40 million pixels. ZIP input is capped at 60 MiB to remain below the central blob store's 64 MiB cap. Future large deliveries need streaming/multipart storage; do not silently loosen this cap.

## Exact task integration requirement

`WorkflowService.validate_task_inputs(ctx, spec, ownership)` is module 7's `InputValidator`. It returns:

```python
{
  'projectTenantId': ctx.tenantId,
  'spec': original_six_field_spec,
  'sources': [{'revisionId': 'rev_...', 'sha256': '...', 'ownership': {...},
               'review': 'approved', 'stale': False}],
  'workflowSnapshot': {'entityVersion': 1, 'styleVersion': 1,
                       'sourceHashes': {'rev_...': 'sha256...'}}
}
```

Module 7's `_validate_inputs` MUST retain `workflowSnapshot` in its return value, so `task.inputs`, `inputHash` and confirmation digest persist it. Its existing revalidation/hash comparison in submit/recover must compare this snapshot too. This covers a style task with zero sources when the entity/style plan changes. Do not recreate a missing old snapshot from the current plan.

`WorkflowOutputStore.put(ctx, task_id=..., ownership=..., index=..., content=bytes, mime=..., sha256=...)` reads the raw durable task from `task_repository` and forwards that snapshot to `record_output`. Missing snapshot fails closed with `WORKFLOW_SNAPSHOT_MISSING` (409). It returns the revision ID as the opaque `blobId` handle; `read(ctx, handle)` verifies and returns those bytes. Transport/download remains module 7/provider-owned. An output MIME mismatch is rejected before recording. Duplicate `(taskId, index)` with identical bytes returns the original revision and never resets review; different bytes reject.

`build_spec(ctx, payload, ownership)` is an additional workflow preparation helper. It validates manual/script entities and source lineage, adds Nano preservation instructions and returns the snapshot. If used before TaskService prepare, pass only `{projectId, entityId, recipe, prompt, sourceRevisionIds, settings}` into TaskService. Ownership comes only from the server. Nano repair references are normalized to the original Image2 revision. The standard InputValidator does not silently change a client task's references: a Nano-to-Nano input is rejected and must be prepared with the Image2 ID.

`record_output` is an internal trusted callback, never an HTTP route. Only trusted persisted task dictionaries may call it. Output attributes/receipt dictionaries are not copied into asset records or delivery manifests. `_valid` recursively verifies the current entity/style version and approved references; changed source selections permanently mark existing downstream outputs stale. A late downloaded output remains in history as stale and cannot be approved.

## Routes and envelope

The module registers internal `/api/v1/...` contract paths. The shared app maps a configurable external `apiBase` to these paths. Responses have `status/body/headers`; JSON `body` is raw service data for the common adapter to wrap as `{data,meta}`. Typed workflow and central-storage errors are converted to `Response(status, {error: ...})` in this module; the common adapter adds request metadata without changing their codes. Unexpected errors still bubble to its safe generic handler. Origin/CSRF is also checked in the common adapter. Route handlers additionally require authenticated tenant and `csrfVerified` for mutations. Do not make images or ZIPs public.

Contract routes: projects GET/POST/PATCH; scripts POST/GET; plan GET/PUT; assets GET; reviews POST; asset content/thumbnail GET; project export GET. Additive, module-owned routes:

- `GET /workflow/capabilities`: analysis unavailable, video off, persistent project support.
- `GET /projects/{projectId}/bundles`: historical immutable delivery packages.
- `POST /projects/{projectId}/bundles` with `{expectedVersion}`: confirm archive only when every entity has all three approved current stages.
- `GET /projects/{projectId}/bundles/{bundleId}/content`: authenticated archived ZIP.

`GET /export` allows partial approved delivery and reports `coverage.complete=false`. POST archive requires full coverage. No raw script, note/prompt, provider subject/receipt/token, signed URL or filesystem path enters the allowlisted manifest. Approved bytes, lineage, dimensions, account/space IDs, hashes and approval time are exported.

## Frontend composition and updates

`frontend/asset-lab.js` now only exports `mount`. The integrator mounts it exactly once after restoring the site session; it does not auto-fetch from a global state. This intentionally replaces the old auto-start CLI-based controller.

```javascript
import {mount} from './asset-lab.js';
const workflowUI = mount({
  root: document.getElementById('workflow-root'), api, events, session,
  apiBase: config.apiBase, publicBasePath: config.publicBasePath
});
await workflowUI.ready;
// Before refresh/updating: await workflowUI.flushDrafts();
```

All JSON calls use injected `api.request`; media/download links use injected same-origin `apiBase`. Dynamic CSS uses its own module-relative URL. Supported root and subpath examples: `/api/v1` and `/asset-lab/api/v1`. No bare legacy `/api/workflow`/`dashixiong-image-test` requests remain in the customer controller.

Mount returns `unmount`, `ready`, `refresh`, `flushDrafts`, `hasUnsavedChanges`, `getState`. `flushDrafts` rejects while a save/import/review is in progress or localStorage fails. It persists draft edits, not an implicit server-side approval. The update controller must await it before reloading. Draft keys include tenant and API mount; no shared legacy localStorage keys are read. Drafts survive server version conflicts and ordinary refresh. Tenant change unmounts and clears this module's visible library/review projections.

Consumes `session:changed`, `selection:changed`, `tasks:changed`, `workflow:navigate`, `workflow:manual-plan`, `workflow:flush-drafts`. `workflow:flush-drafts` accepts `detail.waitUntil(promise)`; the direct returned method is preferred. Handles shell `manual-plan` via cancelable `shell:action`. Emits `project:changed`, `shell:view`, `workflow:dirty`, `workflow:reviewed`, `workflow:remount-required`. Optional existing library IDs (`warehouseList`, `scriptSelect`, etc.) are updated; shell/account/task/update roots stay owned by their modules.

## Verification

Before the integration cherry-pick, point tests at module 3's code-only clone:

```sh
ASSET_LAB_STORAGE_REPO=/absolute/path/to/module-3/repo python -m unittest discover -s tests/workflow -v
node --test tests/workflow/test_model.mjs
```

After integration, omit the environment variable. Tests create new random sessions and isolated temporary data; no real provider authorization, subscription, credits or network calls are used. They cover full three-entity / nine-image closure, forced review gates, Nano ancestry/repair, source version invalidation, tenant/account/space separation, restart, CAS conflict, content tamper, malicious DOCX/path input, safe ZIPs, partial vs complete archive and snapshot fail-closed behavior.

## Current integration evidence

Module 3 / 7 / 8 combined synthetic checks also passed on 2026-10-27: snapshot through the real task/output bridge, review-gated next-stage ownership, a plan change during remote work, and a plan change racing final output storage. Module 7 now retains and checks the exact snapshot described above. These four tests use the real modules with an in-process provider fake; they do not prove official authorization or real paid generation.

The 2026-10-28 local UI adds six visible step buttons, thumbnail-to-original review, operation labels with elapsed time and indeterminate progress, and a count of approved current stages. Five-second local task polling replaces only task/guide feedback, preserving form nodes and carets. It must not reset the eight-second original-receipt recovery timer. Recovery remains distinct from a new paid submission. The browser regression at `tests/workflow/feedback-fixture.html` checks these behaviors with a synthetic API and no provider calls.

Script reanalysis accepts `preview: true` and returns an editable proposal without changing the saved plan. Numbered shot/flashback labels are excluded from characters, and numbered scene headings become locations. A pending plan draft must be confirmed before continuing production. The local customer grant is connected, but official project/account binding and production generation response contracts are not yet verified; UI fixtures and downloads do not establish real LibTV generation acceptance.
