"""Register only module-owned task routes; the app owns envelope/session/CSRF."""

from dataclasses import dataclass, field as dataclass_field

from .errors import TaskError
from .model import field


@dataclass
class Response:
    status: int
    body: dict
    headers: dict = dataclass_field(default_factory=dict)


def register_routes(router, services):
    service = field(services, "tasks")

    def wrap(action, *, mutation=False):
        def handler(ctx, params):
            try:
                if mutation and field(ctx, "csrfVerified") is not True:
                    raise TaskError("CSRF_FAILED", "请求来源校验失败。", 403)
                if service is None:
                    raise TaskError("NOT_IMPLEMENTED", "任务模块尚未接入。", 501)
                return Response(200, {"data": action(ctx, params)})
            except TaskError as exc:
                return Response(exc.status, {"error": exc.public()})
            except Exception as exc:
                # Dependencies may fail before a task is persisted. Do not let
                # raw provider/DB error strings reach the common HTTP adapter.
                safe = {
                    "PROVIDER_ACCOUNT_READ_UNAVAILABLE": ("PROVIDER_ACCOUNT_READ_UNAVAILABLE", "LibTV 暂时无法读取原账号资料。已有任务保留，请稍后刷新账号或收取原任务。", 503),
                    "SESSION_REQUIRED": ("SESSION_REQUIRED", "请恢复本站会话后继续。", 401),
                    "NOT_FOUND": ("NOT_FOUND", "项目、账号或参考素材不存在。", 404),
                    "VALIDATION_FAILED": ("VALIDATION_FAILED", "任务参数或参考素材未通过校验。", 422),
                    "VERSION_CONFLICT": ("VERSION_CONFLICT", "资产记录已变化，请重新读取后准备任务。", 409),
                    "PROVIDER_AUTHORIZATION_REQUIRED": ("PROVIDER_AUTHORIZATION_REQUIRED", "请恢复原账号授权。", 409),
                    "PROVIDER_UNCONFIGURED": ("PROVIDER_UNCONFIGURED", "官方接入尚未配置完成。", 503),
                    "PROVIDER_CAPABILITY_UNAVAILABLE": ("PROVIDER_CAPABILITY_UNAVAILABLE", "官方接口尚未支持此步骤。", 503),
                    "SPACE_UNAVAILABLE": ("SPACE_UNAVAILABLE", "原空间访问权限尚未确认。", 409),
                    "PROVIDER_UNAVAILABLE": ("PROVIDER_UNAVAILABLE", "暂未收到 LibTV 的响应。请刷新连接和原任务状态，不要重复提交生成。", 503),
                    "PROVIDER_NETWORK_ERROR": ("PROVIDER_UNAVAILABLE", "暂未收到 LibTV 的响应。请刷新连接和原任务状态，不要重复提交生成。", 503),
                    "STORAGE_UNAVAILABLE": ("STORAGE_UNAVAILABLE", "本地任务记录暂时无法读取，请刷新任务状态；不要重复提交生成。", 503),
                }
                error = TaskError(*safe.get(getattr(exc, "code", None),
                                  ("TASK_SERVICE_UNAVAILABLE", "任务服务暂不可用，请保留当前页面后稍后重试。", 503)))
                return Response(error.status, {"error": error.public()})
        return handler

    def body(ctx, allowed):
        value = field(ctx, "json")
        if not isinstance(value, dict) or set(value) - set(allowed):
            raise TaskError("VALIDATION_FAILED", "请求字段不符合任务协议。", 422)
        return value

    def idempotency(ctx):
        headers = field(ctx, "headers", {})
        return next((v for k, v in headers.items() if k.lower() == "idempotency-key"), None)

    def prepare(ctx, params):
        value = body(ctx, {"projectId", "recipe", "entityId", "prompt", "sourceRevisionIds", "settings", "expectedSelectionRevision"})
        return service.prepare(ctx, {k: v for k, v in value.items() if k != "expectedSelectionRevision"},
                               value.get("expectedSelectionRevision"), idempotency(ctx))

    def submit(ctx, params):
        value = body(ctx, {"expectedVersion", "confirmationToken"})
        return service.submit(ctx, params["taskId"], value.get("expectedVersion"),
                              value.get("confirmationToken"), idempotency(ctx))

    def task_action(name):
        def action(ctx, params):
            value = body(ctx, {"expectedVersion"})
            return getattr(service, name)(ctx, params["taskId"], value.get("expectedVersion"))
        return action

    def listing(ctx, params):
        query = field(ctx, "query", {}) or {}
        if set(query) - {"projectId", "providerAccountId", "spaceId", "cursor", "limit"}:
            raise TaskError("VALIDATION_FAILED", "任务筛选参数无效。", 422)
        try:
            limit = int(query.get("limit", 50))
        except (ValueError, TypeError):
            raise TaskError("VALIDATION_FAILED", "分页数量无效。", 422) from None
        return service.list(ctx, **{k: query[k] for k in ("projectId", "providerAccountId", "spaceId", "cursor") if k in query}, limit=limit)

    router.add("POST", "/api/v1/tasks/prepare", wrap(prepare, mutation=True))
    router.add("GET", "/api/v1/tasks", wrap(listing))
    router.add("GET", "/api/v1/tasks/{taskId}", wrap(lambda ctx, params: service.get(ctx, params["taskId"])))
    router.add("POST", "/api/v1/tasks/{taskId}/submit", wrap(submit, mutation=True))
    router.add("POST", "/api/v1/tasks/{taskId}/recover", wrap(task_action("recover"), mutation=True))
    router.add("POST", "/api/v1/tasks/{taskId}/cancel", wrap(task_action("cancel"), mutation=True))
    # Minimal v1 additive extension: after switching the UI selection or a
    # confirmation expiring, show/reconfirm this task's ORIGINAL owner.
    router.add("POST", "/api/v1/tasks/{taskId}/confirm", wrap(task_action("confirm"), mutation=True))
