"""Explicit owner binding/recovery after a NEW verified OAuth code exchange.

This service is not an OAuth verifier. Only the auth callback may construct
FreshOwnerProof, after state/session/PKCE and an authoritative official identity
read. No HTTP endpoint accepts proof, issuer, subject, nonce or provider account ID.
"""
from dataclasses import dataclass, field as datafield
import hashlib
import hmac
import math
import re
import secrets
import sqlite3

from backend.storage.core import canonical_json, checked_id, field, opaque_id, utc
from backend.storage.errors import StorageError, conflict, invalid
from backend.storage.workspaces import OWNER_ISSUER, OWNER_PROVIDER, WorkspaceRepository
from .routes import header

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True, repr=False)
class FreshOwnerProof:
    authorization_attempt_id: str
    oauth_state_hash: str
    site_session_id: str
    issuer: str
    subject: str
    code_exchanged_at: float
    identity_verified_at: float
    grant_type: str
    state_verified: bool
    pkce_verified: bool
    authoritative_identity_read: bool

    def __repr__(self):
        return "<FreshOwnerProof server-only>"


@dataclass(frozen=True)
class OwnerAuthorizationRequest:
    intent_id: str
    purpose: str
    expires_at: str
    nonce: str = datafield(repr=False)

    def public(self):
        return {"intentId": self.intent_id, "purpose": self.purpose, "expiresAt": self.expires_at}


@dataclass(frozen=True)
class RecoveryResult:
    data: dict
    session: object | None = datafield(default=None, repr=False)


def _error(code, message, status=409):
    return StorageError(code, message, status)


class WorkspaceRecoveryService:
    def __init__(self, store, sessions, *, intent_ttl=600, proof_ttl=300):
        if store is not sessions.store or not 60 <= intent_ttl <= 900 or not 30 <= proof_ttl <= 600:
            raise ValueError("Invalid recovery storage or lifetime")
        self.store, self.sessions = store, sessions
        self.repo = WorkspaceRepository(store)
        self.intent_ttl, self.proof_ttl = intent_ttl, proof_ttl

    def _mutation(self, ctx):
        self.sessions.verify_mutation(ctx, origin=header(ctx, "Origin"), csrf_token=header(ctx, "X-CSRF-Token"))

    def begin(self, ctx, *, purpose, authorization_attempt_id, oauth_state_hash,
              has_unsaved_changes=None, workspace_label="我的工作区"):
        """Called by auth.begin AFTER generating its state/attempt, BEFORE redirect.

        Persist the returned intent_id + nonce inside that attempt's encrypted
        private payload. The nonce is a server-side intent challenge, not an OIDC
        nonce and not a browser parameter. Normal provider-add must not call here.
        """
        self._mutation(ctx)
        if purpose not in {"bind_owner", "recover_workspace"}:
            raise invalid("需要明确选择绑定主所有者或找回工作区")
        checked_id(authorization_attempt_id)
        if not isinstance(oauth_state_hash, str) or not _HASH.fullmatch(oauth_state_hash):
            raise invalid("缺少本次 OAuth state 绑定")
        if has_unsaved_changes is not None and type(has_unsaved_changes) is not bool:
            raise invalid()
        if (not isinstance(workspace_label, str) or not 1 <= len(workspace_label.strip()) <= 120
                or any(ord(c) < 32 for c in workspace_label)):
            raise invalid()
        now, identifier, nonce = self.store.clock(), opaque_id("wi"), secrets.token_urlsafe(32)
        with self.store.transaction(ctx) as tx:
            session = self.sessions._require(tx._conn, ctx)
            active = tx._conn.execute("SELECT count(*) FROM workspace_intents WHERE tenant_id=? AND site_session_id=? AND status IN ('pending','awaiting_confirmation') AND expires_at>?",
                                      (tx.tenant_id, session["id"], now)).fetchone()[0]
            if active >= 3:
                raise _error("WORKSPACE_AUTHORIZATION_BUSY", "请先完成或取消已有的工作区授权", 429)
            data = {"clientHasUnsavedChanges": has_unsaved_changes,
                    "workspaceLabel": workspace_label.strip(),
                    "initialContentRevision": self.repo.content(tx._conn, tx.tenant_id)["revision"]}
            try:
                tx._conn.execute("INSERT INTO workspace_intents VALUES(?,?,?,?,?,?,?,'pending',1,?,?,?)",
                                 (identifier, tx.tenant_id, session["id"], authorization_attempt_id,
                                  hashlib.sha256(nonce.encode()).hexdigest(), oauth_state_hash, purpose,
                                  now, now + self.intent_ttl, canonical_json(data)))
            except sqlite3.IntegrityError:
                raise _error("WORKSPACE_AUTHORIZATION_REPLAYED", "该次 OAuth 已绑定其他工作区意图") from None
        return OwnerAuthorizationRequest(identifier, purpose, utc(now + self.intent_ttl), nonce)

    def _proof(self, row, ctx, nonce, proof):
        now = self.store.clock()
        if row["status"] != "pending":
            raise _error("WORKSPACE_AUTHORIZATION_REPLAYED", "该次工作区授权已消费")
        if row["expires_at"] <= now:
            raise _error("WORKSPACE_AUTHORIZATION_EXPIRED", "工作区授权已过期，请重新授权", 410)
        if (not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)
                or not hmac.compare_digest(row["nonce_hash"], hashlib.sha256(nonce.encode()).hexdigest())):
            raise _error("WORKSPACE_PROOF_INVALID", "工作区授权校验失败", 403)
        if (not isinstance(proof, FreshOwnerProof) or proof.grant_type != "authorization_code"
                or proof.state_verified is not True or proof.pkce_verified is not True
                or proof.authoritative_identity_read is not True
                or proof.authorization_attempt_id != row["oauth_attempt_id"]
                or proof.site_session_id != field(ctx, "siteSessionId")
                or proof.oauth_state_hash != row["state_hash"] or proof.issuer != OWNER_ISSUER
                or not isinstance(proof.subject, str) or not 1 <= len(proof.subject) <= 512
                or any(ord(c) < 32 for c in proof.subject)):
            raise _error("WORKSPACE_PROOF_INVALID", "工作区需要新的官方身份验证", 403)
        times = (proof.code_exchanged_at, proof.identity_verified_at)
        if (any(type(value) not in (int, float) or not math.isfinite(value) for value in times)
                or not row["created_at"] <= times[0] <= times[1] <= now
                or now - times[1] > 60):
            raise _error("WORKSPACE_PROOF_STALE", "官方身份验证已过时，请重新授权", 403)

    def _public(self, conn, row):
        data = self.repo.data(row)
        result = {"id": row["id"], "purpose": row["purpose"], "status": row["status"],
                  "version": row["version"], "expiresAt": utc(row["expires_at"]),
                  "workspaceId": data.get("resultWorkspaceId"), "error": data.get("error")}
        if row["status"] == "awaiting_confirmation":
            result.update(reasons=data["confirmationReasons"], proofExpiresAt=utc(data["proofExpiresAt"]),
                          sourceWorkspace=self.repo.summary(conn, row["tenant_id"]),
                          candidates=[self.repo.summary(conn, tenant) for tenant in data["candidates"]])
        return result

    def _result(self, data, new_session):
        if new_session is None:
            return RecoveryResult(data)
        row, token, request_id = new_session
        return RecoveryResult(data, self.sessions._result(row, token, request_id=request_id))

    def _finish(self, conn, row, data, target, ctx, *, newly_bound=False, source_preserved=False):
        target_owner = self.repo.owner(conn, target)
        identity = data["verifiedIdentity"]
        if not self.repo.matches(target_owner, identity["issuer"], identity["subject"]):
            raise _error("WORKSPACE_OWNER_MISMATCH", "不能访问其他主所有者的工作区", 403)
        now = self.store.clock()
        if newly_bound:
            # Drop all pre-binding source sessions; no anonymous session inherits
            # ownership merely by having existed before the fresh proof.
            conn.execute("UPDATE site_sessions SET revoked_at=? WHERE tenant_id=? AND revoked_at IS NULL", (now, row["tenant_id"]))
        else:
            conn.execute("UPDATE site_sessions SET revoked_at=? WHERE id=?", (now, row["site_session_id"]))
        new_row, token = self.sessions._insert(conn, target, now)
        data.update(resultWorkspaceId=target, sourcePreserved=source_preserved)
        status = "bound" if row["purpose"] == "bind_owner" else "recovered"
        self.repo.update(conn, row, status, data)
        result = {"id": row["id"], "purpose": row["purpose"], "status": status,
                  "workspaceId": target, "sourceWorkspacePreserved": source_preserved,
                  "version": row["version"] + 1, "error": None}
        return result, (new_row, token, field(ctx, "requestId", ""))

    def accept_verified_authorization(self, ctx, *, intent_id, nonce, proof):
        """Server-only callback hook after fresh official exchange + identity read.

        Consume the auth attempt's state before this hook, outside an open Store
        transaction. For owner intents do not attach a generation account/grant.
        A success rotates the source session, so this must be the last operation
        requiring the old ctx. The returned session cookie MUST reach the browser.
        """
        new_session = None
        with self.store.transaction(ctx) as tx:
            self.sessions._require(tx._conn, ctx)
            row = self.repo.intent(tx._conn, ctx, intent_id)
            self._proof(row, ctx, nonce, proof)
            data = self.repo.data(row)
            data.update(verifiedIdentity={"provider": OWNER_PROVIDER, "issuer": proof.issuer, "subject": proof.subject},
                        proofExpiresAt=min(row["expires_at"], self.store.clock() + self.proof_ttl),
                        verifiedAt=proof.identity_verified_at)
            source_owner = self.repo.owner(tx._conn, tx.tenant_id)
            if source_owner and not self.repo.matches(source_owner, proof.issuer, proof.subject):
                data["error"] = {"code": "WORKSPACE_OWNER_MISMATCH", "message": "当前工作区已有其他主所有者，不能转移或跨所有者恢复"}
                self.repo.update(tx._conn, row, "blocked", data)
            else:
                candidates = [item[0] for item in self.repo.candidates(tx._conn, proof.issuer, proof.subject)]
                data["candidates"] = candidates
                content = self.repo.content(tx._conn, tx.tenant_id)
                if row["purpose"] == "bind_owner":
                    reasons = []
                    if any(tenant != tx.tenant_id for tenant in candidates):
                        reasons.append("owner_has_existing_workspaces")
                    if data["clientHasUnsavedChanges"] is not False:
                        reasons.append("unsaved_or_unknown_browser_drafts")
                    if reasons:
                        data["confirmationReasons"] = reasons
                        self.repo.update(tx._conn, row, "awaiting_confirmation", data)
                    else:
                        self.repo.bind(tx._conn, tx.tenant_id, proof.issuer, proof.subject,
                                       label=data["workspaceLabel"], authorization_attempt_id=row["oauth_attempt_id"])
                        result, new_session = self._finish(tx._conn, row, data, tx.tenant_id, ctx,
                                                           newly_bound=source_owner is None, source_preserved=True)
                elif not candidates:
                    data["error"] = {"code": "OWNER_WORKSPACE_NOT_FOUND", "message": "此官方身份未绑定为工作区主所有者"}
                    self.repo.update(tx._conn, row, "not_found", data)
                else:
                    reasons = []
                    if len(candidates) > 1:
                        reasons.append("choose_existing_workspace")
                    if content["hasContent"] and candidates != [tx.tenant_id]:
                        reasons.append("current_workspace_has_content")
                    if data["clientHasUnsavedChanges"] is not False:
                        reasons.append("unsaved_or_unknown_browser_drafts")
                    if reasons:
                        data["confirmationReasons"] = reasons
                        self.repo.update(tx._conn, row, "awaiting_confirmation", data)
                    else:
                        result, new_session = self._finish(tx._conn, row, data, candidates[0], ctx,
                                                           source_preserved=source_owner is not None)
            if new_session is None:
                result = self._public(tx._conn, self.repo.intent(tx._conn, ctx, intent_id))
        return self._result(result, new_session)

    def get_intent(self, ctx, intent_id):
        with self.store.transaction(ctx, readonly=True) as tx:
            self.sessions._require(tx._conn, ctx)
            result = self._public(tx._conn, self.repo.intent(tx._conn, ctx, intent_id))
            if result["status"] in {"pending", "awaiting_confirmation"}:
                deadline = result.get("proofExpiresAt", result["expiresAt"])
                if deadline <= utc(self.store.clock()):
                    result.update(status="expired", candidates=[])
            return result

    def cancel(self, ctx, intent_id):
        self._mutation(ctx)
        with self.store.transaction(ctx) as tx:
            row = self.repo.intent(tx._conn, ctx, intent_id)
            if row["status"] in {"pending", "awaiting_confirmation"}:
                self.repo.update(tx._conn, row, "cancelled", self.repo.data(row))
            return self._public(tx._conn, self.repo.intent(tx._conn, ctx, intent_id))

    def _saved_drafts(self, tx, row, data, disposition, references):
        if disposition not in {"none", "saved"}:
            raise invalid("请明确确认当前草稿已保存或没有未保存草稿")
        if data["clientHasUnsavedChanges"] is True and disposition != "saved":
            raise _error("DRAFT_SAVE_REQUIRED", "请先保存当前浏览器草稿，再恢复旧工作区")
        if disposition == "saved":
            if not isinstance(references, list) or not 1 <= len(references) <= 100:
                raise _error("DRAFT_SAVE_REQUIRED", "需要当前工作区已持久化的草稿版本")
            if self.repo.content(tx._conn, tx.tenant_id)["revision"] <= data["initialContentRevision"]:
                raise _error("DRAFT_SAVE_REQUIRED", "尚未观察到本次草稿保存")
            for reference in references:
                if not isinstance(reference, dict) or set(reference) != {"collection", "id", "version"}:
                    raise invalid()
                record = tx.get(reference["collection"], reference["id"])
                if (type(reference["version"]) is not int or record["version"] != reference["version"]
                        or record["updatedAt"] < utc(row["created_at"])):
                    raise conflict("DRAFT_VERSION_CHANGED")
        elif references:
            raise invalid()

    def confirm(self, ctx, intent_id, *, action, workspace_id=None, expected_version,
                expected_content_revision, draft_disposition=None, saved_drafts=None):
        self._mutation(ctx)
        with self.store.transaction(ctx) as tx:
            self.sessions._require(tx._conn, ctx)
            row = self.repo.intent(tx._conn, ctx, intent_id)
            data = self.repo.data(row)
            if row["status"] != "awaiting_confirmation":
                raise _error("WORKSPACE_CONFIRMATION_UNAVAILABLE", "该次授权当前不能确认")
            if type(expected_version) is not int or row["version"] != expected_version:
                raise conflict()
            if min(row["expires_at"], data["proofExpiresAt"]) <= self.store.clock():
                raise _error("WORKSPACE_AUTHORIZATION_EXPIRED", "身份确认已过期，请重新授权", 410)
            content = self.repo.content(tx._conn, tx.tenant_id)
            if type(expected_content_revision) is not int or content["revision"] != expected_content_revision:
                raise conflict("WORKSPACE_CONTENT_CHANGED")
            identity = data["verifiedIdentity"]
            source_owner = self.repo.owner(tx._conn, tx.tenant_id)
            if source_owner and not self.repo.matches(source_owner, identity["issuer"], identity["subject"]):
                raise _error("WORKSPACE_OWNER_MISMATCH", "工作区主所有者不一致", 403)
            newly_bound = False
            if row["purpose"] == "bind_owner":
                if action != "bind_current" or workspace_id is not None:
                    raise invalid("绑定意图只能确认当前工作区，找回需另行发起")
                target, preserved = tx.tenant_id, True
                self.repo.bind(tx._conn, target, identity["issuer"], identity["subject"],
                               label=data["workspaceLabel"], authorization_attempt_id=row["oauth_attempt_id"])
                newly_bound = source_owner is None
            else:
                if action not in {"recover", "recover_preserve_current"} or workspace_id not in data["candidates"]:
                    raise _error("WORKSPACE_CHOICE_INVALID", "请选择本次验证返回的工作区", 403)
                target = workspace_id
                if not self.repo.matches(self.repo.owner(tx._conn, target), identity["issuer"], identity["subject"]):
                    raise _error("WORKSPACE_OWNER_MISMATCH", "不能恢复其他主所有者的工作区", 403)
                self._saved_drafts(tx, row, data, draft_disposition, saved_drafts)
                preserved = source_owner is not None or target == tx.tenant_id
                if target != tx.tenant_id:
                    if action == "recover_preserve_current":
                        self.repo.bind(tx._conn, tx.tenant_id, identity["issuer"], identity["subject"],
                                       label=data["workspaceLabel"], authorization_attempt_id=row["oauth_attempt_id"])
                        newly_bound, preserved = source_owner is None, True
                    elif content["hasContent"] or draft_disposition == "saved":
                        raise _error("SOURCE_WORKSPACE_REQUIRES_PRESERVATION", "当前工作区有内容，请明确选择保留当前工作区后恢复")
            result, new_session = self._finish(tx._conn, row, data, target, ctx,
                                               newly_bound=newly_bound, source_preserved=preserved)
        return self._result(result, new_session)
