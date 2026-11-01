"""Local OS-approved workspace handoff; no HTTP operation can approve a target.

An authenticated browser requests a switch. A trusted local launcher/operator
with access to the instance database approves one project, for that exact browser
session and five minutes. The browser then saves its drafts and confirms. This
does not bind an OAuth owner, move records or copy provider grants. Bound workspaces
must continue to use official owner recovery instead of this local migration path.
"""
import json

from .sessions import Response
from .storage import StorageError, TenantContext
from .storage.core import checked_id, opaque_id
from .storage.workspaces import WorkspaceRepository

COLLECTION = "local.workspace_handoffs"


class LocalWorkspaceService:
    def __init__(self, app):
        if not app.config.local_client or app.config.host != "127.0.0.1":
            raise ValueError("Workspace handoff is available only to a local instance")
        self.store, self.sessions = app.services.storage, app.services.sessions

    def _unbound(self, conn, workspace):
        if WorkspaceRepository.owner(conn, workspace):
            raise StorageError("OWNER_RECOVERY_REQUIRED", "已绑定主账号的工作区需要使用官方身份验证恢复", 409)

    def _record(self, tx, ctx, identifier):
        record = tx.get(COLLECTION, checked_id(identifier))
        if record["data"]["sourceSessionId"] != ctx.siteSessionId:
            raise StorageError("NOT_FOUND", "没有当前页面的切换申请", 404)
        if record["data"]["expiresAt"] <= self.store.clock():
            raise StorageError("LOCAL_SWITCH_EXPIRED", "本次切换已过期，请重新准备", 410)
        return record

    @staticmethod
    def public(record):
        data = record["data"]
        return {"id": record["id"], "version": record["version"], "status": data["status"],
                "projectName": data.get("projectName"), "projectId": data.get("projectId")}

    def begin(self, ctx):
        with self.store.transaction(ctx) as tx:
            self.sessions._require(tx._conn, ctx)
            self._unbound(tx._conn, ctx.tenantId)
            active = tx._conn.execute(
                "SELECT id FROM records WHERE tenant_id=? AND collection=? "
                "AND json_extract(data,'$.sourceSessionId')=? "
                "AND json_extract(data,'$.expiresAt')>? "
                "AND json_extract(data,'$.status') IN ('pending','approved') ORDER BY created_at DESC LIMIT 1",
                (ctx.tenantId, COLLECTION, ctx.siteSessionId, self.store.clock())).fetchone()
            if active:
                return self.public(tx.get(COLLECTION, active["id"]))
            record = tx.create(COLLECTION, {"sourceSessionId": ctx.siteSessionId,
                "status": "pending", "expiresAt": self.store.clock() + 300},
                record_id=opaque_id("lws"), immutable_fields=("sourceSessionId", "expiresAt"))
            return self.public(record)

    def read(self, ctx, identifier):
        with self.store.transaction(ctx, readonly=True) as tx:
            return self.public(self._record(tx, ctx, identifier))

    def approve_from_local_operator(self, identifier, project_id):
        """Trusted OS entry only. Intentionally not registered as an HTTP route."""
        checked_id(identifier); checked_id(project_id)
        with self.store._system_transaction(write=False) as conn:
            row = conn.execute("SELECT tenant_id,data FROM records WHERE collection=? AND id=?",
                               (COLLECTION, identifier)).fetchone()
            if row is None:
                raise StorageError("NOT_FOUND", "没有该本机切换申请", 404)
            ctx = TenantContext(row["tenant_id"], json.loads(row["data"])["sourceSessionId"], "local-os-approval")
        with self.store.transaction(ctx) as tx:
            record = self._record(tx, ctx, identifier)
            if record["data"]["status"] != "pending":
                raise StorageError("LOCAL_SWITCH_STATE", "切换申请已处理，不能重新指定目标", 409)
            targets = tx._conn.execute("SELECT tenant_id,data FROM records WHERE collection='workflow.projects' AND id=?",
                                      (project_id,)).fetchall()
            if len(targets) != 1:
                raise StorageError("NOT_FOUND", "目标项目不存在或不唯一", 404)
            target = targets[0]
            self._unbound(tx._conn, ctx.tenantId)
            self._unbound(tx._conn, target["tenant_id"])
            if target["tenant_id"] == ctx.tenantId:
                raise StorageError("LOCAL_SWITCH_SAME_WORKSPACE", "目标项目已经在当前工作区，请直接选择项目", 409)
            updated = tx.update(COLLECTION, identifier, {**record["data"], "status": "approved",
                "targetWorkspaceId": target["tenant_id"], "projectId": project_id,
                "projectName": json.loads(target["data"])["name"], "approvedAt": self.store.clock()},
                expected_version=record["version"])
            return self.public(updated)

    def cancel(self, ctx, identifier):
        with self.store.transaction(ctx) as tx:
            record = self._record(tx, ctx, identifier)
            if record["data"]["status"] not in ("pending", "approved"):
                raise StorageError("LOCAL_SWITCH_STATE", "该切换申请已处理", 409)
            return self.public(tx.update(COLLECTION, identifier, {**record["data"], "status": "cancelled"},
                expected_version=record["version"]))

    def confirm(self, ctx, identifier, expected_version, draft_version):
        if type(expected_version) is not int or type(draft_version) is not int or draft_version < 1:
            raise StorageError("DRAFT_SAVE_REQUIRED", "请先保存当前草稿再切换", 409)
        with self.store.transaction(ctx) as tx:
            old = self.sessions._require(tx._conn, ctx)
            record = self._record(tx, ctx, identifier)
            data = record["data"]
            if record["version"] != expected_version or data["status"] != "approved":
                raise StorageError("LOCAL_SWITCH_NOT_APPROVED", "尚未收到本机对这个目标工作区的确认", 409)
            draft = tx.get("drafts", "browser_drafts_v1")
            if draft["version"] != draft_version:
                raise StorageError("DRAFT_SAVE_REQUIRED", "草稿已变化，请重新保存后切换", 409)
            target = data["targetWorkspaceId"]
            self._unbound(tx._conn, ctx.tenantId); self._unbound(tx._conn, target)
            if not tx._conn.execute("SELECT 1 FROM records WHERE tenant_id=? AND collection='workflow.projects' AND id=?",
                                    (target, data["projectId"])).fetchone():
                raise StorageError("NOT_FOUND", "目标项目已变化，请重新核对", 404)
            now = self.store.clock()
            tx.update(COLLECTION, identifier, {**data, "status": "consumed", "consumedAt": now},
                      expected_version=record["version"])
            row, token = self.sessions._insert(tx._conn, target, now)
            tx._conn.execute("UPDATE site_sessions SET revoked_at=? WHERE id=?", (now, old["id"]))
        session = self.sessions._result(row, token, request_id=ctx.requestId)
        return Response(200, {"data": {"switched": True, "projectId": data["projectId"],
                        "projectName": data["projectName"], "sourceWorkspacePreserved": True}},
                        {"Set-Cookie": session.set_cookie, "Cache-Control": "no-store"})


def register_routes(app):
    service = LocalWorkspaceService(app)
    app.services.local_workspace = service

    def begin(ctx, params):
        if ctx.json != {"confirmLocalSwitch": True}:
            raise StorageError("VALIDATION_FAILED", "需要明确准备本机工作区切换", 422)
        return service.begin(ctx)

    def confirm(ctx, params):
        if not isinstance(ctx.json, dict) or set(ctx.json) != {"expectedVersion", "savedDraftVersion"}:
            raise StorageError("VALIDATION_FAILED", "请通过当前页面核对切换", 422)
        return service.confirm(ctx, params["id"], ctx.json["expectedVersion"], ctx.json["savedDraftVersion"])

    app.router.add("POST", "/api/v1/local-workspace-intents", begin)
    app.router.add("GET", "/api/v1/local-workspace-intents/{id}", lambda ctx, p: service.read(ctx, p["id"]))
    app.router.add("POST", "/api/v1/local-workspace-intents/{id}/confirm", confirm)
    app.router.add("POST", "/api/v1/local-workspace-intents/{id}/cancel", lambda ctx, p: service.cancel(ctx, p["id"]))
