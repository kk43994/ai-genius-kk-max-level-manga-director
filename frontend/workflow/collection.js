// Collect only an already accepted image task. Never prepare/submit/rerun here.
const retryable = new Set(['INTERRUPTED_ORIGINAL_TASK','DELIVERY_UNCONFIRMED','MEDIA_TRANSFER_FAILED','PROVIDER_UNAVAILABLE','SUBMISSION_UNKNOWN']);
export function canAutoCollect(task) {
  return Boolean(task.submissionAttempted && task.canRecover && task.providerReceipt?.taskId &&
    (['queued','submitted','running','downloading','submitting'].includes(task.status) ||
     task.status==='needs_attention' && retryable.has(task.error?.code)));
}
export function nextCollection(tasks, attempts = new Map(), now = Date.now()) {
  return tasks.filter(canAutoCollect).map(task=>({task,due:attempts.get(task.id)?.due||now+8000}))
    .sort((a,b)=>Number(attempts.has(a.task.id))-Number(attempts.has(b.task.id)) || a.due-b.due || a.task.createdAt.localeCompare(b.task.createdAt) || a.task.id.localeCompare(b.task.id))[0] || null;
}
export function collectionDelay(task) {
  return task.status==='needs_attention' ? 30000 : 8000;
}

export function needsAssetRefresh(tasks, assets) {
  const stored = new Set(assets.flatMap(asset=>asset.revisions.map(revision=>revision.id)));
  return tasks.some(task=>task.status==='completed' && (task.outputs||[]).some(output=>output.revisionId&&!stored.has(output.revisionId)));
}
