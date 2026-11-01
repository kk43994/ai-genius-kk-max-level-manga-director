import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from backend.tasks import DownloadArtifact, TaskError, TaskPolicy, TaskService
from backend.tasks.model import digest
from support import Fixture, ProcessCrash, SQLiteRepository, TestProviderError, spec, temporary_directory


class TaskSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = temporary_directory()
        self.addCleanup(self.directory.cleanup)
        self.f = Fixture(Path(self.directory.name) / "tasks.sqlite3")

    def assertCode(self, code, function, *args, **kwargs):
        with self.assertRaises(TaskError) as cm:
            function(*args, **kwargs)
        self.assertEqual(cm.exception.code, code)

    def test_default_paid_gate_is_server_side(self):
        prepared = self.f.prepare()
        disabled = self.f.new_service(enabled=False)
        self.assertCode("PAID_SUBMISSION_DISABLED", disabled.submit, self.f.ctx,
                        prepared["task"]["id"], prepared["task"]["version"],
                        prepared["confirmation"]["token"], "disabled-submit")
        self.assertEqual(self.f.providers.submit_count, 0)
        self.assertFalse(disabled.get(self.f.ctx, prepared["task"]["id"])["submissionAttempted"])

    def test_old_placeholder_cannot_start_new_generation_but_paid_results_remain_recoverable(self):
        from unittest.mock import patch
        prompt='仓库\n请填写希望采用的视觉风格。\n生成完整的风格候选图。'
        self.assertCode('PROMPT_REVIEW_REQUIRED',self.f.prepare,prompt=prompt)
        self.assertEqual(self.f.providers.calls,[])
        with patch.object(TaskService,'_assert_new_prompt',return_value=None):
            old=self.f.prepare(prompt=prompt)
        self.assertCode('PROMPT_REVIEW_REQUIRED',self.f.submit,old)
        self.assertCode('PROMPT_REVIEW_REQUIRED',self.f.service.confirm,self.f.ctx,old['task']['id'],old['task']['version'])
        # Simulate a task submitted by the older release, then upgrade and collect.
        with patch.object(TaskService,'_assert_new_prompt',return_value=None):
            paid=self.f.submit(old)['task']
        self.f.providers.lookup_result={'status':'completed'}
        recovered=self.f.service.recover(self.f.ctx,paid['id'],paid['version'])['task']
        self.assertEqual(recovered['status'],'completed')
        self.assertEqual(self.f.providers.submit_count,1)

    def test_config_string_cannot_accidentally_enable_paid_submission(self):
        policy = TaskPolicy(confirmation_key=b"test-policy-secret" * 2, allow_paid_submission="false")
        with self.assertRaises(ValueError):
            TaskService(repository=None, providers=None, selections=None, spaces=None, inputs=None, outputs=None, policy=policy)
        self.assertNotIn("test-policy-secret", repr(policy))

    def test_video_recipe_cannot_prepare_even_with_enabled_test_policy(self):
        self.assertCode("VIDEO_OR_RECIPE_DISABLED", self.f.prepare, recipe="seedance_video")
        self.assertEqual(self.f.providers.calls, [])

    def test_browser_cannot_supply_owner_or_paths(self):
        self.assertCode("VALIDATION_FAILED", self.f.prepare, ownership={"tenantId": "tenant_B"})
        self.assertCode("VALIDATION_FAILED", self.f.prepare, settings={"nested": {"access_token": "secret"}})
        self.assertCode("VALIDATION_FAILED", self.f.prepare, settings={"url": "https://attacker.invalid"})

    def test_switch_requires_explicit_confirmation_and_keeps_original_owner(self):
        prepared = self.f.prepare()
        original = prepared["task"]["ownership"]
        self.f.selections.set(self.f.ctx, "pa_B", "space_team", 2)
        self.assertCode("SELECTION_CHANGED", self.f.submit, prepared)
        confirmed = self.f.service.confirm(self.f.ctx, prepared["task"]["id"], prepared["task"]["version"])
        self.assertEqual(confirmed["confirmation"]["summary"]["ownership"], original)
        submitted = self.f.submit(confirmed)["task"]
        self.assertEqual(submitted["ownership"], original)
        self.assertEqual(self.f.providers.calls[-1][1], original)
        new = self.f.prepare("new-account-prepare")["task"]
        self.assertEqual(new["ownership"]["providerAccountId"], "pa_B")
        self.assertEqual(new["ownership"]["spaceId"], "space_team")
        self.assertEqual(self.f.service.get(self.f.ctx, submitted["id"])["ownership"], original)

    def test_personal_and_team_spaces_do_not_change_login_identity(self):
        first = self.f.prepare()["task"]
        self.f.selections.set(self.f.ctx, "pa_A", "space_team", 2)
        second = self.f.prepare("prepare-team-key")["task"]
        self.assertEqual(first["ownership"]["providerSubject"], second["ownership"]["providerSubject"])
        self.assertNotEqual(first["ownership"]["spaceId"], second["ownership"]["spaceId"])
        self.assertEqual(second["ownership"]["spaceKind"], "team")

    def test_two_tenants_with_same_provider_subject_cannot_read_each_other(self):
        prepared = self.f.prepare()
        task_id = prepared["task"]["id"]
        self.assertCode("NOT_FOUND", self.f.service.get, self.f.other, task_id)
        self.assertCode("NOT_FOUND", self.f.service.recover, self.f.other, task_id, prepared["task"]["version"])
        self.assertCode("NOT_FOUND", self.f.service.cancel, self.f.other, task_id, prepared["task"]["version"])
        self.assertEqual(self.f.service.list(self.f.other)["items"], [])
        separate = self.f.service.prepare(self.f.other, spec(), 1, "prepare-key-001")
        self.assertNotEqual(separate["task"]["id"], task_id)

    def test_project_owner_and_reference_owner_are_validated(self):
        self.f.inputs.project_owner = "tenant_B"
        self.assertCode("NOT_FOUND", self.f.prepare)
        self.f.inputs.project_owner = None
        original = self.f.prepare()["task"]["ownership"]
        self.f.inputs.sources["revision_A"] = {"revisionId": "revision_A", "sha256": digest("file"),
                                              "ownership": {**original, "providerAccountId": "pa_B"},
                                              "review": "approved", "stale": False}
        self.assertCode("OWNERSHIP_MISMATCH", self.f.prepare, "source-mismatch-key", sourceRevisionIds=["revision_A"])
        self.f.inputs.sources["revision_A"]["ownership"] = original
        self.f.inputs.sources["revision_A"]["review"] = "pending"
        self.assertCode("SOURCE_REVIEW_REQUIRED", self.f.prepare, "source-pending-key", sourceRevisionIds=["revision_A"])

    def test_changed_source_hash_stops_before_billable_call(self):
        original = self.f.prepare()["task"]["ownership"]
        self.f.inputs.sources["revision_A"] = {"revisionId": "revision_A", "sha256": digest("file"),
                                              "ownership": original, "review": "approved", "stale": False}
        prepared = self.f.prepare("with-source-prepare", sourceRevisionIds=["revision_A"])
        self.f.inputs.sources["revision_A"]["sha256"] = digest("changed-file")
        failed = self.f.submit(prepared)["task"]
        self.assertEqual(failed["error"]["code"], "SOURCE_CHANGED")
        self.assertFalse(failed["submissionAttempted"])
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_wrong_subject_and_wrong_space_stop_submission(self):
        prepared = self.f.prepare()
        account = self.f.providers.accounts[(self.f.ctx.tenantId, "pa_A")]
        account["identity"]["subject"] = "different-real-login"
        blocked = self.f.submit(prepared)["task"]
        self.assertEqual(blocked["status"], "blocked_authorization")
        self.assertEqual(self.f.providers.submit_count, 0)
        account["identity"]["subject"] = "subject-pa_A"
        self.f.providers.wrong_space = "space_team"
        recovered = self.f.service.recover(self.f.ctx, blocked["id"], blocked["version"])["task"]
        self.assertEqual(recovered["status"], "blocked_authorization")
        self.assertEqual(recovered["ownership"], prepared["task"]["ownership"])

    def test_identity_checked_again_immediately_before_submission(self):
        prepared = self.f.prepare()
        checks = 0
        def change_on_second_check(client):
            nonlocal checks
            checks += 1
            if checks == 2:
                self.f.providers.accounts[(self.f.ctx.tenantId, "pa_A")]["identity"]["subject"] = "replacement"
        self.f.providers.identity_hook = change_on_second_check
        result = self.f.submit(prepared)["task"]
        self.assertEqual(checks, 2)
        self.assertEqual(result["status"], "blocked_authorization")
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_expired_authorization_only_restores_same_owner(self):
        prepared = self.f.prepare()
        account = self.f.providers.accounts[(self.f.ctx.tenantId, "pa_A")]
        account["authorization"]["state"] = "expired"
        blocked = self.f.submit(prepared)["task"]
        self.assertFalse(blocked["submissionAttempted"])
        self.f.selections.set(self.f.ctx, "pa_B", "space_team", 2)
        account["authorization"]["state"] = "connected"
        restored = self.f.service.recover(self.f.ctx, blocked["id"], blocked["version"])["task"]
        self.assertEqual(restored["status"], "draft")
        confirmed = self.f.service.confirm(self.f.ctx, restored["id"], restored["version"])
        submitted = self.f.submit(confirmed, "after-reauthorization")["task"]
        self.assertEqual(submitted["ownership"], prepared["task"]["ownership"])
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_prepare_idempotency_survives_new_service_and_new_db_connection(self):
        first = self.f.prepare()
        restarted = self.f.new_service(repository=SQLiteRepository(self.f.repository.path))
        same = restarted.prepare(self.f.ctx, spec(), 1, "prepare-key-001")
        self.assertEqual(first, same)
        self.assertEqual(sum(call[0] == "prepare" for call in self.f.providers.calls), 1)
        self.assertCode("IDEMPOTENCY_CONFLICT", restarted.prepare, self.f.ctx, spec(prompt="changed"), 1, "prepare-key-001")

    def test_concurrent_prepare_only_calls_provider_once(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.f.prepare(), range(6)))
        self.assertEqual(len({r["task"]["id"] for r in results}), 1)
        self.assertEqual(sum(call[0] == "prepare" for call in self.f.providers.calls), 1)

    def test_submit_idempotency_survives_restart_and_current_policy_disabled(self):
        prepared = self.f.prepare()
        submitted = self.f.submit(prepared)
        restarted = self.f.new_service(enabled=False, repository=SQLiteRepository(self.f.repository.path))
        replay = restarted.submit(self.f.ctx, prepared["task"]["id"], prepared["task"]["version"],
                                  prepared["confirmation"]["token"], "submit-key-001")
        self.assertEqual(replay, submitted)
        self.assertEqual(self.f.providers.submit_count, 1)
        self.assertCode("IDEMPOTENCY_CONFLICT", restarted.submit, self.f.ctx, prepared["task"]["id"],
                        submitted["task"]["version"], prepared["confirmation"]["token"], "submit-key-001")

    def test_concurrent_submit_keys_cannot_generate_twice(self):
        prepared = self.f.prepare()
        entered, release = threading.Event(), threading.Event()
        def slow_submit(client):
            entered.set()
            self.assertTrue(release.wait(5))
        self.f.providers.submit_hook = slow_submit
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.f.submit, prepared)
            self.assertTrue(entered.wait(5))
            replay = self.f.submit(prepared)
            self.assertEqual(replay["task"]["status"], "submitting")
            self.assertCode("VERSION_CONFLICT", self.f.submit, prepared, "second-submit-key")
            release.set()
            future.result(5)
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_attempt_marker_is_durable_before_provider_call(self):
        prepared = self.f.prepare()
        def inspect_durable_marker(client):
            other_service = self.f.new_service(repository=SQLiteRepository(self.f.repository.path))
            persisted = other_service.get(self.f.ctx, prepared["task"]["id"])
            self.assertTrue(persisted["submissionAttempted"])
            self.assertEqual(persisted["status"], "submitting")
        self.f.providers.submit_hook = inspect_durable_marker
        self.f.submit(prepared)

    def test_failed_commit_never_reaches_provider_submission(self):
        prepared = self.f.prepare()
        self.f.repository.fail_attempt_commit = True
        with self.assertRaises(OSError):
            self.f.submit(prepared)
        self.assertEqual(self.f.providers.submit_count, 0)
        persisted = self.f.service.get(self.f.ctx, prepared["task"]["id"])
        self.assertFalse(persisted["submissionAttempted"])

    def test_timeout_with_original_receipt_can_only_lookup_not_resubmit(self):
        prepared = self.f.prepare()
        self.f.providers.submit_error = TimeoutError("token=secret")
        unknown = self.f.submit(prepared)["task"]
        self.assertEqual(unknown["status"], "needs_attention")
        self.assertTrue(unknown["submissionAttempted"])
        self.assertCode("SUBMISSION_ALREADY_ATTEMPTED", self.f.service.submit, self.f.ctx, unknown["id"],
                        unknown["version"], "irrelevant", "retry-with-new-key")
        self.f.providers.lookup_result = {"status": "running"}
        recovered = self.f.service.recover(self.f.ctx, unknown["id"], unknown["version"])["task"]
        self.assertEqual(recovered["status"], "running")
        self.assertEqual(self.f.providers.lookups, [self.f.providers.prepared_receipt])
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_upload_failure_recovery_is_explicit_and_does_not_resubmit(self):
        self.f.providers.prepared_receipt = {'projectId':'original-project'}
        prepared = self.f.prepare()
        self.f.providers.submit_error = TimeoutError()
        unknown = self.f.submit(prepared)['task']
        self.f.providers.lookup_result = {'status':'failed', 'failureStage':'reference_upload', 'generationSubmitted':False}
        recovered = self.f.service.recover(self.f.ctx, unknown['id'], unknown['version'])['task']
        self.assertEqual(recovered['status'],'failed')
        self.assertEqual(recovered['error']['code'],'REFERENCE_UPLOAD_FAILED')
        self.assertTrue(recovered['submissionAttempted'])
        self.assertEqual(self.f.providers.submit_count,1)
        self.assertCode('SUBMISSION_ALREADY_ATTEMPTED', self.f.service.submit, self.f.ctx,
            recovered['id'], recovered['version'], 'unused', 'never-replay')

    def test_timeout_without_receipt_stops_with_explanation(self):
        self.f.providers.prepared_receipt = None
        prepared = self.f.prepare()
        self.f.providers.submit_error = TimeoutError()
        unknown = self.f.submit(prepared)["task"]
        recovered = self.f.service.recover(self.f.ctx, unknown["id"], unknown["version"])["task"]
        self.assertEqual(recovered["error"]["code"], "ORIGINAL_RECEIPT_REQUIRED")
        self.assertEqual(self.f.providers.lookups, [])
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_explicit_error_receipt_is_preserved_without_error_text(self):
        self.f.providers.prepared_receipt = None
        prepared = self.f.prepare()
        self.f.providers.submit_error = TestProviderError("UNKNOWN", provider_receipt={"taskId": "official-found"})
        unknown = self.f.submit(prepared)["task"]
        self.assertEqual(unknown["providerReceipt"], {"taskId": "official-found"})
        self.assertNotIn("do-not-echo", json.dumps(unknown))
        self.assertNotIn("signed.invalid", Path(self.f.repository.path).read_bytes().decode("latin1"))

    def test_process_crash_after_upstream_acceptance_only_recovers_original(self):
        prepared = self.f.prepare()
        self.f.providers.submit_error = ProcessCrash()
        with self.assertRaises(ProcessCrash):
            self.f.submit(prepared)
        restarted = self.f.new_service(repository=SQLiteRepository(self.f.repository.path))
        before = restarted.get(self.f.ctx, prepared["task"]["id"])
        self.assertEqual(before["status"], "submitting")
        self.assertEqual(restarted.reconcile_after_restart(self.f.ctx), [])
        self.f.clock.advance()
        self.f.providers.lookup_result = {"status": "completed", "providerReceipt": {"taskId": "official-recovered"}}
        finished = restarted.recover_pending(self.f.ctx)[0]
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["review"], "pending")
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_process_crash_before_attempt_marker_can_return_to_draft(self):
        prepared = self.f.prepare()
        def crash(*args):
            raise ProcessCrash()
        self.f.inputs.hook = crash
        with self.assertRaises(ProcessCrash):
            self.f.submit(prepared)
        self.f.clock.advance()
        self.f.service.reconcile_after_restart(self.f.ctx)
        persisted = self.f.service.get(self.f.ctx, prepared["task"]["id"])
        self.assertEqual(persisted["status"], "draft")
        self.assertFalse(persisted["submissionAttempted"])
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_unknown_preparation_does_not_retry_side_effects_after_restart(self):
        self.f.providers.prepare_error = ProcessCrash()
        with self.assertRaises(ProcessCrash):
            self.f.prepare()
        self.f.clock.advance()
        self.f.service.reconcile_after_restart(self.f.ctx)
        task = self.f.service.list(self.f.ctx)["items"][0]
        self.assertEqual(task["status"], "needs_attention")
        self.assertCode("PREPARATION_UNCONFIRMED", self.f.service.recover, self.f.ctx, task["id"], task["version"])
        replay = self.f.prepare()
        self.assertEqual(replay["task"]["id"], task["id"])
        self.assertEqual(sum(call[0] == "prepare" for call in self.f.providers.calls), 1)

    def test_completed_files_use_original_identity_after_selection_switch(self):
        submitted = self.f.submit(self.f.prepare())["task"]
        self.f.selections.set(self.f.ctx, "pa_B", "space_team", 2)
        self.f.providers.calls.clear()
        self.f.providers.lookup_result = {"status": "completed"}
        completed = self.f.service.recover(self.f.ctx, submitted["id"], submitted["version"])["task"]
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(all(owner == submitted["ownership"] for _, owner in self.f.providers.calls))
        self.assertEqual(completed["outputs"][0]["review"], "pending")
        self.assertEqual(completed["review"], "pending")
        self.assertNotIn("signature", json.dumps(completed))

    def test_authorization_expires_between_lookup_and_download(self):
        submitted = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed"}
        def expire(client):
            self.f.providers.accounts[(self.f.ctx.tenantId, "pa_A")]["authorization"]["state"] = "expired"
        self.f.providers.lookup_hook = expire
        blocked = self.f.service.recover(self.f.ctx, submitted["id"], submitted["version"])["task"]
        self.assertEqual(blocked["status"], "blocked_authorization")
        self.assertEqual(blocked["providerReceipt"], submitted["providerReceipt"])
        self.assertFalse(any(call == "download" for call, _ in self.f.providers.calls))
        self.assertEqual(blocked["outputs"], [])

    def test_wrong_official_task_receipt_is_rejected(self):
        submitted = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed", "providerReceipt": {"taskId": "some-other-task"}}
        result = self.f.service.recover(self.f.ctx, submitted["id"], submitted["version"])["task"]
        self.assertEqual(result["error"]["code"], "PROVIDER_RECEIPT_MISMATCH")
        self.assertEqual(result["providerReceipt"], submitted["providerReceipt"])
        self.assertEqual(result["outputs"], [])

    def test_not_found_or_failed_remote_task_never_resubmits(self):
        submitted = self.f.submit(self.f.prepare())["task"]
        for state in ("not_found", "unknown", "failed"):
            self.f.providers.lookup_result = {"status": state}
            submitted = self.f.service.recover(self.f.ctx, submitted["id"], submitted["version"])["task"]
            self.assertIn(submitted["status"], {"needs_attention", "failed"})
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_bad_download_checksum_and_disk_corruption_cannot_mark_completed(self):
        task = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed"}
        self.f.providers.artifacts = [DownloadArtifact(b"synthetic image bytes", "image/png", "0" * 64)]
        task = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(task["error"]["code"], "OUTPUT_INVALID")
        self.f.providers.artifacts = [DownloadArtifact(b"synthetic image bytes", "image/png")]
        self.f.outputs.corrupt = True
        task = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(task["error"]["code"], "OUTPUT_STORE_UNVERIFIED")
        self.f.outputs.corrupt = False
        task = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(len(self.f.outputs.blobs), 1)
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_download_count_mismatch_retains_original_receipt(self):
        task = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed"}
        self.f.providers.artifacts = []
        result = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(result["error"]["code"], "OUTPUT_INVALID")
        self.assertEqual(result["providerReceipt"], task["providerReceipt"])

    def test_late_response_after_local_cancellation_preserves_receipt(self):
        prepared = self.f.prepare()
        def cancel_during_submit(client):
            current = self.f.service.get(self.f.ctx, prepared["task"]["id"])
            self.f.service.cancel(self.f.ctx, current["id"], current["version"])
        self.f.providers.submit_hook = cancel_during_submit
        task = self.f.submit(prepared)["task"]
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["providerReceipt"]["taskId"], "official-task-original")
        self.assertEqual(task["cancellation"], {"localOnly": True, "remoteConfirmed": False, "refundConfirmed": False})
        self.assertEqual(self.f.service.recover_pending(self.f.ctx), [])

    def test_cancel_during_download_does_not_resurrect_task(self):
        task = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed"}
        def cancel():
            current = self.f.service.get(self.f.ctx, task["id"])
            self.f.service.cancel(self.f.ctx, current["id"], current["version"])
        self.f.outputs.hook = cancel
        result = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["outputs"], [])

    def test_account_removal_blocks_work_but_retains_history_and_completed_files(self):
        done = self.f.submit(self.f.prepare())["task"]
        self.f.providers.lookup_result = {"status": "completed"}
        done = self.f.service.recover(self.f.ctx, done["id"], done["version"])["task"]
        pending = self.f.prepare("pending-after-completed")["task"]
        affected = self.f.service.block_account(self.f.ctx, "pa_A")
        self.assertEqual(affected, [pending["id"]])
        self.assertEqual(self.f.service.get(self.f.ctx, done["id"]), done)
        blocked = self.f.service.get(self.f.ctx, pending["id"])
        self.assertEqual(blocked["ownership"], pending["ownership"])
        self.assertEqual(blocked["providerReceipt"], pending["providerReceipt"])
        self.assertEqual(blocked["status"], "blocked_authorization")

    def test_expired_or_tampered_confirmation_rejected(self):
        prepared = self.f.prepare()
        self.f.clock.advance(700)
        self.assertCode("CONFIRMATION_EXPIRED", self.f.submit, prepared)
        confirmed = self.f.service.confirm(self.f.ctx, prepared["task"]["id"], prepared["task"]["version"])
        with self.f.repository.transaction(self.f.ctx) as tx:
            task = tx.get_task(prepared["task"]["id"])
            task["prepared"]["count"] = 2
            # Simulate an invalid adapter writing a changed snapshot without
            # increasing version; confirmation hash must still reject it.
            tx.put_task(task, task["version"])
        self.assertCode("CONFIRMATION_CHANGED", self.f.submit, confirmed)
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_quote_unknown_stays_unknown_and_old_quote_cannot_submit(self):
        prepared = self.f.prepare()
        self.assertEqual(prepared["cost"], {"state": "unknown", "amount": None, "unit": None})
        self.f.providers.quote = {"state": "known", "amount": 1, "unit": "credits", "expiresAt": "2026-10-26T00:00:00Z"}
        expired = self.f.prepare("expired-quote-prepare")
        self.assertCode("QUOTE_EXPIRED", self.f.submit, expired)

    def test_public_projection_omits_confirmation_storage_and_provider_preparation(self):
        prepared = self.f.prepare()
        public = self.f.service.get(self.f.ctx, prepared["task"]["id"])
        for key in ("lease", "confirmation", "spec", "prepared", "submissionKey", "inputs"):
            self.assertNotIn(key, public)

    def test_selection_change_during_preparation_is_caught_in_write_transaction(self):
        def switch(*args):
            self.f.selections.set(self.f.ctx, "pa_B", "space_team", 2)
        self.f.inputs.hook = switch
        self.assertCode("SELECTION_CHANGED", self.f.prepare)
        self.assertEqual(self.f.service.list(self.f.ctx)["items"], [])
        self.assertFalse(any(call == "prepare" for call, _ in self.f.providers.calls))

    def test_identity_only_provider_payload_still_checks_original_space(self):
        prepared = self.f.prepare()
        from support import FakeClient
        class IdentityOnly(FakeClient):
            def identity(self):
                identity = super().identity()
                return {key: identity[key] for key in ("issuer", "subject", "verified")}
        self.f.providers.client_for = lambda ctx, owner: IdentityOnly(self.f.providers, ctx, owner)
        self.f.spaces.get_space = lambda *args: {"id": "space_personal", "kind": "personal", "access": "revoked"}
        task = self.f.submit(prepared)["task"]
        self.assertEqual(task["status"], "blocked_authorization")
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_unrecognized_submit_status_preserves_valid_official_reference(self):
        self.f.providers.prepared_receipt = None
        self.f.providers.submit_result = {"status": "new-unmapped-provider-state", "providerReceipt": {"taskId": "official-new"}}
        task = self.f.submit(self.f.prepare())["task"]
        self.assertEqual(task["status"], "needs_attention")
        self.assertEqual(task["providerReceipt"], {"taskId": "official-new"})

    def test_expired_submit_lease_fences_old_worker_before_generation(self):
        prepared = self.f.prepare()
        def expire_during_preflight(*args):
            self.f.clock.advance()
            self.f.service.reconcile_after_restart(self.f.ctx)
        self.f.inputs.hook = expire_during_preflight
        self.assertCode("LEASE_LOST", self.f.submit, prepared)
        task = self.f.service.get(self.f.ctx, prepared["task"]["id"])
        self.assertFalse(task["submissionAttempted"])
        self.assertEqual(task["status"], "draft")
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_list_filters_and_cursor_do_not_leak_other_tenant(self):
        self.f.prepare("prepare-list-1")
        self.f.selections.set(self.f.ctx, "pa_B", "space_team", 2)
        self.f.prepare("prepare-list-2")
        first = self.f.service.list(self.f.ctx, limit=1)
        second = self.f.service.list(self.f.ctx, limit=1, cursor=first["nextCursor"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        selected = self.f.service.list(self.f.ctx, providerAccountId="pa_B", spaceId="space_team")
        self.assertEqual(len(selected["items"]), 1)
        self.assertEqual(self.f.service.list(self.f.other, cursor=first["nextCursor"])["items"], [])

    def test_workflow_snapshot_is_server_owned_hashed_and_not_provider_parameters(self):
        self.assertCode("VALIDATION_FAILED", self.f.prepare, workflowSnapshot={"entityVersion": 999})
        prepared = self.f.prepare()
        expected = {"entityVersion": 1, "styleVersion": 1, "sourceHashes": {}}
        self.assertEqual(prepared["task"]["workflowSnapshot"], expected)
        with self.f.repository.transaction(self.f.ctx) as tx:
            record = tx.get_task(prepared["task"]["id"])
            self.assertEqual(record["inputs"]["workflowSnapshot"], expected)
            self.assertEqual(record["inputHash"], digest(record["inputs"]))
        self.f.submit(prepared)
        self.assertNotIn("workflowSnapshot", json.dumps(self.f.providers.preparation_payloads))
        self.assertNotIn("workflowSnapshot", json.dumps(self.f.providers.submission_payloads))

    def test_changed_workflow_version_before_submit_is_not_billable(self):
        prepared = self.f.prepare()
        self.f.inputs.workflow_snapshot["styleVersion"] = 2
        task = self.f.submit(prepared)["task"]
        self.assertEqual(task["error"]["code"], "WORKFLOW_VERSION_CHANGED")
        self.assertFalse(task["submissionAttempted"])
        self.assertEqual(self.f.providers.submit_count, 0)
        self.assertEqual(task["workflowSnapshot"], prepared["task"]["workflowSnapshot"])

    def test_changed_workflow_version_after_submission_does_not_publish_old_output(self):
        prepared = self.f.prepare()
        task = self.f.submit(prepared)["task"]
        self.f.inputs.workflow_snapshot["entityVersion"] = 2
        self.f.providers.lookup_result = {"status": "completed"}
        task = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(task["status"], "needs_attention")
        self.assertEqual(task["error"]["code"], "WORKFLOW_VERSION_CHANGED")
        self.assertEqual(task["outputs"], [])
        self.assertEqual(self.f.outputs.blobs, {})
        self.assertEqual(task["workflowSnapshot"], prepared["task"]["workflowSnapshot"])
        self.assertEqual(task["providerReceipt"]["taskId"], "official-task-original")
        self.assertEqual(self.f.providers.submit_count, 1)

    def test_missing_workflow_snapshot_fails_closed_without_reconstruction(self):
        task = self.f.submit(self.f.prepare())["task"]
        with self.f.repository.transaction(self.f.ctx) as tx:
            stored = tx.get_task(task["id"])
            del stored["inputs"]["workflowSnapshot"]
            tx.put_task(stored, stored["version"])
        result = self.f.service.recover(self.f.ctx, task["id"], task["version"])["task"]
        self.assertEqual(result["error"]["code"], "WORKFLOW_SNAPSHOT_MISSING")
        self.assertEqual(result["providerReceipt"], task["providerReceipt"])
        self.assertEqual(self.f.providers.lookups, [])
        self.assertEqual(self.f.outputs.blobs, {})


if __name__ == "__main__":
    unittest.main()
