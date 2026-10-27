"""Actual SQLite/session/blob recovery with synthetic, server-issued OAuth evidence.

These tests are NOT evidence of a real LibTV login. The auth module must run its
own state/PKCE/official identity tests and wire only its verified callback here.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import base64
import hashlib
import json
import secrets
import sqlite3
import subprocess
import sys
import threading
import unittest

from backend.sessions import FreshOwnerProof, SessionService, WorkspaceRecoveryService, register_routes
from backend.storage import AccountRepository, Store, TenantContext, WorkspaceRepository
from backend.storage.core import canonical_json, utc
from backend.storage.schema import STATEMENTS
from backend.storage.workspaces import OWNER_ISSUER

try:
    from . import test_security as fixtures
except ImportError:
    import test_security as fixtures


class WorkspaceRecoveryTests(unittest.TestCase):
    setUp = fixtures.SecurityTests.setUp
    tearDown = fixtures.SecurityTests.tearDown
    raises_code = fixtures.SecurityTests.raises_code
    add_account = fixtures.SecurityTests.add_account
    add_spaces = fixtures.SecurityTests.add_spaces
    make_task = fixtures.SecurityTests.make_task

    @property
    def recovery(self):
        return WorkspaceRecoveryService(self.store, self.sessions)

    @staticmethod
    def context(session):
        return {"tenantId": session.context.tenantId, "siteSessionId": session.context.siteSessionId,
                "headers": {"Origin": "https://asset.example", "X-CSRF-Token": session.data["csrfToken"]},
                "csrfVerified": True, "requestId": "synthetic-recovery"}

    def start(self, session, purpose, *, unsaved=False, label="合成工作区"):
        ctx = self.context(session)
        attempt, state_hash = "oa_" + secrets.token_hex(16), hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        request = self.recovery.begin(ctx, purpose=purpose, authorization_attempt_id=attempt,
                                      oauth_state_hash=state_hash, has_unsaved_changes=unsaved, workspace_label=label)
        return ctx, request, attempt, state_hash

    def proof(self, ctx, attempt, state_hash, subject):
        return FreshOwnerProof(attempt, state_hash, ctx["siteSessionId"], OWNER_ISSUER, subject,
                               self.clock(), self.clock(), "authorization_code", True, True, True)

    def complete(self, started, subject="owner-one", **overrides):
        ctx, request, attempt, state_hash = started
        proof = replace(self.proof(ctx, attempt, state_hash, subject), **overrides)
        return self.recovery.accept_verified_authorization(ctx, intent_id=request.intent_id, nonce=request.nonce, proof=proof)

    def bind(self, session, subject="owner-one", *, label="合成工作区"):
        started = self.start(session, "bind_owner", label=label)
        result = self.complete(started, subject)
        if result.data["status"] == "awaiting_confirmation":
            result = self.confirm(started, action="bind_current")
        self.assertEqual(result.data["status"], "bound")
        return result.session

    def confirm(self, started, *, action="recover", workspace_id=None, disposition="none", saved=None):
        ctx, request, _, _ = started
        pending = self.recovery.get_intent(ctx, request.intent_id)
        return self.recovery.confirm(ctx, request.intent_id, action=action, workspace_id=workspace_id,
                                     expected_version=pending["version"],
                                     expected_content_revision=pending["sourceWorkspace"]["content"]["revision"],
                                     draft_disposition=disposition, saved_drafts=saved)

    def test_clear_cookie_recovery_preserves_project_blob_task_owner_and_selection(self):
        account = self.add_account()
        task = self.make_task(account)
        project = self.store.create(self.a, "projects", {"name": "待找回项目"})
        blob = self.store.blob_put(self.a, b"synthetic saved asset", mime="image/png")
        owner = self.bind(self.alice)
        self.assertNotEqual(owner.context.siteSessionId, self.a.siteSessionId)
        self.raises_code("SESSION_REQUIRED", self.sessions.bootstrap, self.alice.set_cookie)
        # No cookie: a fresh anonymous workspace. No tenant/subject is accepted here.
        fresh = self.sessions.bootstrap()
        self.assertNotEqual(fresh.context.tenantId, owner.context.tenantId)
        recovered = self.complete(self.start(fresh, "recover_workspace"))
        self.assertEqual(recovered.data["status"], "recovered")
        ctx = recovered.session.context
        self.assertEqual(ctx.tenantId, owner.context.tenantId)
        self.assertEqual(self.store.get(ctx, "projects", project["id"]), project)
        self.assertEqual(self.store.get(ctx, "tasks", task["id"]), task)
        self.assertEqual(self.store.blob_get(ctx, blob["id"])[0], b"synthetic saved asset")
        self.assertEqual(recovered.session.data["selection"]["providerAccountId"], account["id"])
        self.raises_code("SESSION_REQUIRED", self.sessions.bootstrap, fresh.set_cookie)

    def test_expired_site_session_can_recover_only_through_new_oauth(self):
        owner = self.bind(self.alice)
        self.clock.now += 31 * 86400
        self.raises_code("SESSION_REQUIRED", self.sessions.bootstrap, owner.set_cookie)
        anonymous = self.sessions.create()
        recovered = self.complete(self.start(anonymous, "recover_workspace"))
        self.assertEqual(recovered.session.context.tenantId, owner.context.tenantId)

    def test_generation_accounts_are_not_owners_and_cannot_find_workspace(self):
        attached = self.add_account(subject="attached-provider")
        owner = self.bind(self.alice, "owner-one")
        fresh = self.sessions.create()
        result = self.complete(self.start(fresh, "recover_workspace"), "attached-provider")
        self.assertEqual(result.data["status"], "not_found")
        self.assertIsNone(result.session)
        self.assertNotIn(owner.context.tenantId, json.dumps(result.data))
        self.raises_code("NOT_FOUND", self.accounts.get, fresh.context, attached["id"])

    def test_regular_provider_identity_never_auto_binds_workspace(self):
        account = self.add_account(subject="ordinary-provider")
        self.assertTrue(account["identity"]["verified"])
        self.assertFalse(WorkspaceRepository(self.store).get(self.a)["ownerBound"])
        fresh = self.sessions.create()
        result = self.complete(self.start(fresh, "recover_workspace"), "ordinary-provider")
        self.assertEqual(result.data["error"]["code"], "OWNER_WORKSPACE_NOT_FOUND")

    def test_removing_owner_generation_account_does_not_transfer_or_destroy_ownership(self):
        primary_account = self.add_account(subject="owner-one")
        attached = self.add_account(subject="attached-provider")
        owner = self.bind(self.alice)
        self.accounts.remove_local(owner.context, primary_account["id"], expected_version=1)
        self.accounts.remove_local(owner.context, attached["id"], expected_version=1)
        result = self.complete(self.start(self.sessions.create(), "recover_workspace"))
        self.assertEqual(result.session.context.tenantId, owner.context.tenantId)
        # Recovery proves website ownership; it must not revive removed generator grants.
        self.assertEqual(self.accounts.get(result.session.context, primary_account["id"])["authorization"]["state"], "removed")
        self.raises_code("AUTHORIZATION_REQUIRED", self.accounts.credentials, result.session.context, primary_account["id"])

    def test_bound_source_cannot_be_transferred_to_different_owner(self):
        alice = self.bind(self.alice, "owner-one")
        bob = self.bind(self.bob, "owner-two")
        for purpose in ("bind_owner", "recover_workspace"):
            result = self.complete(self.start(alice, purpose), "owner-two")
            self.assertEqual(result.data["status"], "blocked")
            self.assertIsNone(result.session)
            self.assertNotIn(bob.context.tenantId, json.dumps(result.data))
        self.assertEqual(WorkspaceRepository(self.store).get(alice.context)["owner"]["subject"], "owner-one")

    def test_two_workspaces_same_owner_require_selection_and_foreign_choice_fails(self):
        first = self.bind(self.alice, label="第一个工作区")
        started = self.start(self.bob, "bind_owner", label="第二个工作区")
        pending = self.complete(started)
        self.assertEqual(pending.data["status"], "awaiting_confirmation")
        self.assertIn("owner_has_existing_workspaces", pending.data["reasons"])
        second = self.confirm(started, action="bind_current").session
        foreign = self.bind(self.sessions.create(), "owner-two")
        started = self.start(self.sessions.create(), "recover_workspace")
        pending = self.complete(started)
        self.assertEqual({x["id"] for x in pending.data["candidates"]}, {first.context.tenantId, second.context.tenantId})
        self.assertNotIn(foreign.context.tenantId, json.dumps(pending.data))
        self.raises_code("WORKSPACE_CHOICE_INVALID", self.confirm, started, workspace_id=foreign.context.tenantId)
        result = self.confirm(started, workspace_id=second.context.tenantId)
        self.assertEqual(result.session.context.tenantId, second.context.tenantId)

    def test_anonymous_content_is_not_silently_replaced_or_orphaned(self):
        owner = self.bind(self.alice)
        draft = self.store.create(self.b, "projects", {"name": "匿名新项目"})
        started = self.start(self.bob, "recover_workspace", label="保留的新项目工作区")
        result = self.complete(started)
        self.assertEqual(result.data["status"], "awaiting_confirmation")
        self.assertIn("current_workspace_has_content", result.data["reasons"])
        self.assertIsNone(result.session)
        self.assertEqual(self.store.get(self.b, "projects", draft["id"]), draft)
        self.raises_code("SOURCE_WORKSPACE_REQUIRES_PRESERVATION", self.confirm, started, workspace_id=owner.context.tenantId)
        preserved = self.confirm(started, action="recover_preserve_current", workspace_id=owner.context.tenantId)
        self.assertTrue(preserved.data["sourceWorkspacePreserved"])
        self.assertEqual(preserved.session.context.tenantId, owner.context.tenantId)
        # Recover again: preserved anonymous workspace is now explicitly selectable.
        choose = self.start(self.sessions.create(), "recover_workspace")
        pending = self.complete(choose)
        self.assertEqual({x["id"] for x in pending.data["candidates"]}, {owner.context.tenantId, self.b.tenantId})
        restored_draft = self.confirm(choose, workspace_id=self.b.tenantId)
        self.assertEqual(self.store.get(restored_draft.session.context, "projects", draft["id"]), draft)

    def test_unsaved_drafts_require_persisted_version_before_switch(self):
        owner = self.bind(self.alice)
        started = self.start(self.bob, "recover_workspace", unsaved=True)
        pending = self.complete(started)
        self.assertEqual(pending.data["status"], "awaiting_confirmation")
        self.raises_code("DRAFT_SAVE_REQUIRED", self.confirm, started,
                         action="recover_preserve_current", workspace_id=owner.context.tenantId)
        self.raises_code("DRAFT_SAVE_REQUIRED", self.confirm, started,
                         action="recover_preserve_current", workspace_id=owner.context.tenantId, disposition="saved", saved=[])
        saved = self.store.create(self.b, "drafts", {"prompt": "浏览器当前未保存文本"})
        refs = [{"collection": "drafts", "id": saved["id"], "version": saved["version"]}]
        result = self.confirm(started, action="recover_preserve_current", workspace_id=owner.context.tenantId,
                              disposition="saved", saved=refs)
        self.assertEqual(result.data["status"], "recovered")
        # No copy/merge into the old owner workspace. The preserved workspace is separate.
        self.raises_code("NOT_FOUND", self.store.get, result.session.context, "drafts", saved["id"])
        self.assertEqual(self.store.get(TenantContext(self.b.tenantId), "drafts", saved["id"]), saved)

    def test_changed_source_and_changed_saved_draft_cannot_pass_old_confirmation(self):
        owner = self.bind(self.alice)
        started = self.start(self.bob, "recover_workspace", unsaved=True)
        pending = self.complete(started)
        saved = self.store.create(self.b, "drafts", {"text": "first"})
        self.raises_code("WORKSPACE_CONTENT_CHANGED", self.recovery.confirm, started[0], started[1].intent_id,
                         action="recover_preserve_current", workspace_id=owner.context.tenantId,
                         expected_version=pending.data["version"],
                         expected_content_revision=pending.data["sourceWorkspace"]["content"]["revision"],
                         draft_disposition="saved", saved_drafts=[{"collection": "drafts", "id": saved["id"], "version": 1}])
        self.store.update(self.b, "drafts", saved["id"], {"text": "second"}, expected_version=1)
        self.raises_code("DRAFT_VERSION_CHANGED", self.confirm, started, action="recover_preserve_current",
                         workspace_id=owner.context.tenantId, disposition="saved",
                         saved=[{"collection": "drafts", "id": saved["id"], "version": 1}])

    def test_only_same_session_can_complete_or_inspect_intent(self):
        started = self.start(self.alice, "bind_owner")
        proof = self.proof(started[0], started[2], started[3], "owner-one")
        self.raises_code("NOT_FOUND", self.recovery.accept_verified_authorization, self.context(self.bob),
                         intent_id=started[1].intent_id, nonce=started[1].nonce, proof=proof)
        self.raises_code("NOT_FOUND", self.recovery.get_intent, self.context(self.bob), started[1].intent_id)
        self.raises_code("NOT_FOUND", self.recovery.cancel, self.context(self.bob), started[1].intent_id)

    def test_invalid_state_nonce_proof_type_old_grant_and_wrong_issuer_fail_closed(self):
        started = self.start(self.alice, "bind_owner")
        ctx, ticket, attempt, state = started
        good = self.proof(ctx, attempt, state, "owner-one")
        self.raises_code("WORKSPACE_PROOF_INVALID", self.recovery.accept_verified_authorization, ctx,
                         intent_id=ticket.intent_id, nonce=secrets.token_urlsafe(32), proof=good)
        for change in ({"oauth_state_hash": "0" * 64}, {"site_session_id": self.b.siteSessionId},
                       {"authorization_attempt_id": "oa_other"}, {"issuer": "https://wrong.example"},
                       {"grant_type": "refresh_token"}, {"state_verified": False}, {"pkce_verified": False},
                       {"authoritative_identity_read": False}, {"subject": ""}):
            self.raises_code("WORKSPACE_PROOF_INVALID", self.recovery.accept_verified_authorization, ctx,
                             intent_id=ticket.intent_id, nonce=ticket.nonce, proof=replace(good, **change))
        self.raises_code("WORKSPACE_PROOF_INVALID", self.recovery.accept_verified_authorization, ctx,
                         intent_id=ticket.intent_id, nonce=ticket.nonce, proof=asdict(good))
        self.assertFalse(WorkspaceRepository(self.store).get(self.a)["ownerBound"])

    def test_freshness_expiry_and_consumed_callback_replay(self):
        started = self.start(self.alice, "bind_owner", unsaved=None)
        ctx, ticket, attempt, state = started
        old = self.proof(ctx, attempt, state, "owner-one")
        self.clock.now += 61
        self.raises_code("WORKSPACE_PROOF_STALE", self.recovery.accept_verified_authorization, ctx,
                         intent_id=ticket.intent_id, nonce=ticket.nonce, proof=old)
        result = self.complete(started)
        self.assertEqual(result.data["status"], "awaiting_confirmation")
        self.raises_code("WORKSPACE_AUTHORIZATION_REPLAYED", self.complete, started)
        self.clock.now += 301
        self.raises_code("WORKSPACE_AUTHORIZATION_EXPIRED", self.confirm, started, action="bind_current")

    def test_cancelled_or_logged_out_intent_cannot_recover(self):
        started = self.start(self.alice, "bind_owner")
        result = self.recovery.cancel(started[0], started[1].intent_id)
        self.assertEqual(result["status"], "cancelled")
        self.raises_code("WORKSPACE_AUTHORIZATION_REPLAYED", self.complete, started)
        started = self.start(self.bob, "bind_owner")
        self.sessions.logout(self.b)
        self.raises_code("SESSION_REQUIRED", self.complete, started)

    def test_begin_confirm_cancel_require_origin_and_session_csrf(self):
        ctx = self.context(self.alice)
        ctx["headers"]["Origin"] = "https://untrusted.example"
        self.raises_code("CSRF_FAILED", self.recovery.begin, ctx, purpose="bind_owner",
                         authorization_attempt_id="oa_new", oauth_state_hash="a" * 64)
        started = self.start(self.alice, "bind_owner", unsaved=None)
        pending = self.complete(started)
        started[0]["headers"]["X-CSRF-Token"] = self.bob.data["csrfToken"]
        self.raises_code("CSRF_FAILED", self.confirm, started, action="bind_current")
        self.raises_code("CSRF_FAILED", self.recovery.cancel, started[0], started[1].intent_id)
        self.assertFalse(WorkspaceRepository(self.store).get(self.a)["ownerBound"])

    def test_pending_confirmation_survives_service_restart_without_reusing_oauth(self):
        owner = self.bind(self.alice)
        started = self.start(self.bob, "recover_workspace", unsaved=None)
        pending = self.complete(started)
        self.assertEqual(pending.data["status"], "awaiting_confirmation")
        restarted = Store(self.data, encryption_key=self.key, release_root=self.root / "release-next", clock=self.clock)
        sessions = SessionService(restarted, public_origin="https://asset.example")
        restored = sessions.bootstrap(self.bob.set_cookie)
        service = WorkspaceRecoveryService(restarted, sessions)
        state = service.get_intent(self.context(restored), started[1].intent_id)
        result = service.confirm(self.context(restored), started[1].intent_id, action="recover",
                                 workspace_id=owner.context.tenantId, expected_version=state["version"],
                                 expected_content_revision=state["sourceWorkspace"]["content"]["revision"],
                                 draft_disposition="none")
        self.assertEqual(result.session.context.tenantId, owner.context.tenantId)

    def test_eight_duplicate_callbacks_rotate_only_one_session(self):
        owner = self.bind(self.alice)
        started = self.start(self.bob, "recover_workspace")
        barrier = threading.Barrier(8)
        def finish(_):
            barrier.wait()
            try:
                return self.complete(started)
            except Exception as error:
                return error.code
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(finish, range(8)))
        winners = [item for item in results if not isinstance(item, str)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].session.context.tenantId, owner.context.tenantId)
        self.assertEqual(results.count("SESSION_REQUIRED"), 7)

    def test_migration_preserves_v1_records_and_never_infers_owner_from_provider(self):
        path = self.root / "v1-data"
        path.mkdir(mode=0o700)
        with sqlite3.connect(path / "state.sqlite3") as conn:
            for statement in STATEMENTS:
                conn.execute(statement)
            probe = self.store._seal("system", "key-check", "v1", {"check": "asset-lab-storage-v1"})
            conn.execute("INSERT INTO settings VALUES('key_check',?)", (probe,))
            conn.execute("INSERT INTO tenants VALUES('tenant_legacy',?)", (utc(self.clock()),))
            conn.execute("INSERT INTO records VALUES('tenant_legacy','projects','project_legacy',1,?, '[]',?,?,NULL)",
                         (canonical_json({"name": "legacy"}), utc(self.clock()), utc(self.clock())))
            conn.execute("""INSERT INTO provider_accounts(tenant_id,id,provider,issuer,subject,label,verified,state,version,created_at,updated_at)
                VALUES('tenant_legacy','pa_legacy','libtv',?,'owner-one','旧账号',1,'connected',1,?,?)""", (OWNER_ISSUER, utc(self.clock()), utc(self.clock())))
            conn.execute("PRAGMA user_version=1")
        migrated = Store(path, encryption_key=self.key, release_root=self.release, clock=self.clock)
        legacy = TenantContext("tenant_legacy")
        self.assertEqual(migrated.get(legacy, "projects", "project_legacy")["data"]["name"], "legacy")
        self.assertFalse(WorkspaceRepository(migrated).get(legacy)["ownerBound"])
        with migrated._system_transaction(write=False) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_restart_new_process_can_finish_verified_recovery(self):
        owner = self.bind(self.alice)
        started = self.start(self.bob, "recover_workspace")
        proof = self.proof(started[0], started[2], started[3], "owner-one")
        script = '''
import base64,json,sys
from backend.storage import Store
from backend.sessions import SessionService,WorkspaceRecoveryService,FreshOwnerProof
p=json.load(sys.stdin)
s=Store(p['path'],encryption_key=base64.b64decode(p['key']),release_root=p['release'],clock=lambda:p['now'])
sessions=SessionService(s,public_origin='https://asset.example')
restored=sessions.bootstrap(p['cookie'])
ctx={'tenantId':restored.context.tenantId,'siteSessionId':restored.context.siteSessionId}
result=WorkspaceRecoveryService(s,sessions).accept_verified_authorization(ctx,intent_id=p['intent'],nonce=p['nonce'],proof=FreshOwnerProof(**p['proof']))
print(json.dumps({'status':result.data['status'],'targetMatches':result.session.context.tenantId==p['target'],'ownerBound':result.session.data['workspace']['ownerBound']}))
'''
        payload = {"path": str(self.data), "key": base64.b64encode(self.key).decode(), "release": str(self.release),
                   "now": self.clock(), "cookie": self.bob.set_cookie, "intent": started[1].intent_id,
                   "nonce": started[1].nonce, "proof": asdict(proof), "target": owner.context.tenantId}
        result = subprocess.run([sys.executable, "-c", script], input=json.dumps(payload), text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"status": "recovered", "targetMatches": True, "ownerBound": True})

    def test_owner_identity_cannot_be_deleted_or_changed_by_account_cleanup(self):
        owner = self.bind(self.alice)
        for statement in ("DELETE FROM workspace_owners WHERE tenant_id=?",
                          "UPDATE workspace_owners SET subject='attached' WHERE tenant_id=?"):
            with self.assertRaises(sqlite3.IntegrityError):
                with self.store._system_transaction() as conn:
                    conn.execute(statement, (owner.context.tenantId,))
        self.assertEqual(WorkspaceRepository(self.store).get(owner.context)["owner"]["subject"], "owner-one")

    def test_browser_cannot_submit_owner_proof_or_ids_to_confirmation_route(self):
        class Router:
            def __init__(self):
                self.routes = {}
            def add(self, method, path, handler):
                self.routes[(method, path)] = handler
        router = Router()
        register_routes(router, {"sessions": self.sessions, "workspace_recovery": self.recovery})
        self.assertNotIn(("POST", "/api/v1/workspace-intents"), router.routes)
        handler = router.routes[("POST", "/api/v1/workspace-intents/{id}/confirm")]
        ctx = self.context(self.alice)
        for body in ({"subject": "owner-one"}, {"providerAccountId": "pa_fake"}, {"tenantId": self.b.tenantId}, {"proof": {"state_verified": True}}):
            ctx["json"] = body
            self.raises_code("VALIDATION_FAILED", handler, ctx, {"id": "wi_fake"})


if __name__ == "__main__":
    unittest.main()
