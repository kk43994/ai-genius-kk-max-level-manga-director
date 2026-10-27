"""Durable per-owner operation markers in the existing Store, no second database."""
from contextlib import contextmanager
from copy import deepcopy

from .errors import GenerationError
from .types import digest, owner, same_owner, safe_receipt


def context_for(source, ownership):
    ctx = source(ownership) if callable(source) else source
    tenant = ctx.get('tenantId') if isinstance(ctx, dict) else getattr(ctx, 'tenantId', None)
    if tenant != ownership['tenantId']:
        raise GenerationError('OWNERSHIP_MISMATCH')
    return ctx


class StoreGenerationJournal:
    def __init__(self, store, ctx):
        self.store, self.ctx = store, ctx

    @contextmanager
    def edit(self, ownership, task_id):
        owner(ownership)
        ctx = context_for(self.ctx, ownership)
        key = 'gen_' + digest([ownership['providerAccountId'], ownership['spaceId'], task_id])
        with self.store.transaction(ctx) as tx:
            try:
                row = tx.get('generation.operations', key)
            except Exception as exc:
                if getattr(exc, 'code', None) != 'NOT_FOUND':
                    raise
                row = None
            value = deepcopy(row['data']) if row else {'ownership': deepcopy(ownership), 'localTaskId': task_id, 'steps': {}}
            if not same_owner(value['ownership'], ownership) or value['localTaskId'] != task_id:
                raise GenerationError('OWNERSHIP_MISMATCH')
            before = deepcopy(value)
            yield value
            if row is None:
                tx.create('generation.operations', value, record_id=key,
                          immutable_fields=('ownership', 'localTaskId'))
            elif value != before:
                tx.update('generation.operations', key, value, expected_version=row['version'])


class TaskSubmissionBridge:
    """Only a persisted TaskService submission permits writes. Receipt before spend.

    Uses the task module's public repository port. It never changes owner/spec,
    clears attempted, cancels leases or promotes a task to completed.
    """
    def __init__(self, task_repository, ctx):
        self.repository, self.ctx = task_repository, ctx

    def check(self, task_id, ownership, request_hash, idempotency_key):
        with self.repository.transaction(context_for(self.ctx, ownership)) as tx:
            task = tx.get_task(task_id)
        if (not task or not same_owner(task['ownership'], ownership)
                or task.get('inputHash') != request_hash
                or task.get('submissionAttempted') is not True
                or task.get('submissionKey') != idempotency_key
                or task.get('status') != 'submitting'):
            raise GenerationError('CONFIRMATION_REQUIRED')

    def checkpoint(self, task_id, ownership, receipt):
        new = safe_receipt(receipt)
        error = None
        with self.repository.transaction(context_for(self.ctx, ownership)) as tx:
            task = tx.get_task(task_id)
            if not task or not same_owner(task['ownership'], ownership):
                error = 'OWNERSHIP_MISMATCH'
            else:
                old = task.get('providerReceipt') or {}
                if any(k in old and old[k] != v for k, v in new.items()):
                    error = 'PROVIDER_RECEIPT_MISMATCH'
                else:
                    merged = {**old, **new}
                    if merged != old:
                        version = task['version']
                        task.update(providerReceipt=merged, version=version + 1)
                        tx.put_task(task, version)
        if error:
            raise GenerationError(error)

    def task_for_receipt(self, ownership, receipt):
        receipt = safe_receipt(receipt)
        with self.repository.transaction(context_for(self.ctx, ownership)) as tx:
            rows = [t for t in tx.list_tasks() if same_owner(t['ownership'], ownership)
                    and t.get('providerReceipt') == receipt]
        if len(rows) != 1:
            raise GenerationError('ORIGINAL_RECEIPT_REQUIRED')
        return rows[0]['id']


class WorkflowReferenceReader:
    """Reads verified revision bytes through module 8, never arbitrary local paths."""
    def __init__(self, workflow, ctx):
        self.workflow, self.ctx = workflow, ctx

    def read(self, ownership, snapshot):
        from .types import VerifiedReference
        ctx = context_for(self.ctx, ownership)
        revision = self.workflow.get_revision(ctx, snapshot['revisionId'], ownership=ownership,
                                              require_approved=True)
        raw, mime = self.workflow.content(ctx, revision['assetId'], revision['id'])
        # Recheck metadata after the blob read to detect a concurrent review/version change.
        current = self.workflow.get_revision(ctx, revision['id'], ownership=ownership, require_approved=True)
        if current != revision or revision['sha256'] != snapshot['sha256']:
            raise GenerationError('SOURCE_CHANGED')
        return VerifiedReference(revision['id'], deepcopy(ownership), raw, mime, revision['sha256'],
                                 revision['stage'], revision['review'] == 'approved', revision['status'] == 'stale')
