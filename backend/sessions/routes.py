"""Thin framework-independent adapters; the integration owns the public server."""
from dataclasses import dataclass, field as dataclass_field

from backend.storage.core import field
from backend.storage.errors import invalid

PUBLIC_ROUTES = frozenset({("GET", "/api/v1/session")})


@dataclass
class Response:
    status: int
    body: dict
    headers: dict = dataclass_field(default_factory=dict, repr=False)


def header(ctx, name):
    headers = field(ctx, "headers", {}) or {}
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def register_routes(router, services):
    sessions = field(services, "sessions")

    def session(ctx, params):
        result = sessions.bootstrap(header(ctx, "Cookie"), request_id=field(ctx, "requestId", ""))
        return Response(200, {"data": result.data,
                              "meta": {"requestId": field(ctx, "requestId", ""), "apiVersion": 1}},
                        {"Set-Cookie": result.set_cookie, "Cache-Control": "no-store",
                         "Vary": "Cookie", "Pragma": "no-cache"})

    def logout(ctx, params):
        body = field(ctx, "json", {}) or {}
        if not isinstance(body, dict) or body:
            raise invalid("注销接口不接受账号或客户标识")
        # Defense in depth: do not trust a forged ctx.csrfVerified flag.
        sessions.verify_mutation(ctx, origin=header(ctx, "Origin"), csrf_token=header(ctx, "X-CSRF-Token"))
        cookie = sessions.logout(ctx)
        return Response(200, {"data": {"loggedOut": True},
                              "meta": {"requestId": field(ctx, "requestId", ""), "apiVersion": 1}},
                        {"Set-Cookie": cookie, "Cache-Control": "no-store"})

    router.add("GET", "/api/v1/session", session)
    # Additive route to v1: the base contract required logout handling but did not
    # name a URL. The integrator must expose this route with normal session/CSRF.
    router.add("POST", "/api/v1/session/logout", logout)

    recovery = field(services, "workspace_recovery")
    if recovery is None:
        return  # Do not advertise recovery routes until the provider hook is wired.

    def recovery_response(ctx, data, session=None):
        headers = {"Cache-Control": "no-store", "Vary": "Cookie"}
        if session is not None:
            headers["Set-Cookie"] = session.set_cookie
        return Response(200, {"data": data, "meta": {"requestId": field(ctx, "requestId", ""), "apiVersion": 1}}, headers)

    def confirm(ctx, params):
        body = field(ctx, "json")
        allowed = {"action", "workspaceId", "expectedVersion", "expectedContentRevision", "draftDisposition", "savedDrafts"}
        if not isinstance(body, dict) or not set(body) <= allowed:
            raise invalid()
        result = recovery.confirm(ctx, params["id"], action=body.get("action"),
                                  workspace_id=body.get("workspaceId"), expected_version=body.get("expectedVersion"),
                                  expected_content_revision=body.get("expectedContentRevision"),
                                  draft_disposition=body.get("draftDisposition"), saved_drafts=body.get("savedDrafts"))
        return recovery_response(ctx, result.data, result.session)

    def cancel(ctx, params):
        if field(ctx, "json", {}) != {}:
            raise invalid()
        return recovery_response(ctx, recovery.cancel(ctx, params["id"]))

    router.add("GET", "/api/v1/workspace", lambda ctx, params: recovery_response(ctx, recovery.repo.get(ctx)))
    router.add("GET", "/api/v1/workspace-intents/{id}",
               lambda ctx, params: recovery_response(ctx, recovery.get_intent(ctx, params["id"])))
    router.add("POST", "/api/v1/workspace-intents/{id}/confirm", confirm)
    router.add("POST", "/api/v1/workspace-intents/{id}/cancel", cancel)
