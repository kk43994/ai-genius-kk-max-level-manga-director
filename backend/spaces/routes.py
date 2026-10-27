"""Framework-neutral routes; mount through the integration HTTP adapter."""
from dataclasses import dataclass, field as dataclass_field

from .errors import SpaceError
from .service import field, require_tenant


@dataclass(frozen=True)
class Response:
    status: int
    body: dict
    headers: dict = dataclass_field(default_factory=lambda: {"Cache-Control": "no-store"})


def register_routes(router, services):
    service = field(services, "spaces")

    def handler(operation, *, write=False):
        def handle(ctx, params):
            meta = {"requestId": field(ctx, "requestId"), "apiVersion": 1}
            try:
                require_tenant(ctx)
                if service is None:
                    raise SpaceError("NOT_IMPLEMENTED", "空间资料模块尚未接入。", status=501)
                if write and field(ctx, "csrfVerified") is not True:
                    raise SpaceError("CSRF_FAILED", "请刷新页面后重试。", status=403)
                value = operation(service, ctx, params)
                return Response(200, {"data": value, "meta": meta})
            except SpaceError as error:
                return Response(error.status, {"error": {"code": error.code,
                    "message": error.message, "retryable": error.retryable, "details": {}}, "meta": meta})
        return handle

    router.add("GET", "/api/v1/provider-accounts/{id}/spaces", handler(
        lambda service, ctx, p: service.list_spaces(ctx, p["id"])))
    router.add("GET", "/api/v1/provider-accounts/{id}/spaces/{spaceId}/quota", handler(
        lambda service, ctx, p: service.quota(ctx, p["id"], p["spaceId"])))
    router.add("GET", "/api/v1/provider-accounts/{id}/spaces/{spaceId}/models", handler(
        lambda service, ctx, p: service.list_models(ctx, p["id"], p["spaceId"])))

    def selection(service, ctx, params):
        body = field(ctx, "json")
        required = {"providerAccountId", "spaceId", "expectedRevision"}
        if not isinstance(body, dict) or set(body) != required:
            raise SpaceError("VALIDATION_FAILED", "请选择账号、空间及对应版本。", status=422)
        return service.set_selection(ctx, **body)

    router.add("PUT", "/api/v1/selection", handler(selection, write=True))
