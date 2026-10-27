# Script-first customer workflow

The local workbench now opens directly on script entry. `POST /workflow/start`
accepts either text or one existing intake file format (TXT/MD/DOCX). A caller
supplies an idempotency key. Project, source, extracted plan and asset records
commit together through the tenant-scoped workflow repository. A lost response
can be retried with the same key; changed input with that key is rejected.

Extraction is an offline, conservative screenplay parser, not semantic AI
analysis. It recognizes explicitly labelled characters, locations, props,
visual style, common numbered sluglines and dialogue speakers. Every extracted
entry retains a literal source quote. Unsupported prose yields an empty draft
and a visible explanation. It never fabricates a successful analysis.

Generated plans require explicit confirmation. The server rejects task
preparation while `needsReview` is present. Existing plans are never overwritten
by the extraction endpoint. Detailed editing remains available separately.

The guide projects the current saved plan, selected owner, revisions and all
pages of task history into one next action. Submitted ambiguous tasks take
priority over new preparation, even after a plan edit. Missing task history
stops progression. Task preparation keeps stable identities including input,
selection and workflow versions. Returned images stop for human review; only
approved current images become references. Nano uses the original Image2
revision, including repair requests. After all required reviews, the guide
archives the exact approved revision set. Changed reviews invalidate an older
bundle. Receipt recovery polls only while the page is open, and resumes from
saved tasks after reopening. It never resubmits a paid task.

## Authorization

Ordinary authorization remains `account` / `libtv:account:read`. The explicit
`creator` profile requests the six published LibTV scopes. It has a separate
client registration and its profile is sealed into the original authorization
attempt, so callback restart cannot lose the requested scope. Reauthorization
pins the existing provider identity. Workspace ownership/recovery authorization
cannot use the creator profile. A granted-scope projection contains no tokens;
actual provider calls still validate the encrypted token bundle.

## Acceptance boundary, 2026-10-28

225 automated checks passed: auth 88, workflow 25, HTTP integration 72, JS 40.
The script-to-archive test uses synthetic PNGs and the real local Store. Browser
verification exercised script entry, three source-backed asset cards, single
plan confirmation, account handoff and service restart persistence. The
existing local account table was unchanged by the application update; SQLite
integrity and both local health responses were checked.

The official creator consent page was reached with the six expected scopes.
Consent has not been granted in this change. No paid generation was submitted.
AI semantic script analysis, production model/response/CDN configuration and a
real paid image-to-download acceptance run remain incomplete. Generation and
final video remain disabled. The published installers/download site have not
been replaced. These facts must not be described as a production full-flow pass.
