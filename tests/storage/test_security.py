"""No external services, credentials, real subjects, generation or listeners."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

from backend.sessions import SessionService, register_routes
from backend.storage import AccountRepository, SelectionRepository, StorageError, Store, TenantContext, VerifiedIdentity, request_hash


class Clock:
    now = 1793059200.0

    def __call__(self):
        return self.now


class SecurityTests(unittest.TestCase):
    def setUp(self):
        work = Path(os.environ.get("ASSET_LAB_TEST_ROOT", Path(__file__).resolve().parents[3] / "work" / "storage-tests")).resolve()
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.release = self.root / "release"
        self.release.mkdir()
        self.key = secrets.token_bytes(32)
        self.clock = Clock()
        self.store = Store(self.data, encryption_key=self.key, release_root=self.release, clock=self.clock)
        self.sessions = SessionService(self.store, public_origin="https://asset.example")
        self.alice, self.bob = self.sessions.create(), self.sessions.create()
        self.a, self.b = self.alice.context, self.bob.context
        self.accounts, self.selection = AccountRepository(self.store), SelectionRepository(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def raises_code(self, code, callback, *args, **kwargs):
        with self.assertRaises(StorageError) as error:
            callback(*args, **kwargs)
        self.assertEqual(error.exception.code, code)
        return error.exception

    def add_account(self, ctx=None, subject="synthetic-subject-one", **kwargs):
        kwargs.setdefault("expected_authorization_epoch", self.accounts.authorization_epoch(ctx or self.a))
        return self.accounts.complete_authorization(
            ctx or self.a, VerifiedIdentity("https://issuer.example", subject, "合成身份"),
            {"access_token": "test-access-" + subject, "refresh_token": "test-refresh-" + subject},
            minimum_read_verified=True, expires_at=self.clock() + 3600, **kwargs)

    def add_spaces(self, account, ctx=None):
        self.selection.replace_spaces(ctx or self.a, account["id"], [
            {"id": "upstream-personal", "kind": "personal", "name": "个人空间", "access": "available"},
            {"id": "upstream-team", "kind": "team", "name": "合成团队", "access": "available"}])

    def make_task(self, account, *, identifier="task_example", idempotency_key="prepare-one"):
        self.add_spaces(account)
        selected = self.selection.set(self.a, account["id"], "upstream-personal", expected_revision=self.selection.get(self.a)["revision"])
        def operation(tx):
            ownership = self.selection.bind_ownership(tx, expected_revision=selected["revision"])
            return tx.create("tasks", {"ownership": ownership, "status": "draft"}, record_id=identifier)
        return self.store.idempotency(self.a, idempotency_key, request_hash({"prompt": "synthetic"}), operation, scope="prepare-task")

    def test_cookie_and_database_never_contain_plain_session_or_provider_secrets(self):
        account = self.add_account()
        cookie = self.alice.set_cookie
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/", cookie)
        self.assertNotIn("Domain=", cookie)
        token = self.sessions.token_from_cookie(cookie)
        raw = self.store.db_path.read_bytes()
        self.assertNotIn(token.encode(), raw)
        self.assertNotIn(b"test-access-synthetic-subject-one", raw)
        self.assertNotIn(b"test-refresh-synthetic-subject-one", raw)
        self.assertNotIn(self.key, raw)
        self.assertNotIn(token, repr(self.alice))
        self.assertNotIn("access_token", json.dumps(account))
        self.assertEqual(self.accounts.credentials(self.a, account["id"])["access_token"], "test-access-synthetic-subject-one")

    def test_reload_and_new_service_restore_same_tenant_selection_and_csrf(self):
        account = self.add_account()
        task = self.make_task(account)
        restarted = Store(self.data, encryption_key=self.key, release_root=self.root / "release-v2", clock=self.clock)
        service = SessionService(restarted, public_origin="https://asset.example")
        restored = service.bootstrap(self.alice.set_cookie)
        self.assertEqual(restored.context, self.a)
        self.assertEqual(restored.data["csrfToken"], self.alice.data["csrfToken"])
        self.assertEqual(restored.data["selection"]["providerAccountId"], account["id"])
        self.assertEqual(restarted.get(restored.context, "tasks", task["id"]), task)

    def test_actual_fresh_process_can_restore_encrypted_grant_and_task(self):
        account = self.add_account()
        task = self.make_task(account)
        script = '''
import base64,json,sys
from backend.storage import Store,AccountRepository
from backend.sessions import SessionService
p=json.load(sys.stdin)
s=Store(p['data'],encryption_key=base64.b64decode(p['key']),release_root=p['release'],clock=lambda:p['now'])
r=SessionService(s,public_origin='https://asset.example').bootstrap(p['cookie'])
t=s.get(r.context,'tasks',p['task'])
secret=AccountRepository(s).credentials(r.context,p['account'])
print(json.dumps({'tenantMatches':r.context.tenantId==p['tenant'],'taskMatches':t['data']['ownership']['providerAccountId']==p['account'],'grantRestored':bool(secret.get('access_token'))}))
'''
        payload = {"data": str(self.data), "key": base64.b64encode(self.key).decode(), "release": str(self.release),
                   "now": self.clock(), "cookie": self.alice.set_cookie, "task": task["id"],
                   "account": account["id"], "tenant": self.a.tenantId}
        result = subprocess.run([sys.executable, "-c", script], input=json.dumps(payload), text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"tenantMatches": True, "taskMatches": True, "grantRestored": True})

    def test_tenants_cannot_read_write_or_remove_each_others_objects(self):
        account = self.add_account()
        task = self.make_task(account)
        blob = self.store.blob_put(self.a, b"synthetic private image", mime="image/png")
        self.raises_code("NOT_FOUND", self.accounts.get, self.b, account["id"])
        self.raises_code("NOT_FOUND", self.accounts.credentials, self.b, account["id"])
        self.raises_code("NOT_FOUND", self.accounts.remove_local, self.b, account["id"], expected_version=1)
        self.raises_code("NOT_FOUND", self.store.get, self.b, "tasks", task["id"])
        self.raises_code("NOT_FOUND", self.store.update, self.b, "tasks", task["id"], {}, expected_version=1)
        self.raises_code("NOT_FOUND", self.store.blob_get, self.b, blob["id"])
        self.raises_code("NOT_FOUND", self.selection.set, self.b, account["id"], "upstream-personal", expected_revision=0)
        self.assertEqual(self.store.list(self.b, "tasks")["items"], [])
        self.assertEqual(self.accounts.list(self.b)["items"], [])

    def test_forged_context_session_cannot_expand_tenant(self):
        forged = TenantContext(self.b.tenantId, self.a.siteSessionId)
        self.raises_code("SESSION_REQUIRED", self.store.list, forged, "tasks")
        self.raises_code("SESSION_REQUIRED", self.sessions.verify_mutation, forged,
                         origin="https://asset.example", csrf_token=self.alice.data["csrfToken"])
        self.raises_code("SESSION_REQUIRED", self.store.list, {}, "tasks")

    def test_same_official_subject_is_unique_per_tenant_not_global(self):
        first = self.add_account()
        second = self.add_account(label="重复显示名")
        b_account = self.add_account(self.b)
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["id"], b_account["id"])
        self.assertEqual(len(self.accounts.list(self.a)["items"]), 1)
        self.assertEqual(len(self.accounts.list(self.b)["items"]), 1)
        self.assertEqual(second["version"], 2)

    def test_spaces_do_not_become_login_identities(self):
        first, second = self.add_account(), self.add_account(subject="synthetic-subject-two")
        self.add_spaces(first)
        self.add_spaces(second)
        self.assertEqual(len(self.accounts.list(self.a)["items"]), 2)
        self.assertEqual(len(self.selection.list_spaces(self.a, first["id"])["items"]), 2)
        current = self.selection.set(self.a, first["id"], "upstream-team", expected_revision=0)
        switched = self.selection.set(self.a, second["id"], None, expected_revision=current["revision"])
        self.assertIsNone(switched["spaceId"])
        self.selection.replace_spaces(self.a, second["id"], [])
        self.raises_code("SPACE_UNAVAILABLE", self.selection.set, self.a, second["id"], "upstream-personal", expected_revision=switched["revision"])

    def test_unverified_subject_and_minimum_read_cannot_connect(self):
        pending = self.accounts.create_unconfigured(self.a)
        self.assertFalse(pending["identity"]["verified"])
        self.assertEqual(pending["authorization"]["state"], "unconfigured")
        self.raises_code("VALIDATION_FAILED", self.accounts.complete_authorization, self.a,
                         {"issuer": "https://issuer.example", "subject": "forged-space"}, {"access_token": "synthetic"}, minimum_read_verified=True)
        self.raises_code("IDENTITY_UNVERIFIED", self.accounts.complete_authorization, self.a,
                         VerifiedIdentity("https://issuer.example", "synthetic-subject"), {"access_token": "synthetic"})
        self.raises_code("AUTHORIZATION_REQUIRED", self.accounts.credentials, self.a, pending["id"])

    def test_reauthorization_wrong_subject_and_stale_callback_do_not_replace_secret(self):
        account = self.add_account()
        self.raises_code("OWNERSHIP_MISMATCH", self.add_account, subject="different-synthetic-subject", account_id=account["id"], expected_version=1)
        renewed = self.add_account(account_id=account["id"], expected_version=1)
        self.assertEqual(renewed["version"], 2)
        self.raises_code("VERSION_CONFLICT", self.add_account, account_id=account["id"], expected_version=1)
        self.assertEqual(self.accounts.credentials(self.a, account["id"])["access_token"], "test-access-synthetic-subject-one")

    def test_remove_invalidates_pending_add_callbacks_without_account_id(self):
        account = self.add_account()
        checkpoint = self.accounts.authorization_epoch(self.a)
        bob_checkpoint = self.accounts.authorization_epoch(self.b)
        self.accounts.remove_local(self.a, account["id"], expected_version=1)
        self.raises_code("AUTHORIZATION_ATTEMPT_INVALIDATED", self.add_account,
                         expected_authorization_epoch=checkpoint)
        self.assertEqual(self.accounts.get(self.a, account["id"])["authorization"]["state"], "removed")
        self.assertEqual(self.accounts.authorization_epoch(self.b), bob_checkpoint)
        restored = self.add_account()
        self.assertEqual(restored["id"], account["id"])

    def test_authorization_without_stored_attempt_checkpoint_is_rejected(self):
        self.raises_code("AUTHORIZATION_ATTEMPT_REQUIRED", self.accounts.complete_authorization, self.a,
                         VerifiedIdentity("https://issuer.example", "synthetic-subject"),
                         {"access_token": "synthetic"}, minimum_read_verified=True)

    def test_expired_and_revoked_authorization_never_fall_back_to_other_account(self):
        old = self.add_account()
        task = self.make_task(old)
        other = self.add_account(subject="synthetic-subject-two")
        self.add_spaces(other)
        self.selection.set(self.a, other["id"], "upstream-team", expected_revision=1)
        self.clock.now += 3601
        self.assertEqual(self.accounts.get(self.a, old["id"])["authorization"]["state"], "expired")
        self.raises_code("AUTHORIZATION_REQUIRED", self.accounts.credentials, self.a, old["id"])
        self.raises_code("AUTHORIZATION_REQUIRED", self.selection.assert_ownership_available, self.a, task["data"]["ownership"])
        self.assertIn("refresh_token", self.accounts.credentials(self.a, old["id"], for_refresh=True))
        revoked = self.accounts.mark_authorization(self.a, old["id"], "revoked", expected_version=1, reason="provider_revoked")
        self.assertEqual(revoked["authorization"]["state"], "revoked")
        self.raises_code("AUTHORIZATION_REQUIRED", self.accounts.credentials, self.a, old["id"], for_refresh=True)
        renewed = self.add_account(account_id=old["id"], expected_version=2)
        self.assertEqual(self.selection.assert_ownership_available(self.a, task["data"]["ownership"])["id"], renewed["id"])

    def test_account_remove_retains_history_and_blocks_stale_callback(self):
        account = self.add_account()
        task = self.make_task(account)
        blob = self.store.blob_put(self.a, b"historical-file", mime="image/png")
        removed = self.accounts.remove_local(self.a, account["id"], expected_version=1)
        self.assertEqual(removed["affectedTaskIds"], [task["id"]])
        self.assertNotIn("remoteRevocation", removed)
        self.assertEqual(self.store.get(self.a, "tasks", task["id"]), task)
        self.assertEqual(self.store.blob_get(self.a, blob["id"])[0], b"historical-file")
        self.assertIsNone(self.selection.get(self.a)["providerAccountId"])
        self.assertEqual(self.selection.get(self.a)["revision"], 2)
        self.raises_code("AUTHORIZATION_REQUIRED", self.accounts.credentials, self.a, account["id"])
        self.raises_code("VERSION_CONFLICT", self.add_account, account_id=account["id"], expected_version=1)
        self.raises_code("ACCOUNT_REMOVED", self.add_account, account_id=account["id"], expected_version=2)
        restored = self.add_account()
        self.assertEqual(restored["id"], account["id"])
        self.assertIsNone(restored["removedAt"])
        self.raises_code("SPACE_UNAVAILABLE", self.selection.assert_ownership_available, self.a, task["data"]["ownership"])
        self.add_spaces(restored)
        self.assertEqual(self.selection.assert_ownership_available(self.a, task["data"]["ownership"])["id"], account["id"])

    def test_task_owner_cannot_be_rewritten_after_selection_changes(self):
        account = self.add_account()
        task = self.make_task(account)
        other = self.add_account(subject="synthetic-subject-two")
        self.add_spaces(other)
        self.selection.set(self.a, other["id"], "upstream-team", expected_revision=1)
        updated = dict(task["data"])
        updated["ownership"] = dict(updated["ownership"], providerAccountId=other["id"])
        self.raises_code("OWNERSHIP_MISMATCH", self.store.update, self.a, "tasks", task["id"], updated, expected_version=1)
        updated = dict(task["data"], status="completed")
        saved = self.store.update(self.a, "tasks", task["id"], updated, expected_version=1)
        self.assertEqual(saved["data"]["ownership"], task["data"]["ownership"])

    def test_eight_concurrent_switches_have_one_winner_and_no_mixed_space(self):
        accounts = [self.add_account(subject=f"synthetic-account-{i}") for i in range(8)]
        for account in accounts:
            self.selection.replace_spaces(self.a, account["id"], [{"id": account["id"] + "_space", "kind": "personal", "name": "独立空间", "access": "available"}])
        barrier = threading.Barrier(8)
        def switch(account):
            barrier.wait()
            try:
                return self.selection.set(self.a, account["id"], account["id"] + "_space", expected_revision=0)
            except StorageError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(switch, accounts))
        winners = [item for item in results if isinstance(item, dict)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(results.count("SELECTION_CHANGED"), 7)
        self.assertEqual(winners[0]["spaceId"], winners[0]["providerAccountId"] + "_space")
        self.assertEqual(self.selection.get(self.a), winners[0])

    def test_prepare_and_switch_are_serialized_in_one_transaction(self):
        first, second = self.add_account(), self.add_account(subject="synthetic-subject-two")
        self.add_spaces(first)
        self.add_spaces(second)
        self.selection.set(self.a, first["id"], "upstream-personal", expected_revision=0)
        entered, continue_prepare = threading.Event(), threading.Event()
        def prepare():
            with self.store.transaction(self.a) as tx:
                owner = self.selection.bind_ownership(tx, expected_revision=1)
                entered.set()
                if not continue_prepare.wait(timeout=5):
                    raise RuntimeError("test synchronization timeout")
                return tx.create("tasks", {"ownership": owner, "status": "draft"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            task_future = pool.submit(prepare)
            self.assertTrue(entered.wait(timeout=5))
            switch_future = pool.submit(self.selection.set, self.a, second["id"], "upstream-team", expected_revision=1)
            continue_prepare.set()
            task, switched = task_future.result(), switch_future.result()
        self.assertEqual(task["data"]["ownership"]["providerAccountId"], first["id"])
        self.assertEqual(switched["providerAccountId"], second["id"])

    def test_record_cas_and_transaction_rollback(self):
        record = self.store.create(self.a, "projects", {"name": "合成项目"})
        self.store.update(self.a, "projects", record["id"], {"name": "新版"}, expected_version=1)
        self.raises_code("VERSION_CONFLICT", self.store.update, self.a, "projects", record["id"], {"name": "旧版覆盖"}, expected_version=1)
        try:
            with self.store.transaction(self.a) as tx:
                tx.create("projects", {"name": "应回滚"}, record_id="rollback_example")
                raise RuntimeError("simulated crash before commit")
        except RuntimeError:
            pass
        self.raises_code("NOT_FOUND", self.store.get, self.a, "projects", "rollback_example")
        self.assertEqual(self.store.get(self.a, "projects", record["id"])["data"]["name"], "新版")

    def test_concurrent_idempotency_once_survives_restart_and_is_tenant_scoped(self):
        calls, lock = [], threading.Lock()
        def operation(tx):
            with lock:
                calls.append(1)
            return tx.create("tasks", {"status": "draft"})
        def run(_):
            return self.store.idempotency(self.a, "same-key", request_hash({"synthetic": True}), operation, scope="prepare")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, range(8)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({item["id"] for item in results}), 1)
        restarted = Store(self.data, encryption_key=self.key, release_root=self.release, clock=self.clock)
        replay = restarted.idempotency(self.a, "same-key", request_hash({"synthetic": True}), operation, scope="prepare")
        self.assertEqual(replay, results[0])
        self.assertEqual(len(calls), 1)
        self.raises_code("IDEMPOTENCY_CONFLICT", self.store.idempotency, self.a, "same-key", request_hash({"changed": True}), operation, scope="prepare")
        other = self.store.idempotency(self.b, "same-key", request_hash({"synthetic": True}), operation, scope="prepare")
        self.assertNotEqual(other["id"], replay["id"])

    def test_failed_idempotent_operation_rolls_back_its_object(self):
        def fail(tx):
            tx.create("tasks", {"status": "draft"}, record_id="failed_task")
            raise RuntimeError("synthetic failure")
        with self.assertRaises(RuntimeError):
            self.store.idempotency(self.a, "retryable-key", request_hash({}), fail, scope="prepare")
        self.raises_code("NOT_FOUND", self.store.get, self.a, "tasks", "failed_task")
        def retry(tx):
            return tx.create("tasks", {"status": "draft"}, record_id="failed_task")
        self.assertEqual(self.store.idempotency(self.a, "retryable-key", request_hash({}), retry, scope="prepare")["id"], "failed_task")

    def test_csrf_and_origin_both_required_and_bound_to_session(self):
        self.sessions.verify_mutation(self.a, origin="https://asset.example", csrf_token=self.alice.data["csrfToken"])
        for origin, csrf in [(None, self.alice.data["csrfToken"]), ("https://other.example", self.alice.data["csrfToken"]),
                             ("https://asset.example", self.bob.data["csrfToken"]), ("https://asset.example", "非 ASCII"),
                             ("https://asset.example", None), ("https://asset.example.evil", self.alice.data["csrfToken"])]:
            self.raises_code("CSRF_FAILED", self.sessions.verify_mutation, self.a, origin=origin, csrf_token=csrf)

    def test_logout_revokes_site_session_without_deleting_customer_or_provider_data(self):
        account = self.add_account()
        task = self.make_task(account)
        cookie = self.sessions.logout(self.a)
        self.assertIn("Max-Age=0", cookie)
        self.raises_code("SESSION_REQUIRED", self.sessions.bootstrap, self.alice.set_cookie)
        self.raises_code("SESSION_REQUIRED", self.store.get, self.a, "tasks", task["id"])
        worker = TenantContext(self.a.tenantId)  # trusted worker context, never HTTP input
        self.assertEqual(self.store.get(worker, "tasks", task["id"]), task)
        self.assertIn("access_token", self.accounts.credentials(worker, account["id"]))
        fresh = self.sessions.create()
        self.assertNotEqual(fresh.context.tenantId, self.a.tenantId)
        self.raises_code("NOT_FOUND", self.store.get, fresh.context, "tasks", task["id"])

    def test_rotation_preserves_tenant_and_invalidates_old_session_csrf(self):
        rotated = self.sessions.rotate(self.a)
        self.assertEqual(rotated.context.tenantId, self.a.tenantId)
        self.assertNotEqual(rotated.context.siteSessionId, self.a.siteSessionId)
        self.raises_code("SESSION_REQUIRED", self.sessions.bootstrap, self.alice.set_cookie)
        self.raises_code("CSRF_FAILED", self.sessions.verify_mutation, rotated.context,
                         origin="https://asset.example", csrf_token=self.alice.data["csrfToken"])
        self.assertEqual(self.sessions.bootstrap(rotated.set_cookie).context, rotated.context)

    def test_idle_and_absolute_expiry_and_cookie_fixation(self):
        service = SessionService(self.store, public_origin="https://asset.example", idle_seconds=60, absolute_seconds=120)
        initial = service.create()
        self.clock.now += 50
        service.bootstrap(initial.set_cookie)
        self.clock.now += 50
        service.bootstrap(initial.set_cookie)
        self.clock.now += 20
        self.raises_code("SESSION_REQUIRED", service.bootstrap, initial.set_cookie)
        idle = service.create()
        self.clock.now += 61
        self.raises_code("SESSION_REQUIRED", service.bootstrap, idle.set_cookie)
        self.raises_code("SESSION_REQUIRED", service.bootstrap, "__Host-asset_lab_session=" + "a" * 43)
        self.raises_code("SESSION_REQUIRED", service.bootstrap, "__Host-asset_lab_session=" + "a" * 43 + "; __Host-asset_lab_session=" + "b" * 43)

    def test_secure_cookie_required_except_explicit_loopback_development(self):
        self.raises_code("ORIGIN_INVALID", SessionService, self.store, public_origin="http://public.example")
        service = SessionService(self.store, public_origin="http://127.0.0.1:18873")
        cookie = service.create().set_cookie
        self.assertNotIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertTrue(cookie.startswith("asset_lab_session="))

    def test_encryption_is_bound_to_tenant_and_namespace_and_wrong_key_fails_closed(self):
        with self.store.transaction(self.a) as tx:
            tx.secret_put("test-secrets", "secret_example", {"access_token": "synthetic-super-secret"})
        # Simulate a corrupted backup transplanting Alice's ciphertext into Bob's row.
        with self.store._system_transaction() as conn:
            sealed = conn.execute("SELECT ciphertext FROM secrets WHERE tenant_id=?", (self.a.tenantId,)).fetchone()[0]
            conn.execute("INSERT INTO secrets VALUES(?,?,?,?)", (self.b.tenantId, "test-secrets", "secret_example", sealed))
        with self.store.transaction(self.b, readonly=True) as tx:
            error = self.raises_code("SECRET_UNAVAILABLE", tx.secret_get, "test-secrets", "secret_example")
            self.assertNotIn("synthetic-super-secret", str(error))
        self.raises_code("SECRET_UNAVAILABLE", Store, self.data, encryption_key=secrets.token_bytes(32), release_root=self.release)

    def test_private_modes_external_data_key_and_schema_fail_closed(self):
        self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.db_path.stat().st_mode), 0o600)
        self.raises_code("UNSAFE_DATA_PATH", Store, self.release / "runtime", encryption_key=self.key, release_root=self.release)
        self.raises_code("UNSAFE_DATA_PATH", Store, "relative-data", encryption_key=self.key, release_root=self.release)
        self.raises_code("STORAGE_UNCONFIGURED", Store.from_env, environ={})
        key_file = self.root / "outside-data-key"
        key_file.write_bytes(base64.b64encode(self.key))
        key_file.chmod(0o600)
        loaded = Store.from_env(environ={"ASSET_LAB_DATA_DIR": str(self.data), "ASSET_LAB_SECRET_KEY_FILE": str(key_file)}, release_root=self.release)
        self.assertEqual(loaded.data_dir, self.data)
        key_file.chmod(0o644)
        self.raises_code("UNSAFE_SECRET_PATH", Store.from_env, environ={"ASSET_LAB_DATA_DIR": str(self.data), "ASSET_LAB_SECRET_KEY_FILE": str(key_file)}, release_root=self.release)
        self.raises_code("UNSAFE_SECRET_PATH", Store.from_env, environ={"ASSET_LAB_DATA_DIR": str(self.data), "ASSET_LAB_SECRET_KEY_FILE": str(self.data / "key")}, release_root=self.release)
        with self.store._system_transaction() as conn:
            conn.execute("PRAGMA user_version=999")
        self.raises_code("SCHEMA_INCOMPATIBLE", Store, self.data, encryption_key=self.key, release_root=self.release)

    def test_blob_integrity_path_traversal_symlinks_and_hardlinks(self):
        blob = self.store.blob_put(self.a, b"abc", mime="image/png")
        path = self.data / "tenants" / self.a.tenantId / "blobs" / blob["id"]
        self.raises_code("VALIDATION_FAILED", self.store.blob_get, self.a, "../../private")
        path.write_bytes(b"abd")
        self.raises_code("BLOB_INTEGRITY_FAILED", self.store.blob_get, self.a, blob["id"])
        path.unlink()
        outside = self.root / "outside"
        outside.write_bytes(b"abc")
        outside.chmod(0o600)
        path.symlink_to(outside)
        self.raises_code("BLOB_UNAVAILABLE", self.store.blob_get, self.a, blob["id"])
        path.unlink()
        os.link(outside, path)
        self.raises_code("BLOB_INTEGRITY_FAILED", self.store.blob_get, self.a, blob["id"])
        path.unlink()
        directory = path.parent
        directory.rmdir()
        directory.symlink_to(self.root, target_is_directory=True)
        self.raises_code("BLOB_UNAVAILABLE", self.store.blob_put, self.a, b"cannot escape")

    def test_metadata_rejects_secrets_unsafe_ids_and_cross_tenant_owners(self):
        self.raises_code("VALIDATION_FAILED", self.store.create, self.a, "projects", {"accessToken": "synthetic-secret"})
        self.raises_code("VALIDATION_FAILED", self.store.create, self.a, "projects", {"name": "x"}, record_id="../escape")
        self.raises_code("OWNERSHIP_MISMATCH", self.store.create, self.a, "tasks", {"ownership": {"tenantId": self.b.tenantId}})
        self.raises_code("VALIDATION_FAILED", self.store.create, self.a, "projects", {"name": float("nan")})

    def test_worker_lease_fencing_prevents_stale_worker_writes(self):
        with self.store.transaction(self.a) as tx:
            old = tx.claim_lease("task_example", "worker_one", ttl=5)
        with self.store.transaction(self.a) as tx:
            self.raises_code("LEASE_BUSY", tx.claim_lease, "task_example", "worker_two", ttl=5)
        self.clock.now += 6
        with self.store.transaction(self.a) as tx:
            new = tx.claim_lease("task_example", "worker_two", ttl=5)
            self.assertGreater(new["fence"], old["fence"])
            self.raises_code("LEASE_LOST", tx.assert_lease, "task_example", "worker_one", old["fence"])
            tx.release_lease("task_example", "worker_two", new["fence"])
        with self.store.transaction(self.a) as tx:
            third = tx.claim_lease("task_example", "worker_one", ttl=5)
            self.assertGreater(third["fence"], new["fence"])

    def test_route_contract_and_logout_reject_client_tenant(self):
        class Router:
            def __init__(self):
                self.routes = {}
            def add(self, method, path, handler):
                self.routes[(method, path)] = handler
        router = Router()
        register_routes(router, {"sessions": self.sessions})
        response = router.routes[("GET", "/api/v1/session")]({"requestId": "request_test", "headers": {"Cookie": self.alice.set_cookie}}, {})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["data"]["tenant"]["id"], self.a.tenantId)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        ctx = {"tenantId": self.a.tenantId, "siteSessionId": self.a.siteSessionId, "requestId": "request_test",
               "headers": {"Origin": "https://asset.example", "X-CSRF-Token": self.alice.data["csrfToken"]}, "json": {"tenantId": self.b.tenantId}}
        handler = router.routes[("POST", "/api/v1/session/logout")]
        self.raises_code("VALIDATION_FAILED", handler, ctx, {})
        ctx["json"] = {}
        response = handler(ctx, {})
        self.assertTrue(response.body["data"]["loggedOut"])
        self.raises_code("SESSION_REQUIRED", self.sessions.bootstrap, self.alice.set_cookie)


if __name__ == "__main__":
    unittest.main()
