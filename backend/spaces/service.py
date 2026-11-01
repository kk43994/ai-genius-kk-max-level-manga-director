"""Tenant-scoped, read-only LibTV account/space/entitlement adapter."""
from collections.abc import Mapping
from copy import deepcopy

from .errors import SpaceError, call_provider, unavailable
from . import normalize


def field(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def require_tenant(ctx):
    tenant_id = field(ctx, "tenantId")
    if not normalize.identifier(tenant_id):
        raise SpaceError("SESSION_REQUIRED", "请重新打开工作台以恢复站点会话。", status=401)
    return tenant_id


def require_id(value):
    if not normalize.identifier(value):
        raise SpaceError("VALIDATION_FAILED", "请选择明确的账号和空间。", status=422)


class SpaceService:
    """providers follows docs/api-contract.md; selections is SelectionRepository.

    No credentials, process environment, server default account, shared mutable
    provider selection, or quota cache is accessed by this module.
    """

    def __init__(self, providers, selections=None, *, clock=normalize.utc_now,
                 quota_max_age_seconds=120, space_max_age_seconds=120):
        self.providers = providers
        self.selections = selections
        self.clock = clock
        self.quota_max_age_seconds = quota_max_age_seconds
        self.space_max_age_seconds = space_max_age_seconds

    def _store(self, method, *args, **kwargs):
        operation = getattr(self.selections, method, None)
        if not callable(operation):
            raise unavailable()
        try:
            return operation(*args, **kwargs)
        except SpaceError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            if code in {"VERSION_CONFLICT", "SELECTION_CHANGED"}:
                raise SpaceError("SELECTION_CHANGED", "账号选择已被其他页面更新，请刷新后重试。", status=409) from None
            if code == "NOT_FOUND":
                raise SpaceError("NOT_FOUND", "未找到此账号或空间。", status=404) from None
            if code in {"AUTHORIZATION_REQUIRED", "SPACE_UNAVAILABLE", "OWNERSHIP_MISMATCH"}:
                raise SpaceError(code, "账号或空间状态已变化，请重新核对。", status=409) from None
            raise SpaceError("STORAGE_UNAVAILABLE", "账号选择或空间资料尚未保存，请稍后重试。", retryable=True) from None

    def _account(self, ctx, account_id):
        tenant_id = require_tenant(ctx)
        require_id(account_id)
        account = call_provider(self.providers, "get_account", ctx, account_id)
        if (not isinstance(account, dict) or account.get("id") != account_id
                or ("tenantId" in account and account["tenantId"] != tenant_id)
                or account.get("provider") != "libtv"):
            raise SpaceError("NOT_FOUND", "未找到此账号。", status=404)
        authorization = account.get("authorization")
        if not isinstance(authorization, dict):
            raise normalize.invalid_response()
        if account.get("removedAt") is not None or authorization.get("state") == "removed":
            raise SpaceError("NOT_FOUND", "未找到此账号。", status=404)
        # Expiry is a presentation state: the bound auth client may still rotate
        # a valid refresh grant. It must validate/refresh before any identity or
        # space read. Revoked/error/unconfigured accounts remain blocked here.
        if authorization.get("state") not in ("connected", "expired"):
            raise SpaceError("PROVIDER_AUTHORIZATION_REQUIRED", "请先完成此 LibTV 账号的官方授权。", status=409)
        identity = normalize.identity(account.get("identity"))
        return account, identity

    def _client(self, ctx, account, identity, space=None):
        ownership = {"tenantId": require_tenant(ctx), "provider": "libtv",
                     "providerAccountId": account["id"], "providerSubject": identity["subject"],
                     "providerIssuer": identity["issuer"],
                     "spaceId": space["id"] if space else None,
                     "spaceKind": space["kind"] if space else None}
        # Space discovery necessarily precedes space selection. The auth module
        # must expose an account-only reader; never fabricate a space/default to
        # satisfy a task client's mandatory ownership.spaceId.
        method = "client_for" if space else "account_client_for"
        client = call_provider(self.providers, method, ctx, deepcopy(ownership))
        current = call_provider(client, "identity")
        normalize.check_scope(current, ownership["tenantId"], account["id"], ownership["spaceId"])
        verified = normalize.identity(current)
        if (verified["issuer"], verified["subject"]) != (identity["issuer"], identity["subject"]):
            raise SpaceError("OWNERSHIP_MISMATCH", "授权返回的登录身份已变化，请重新核对账号。", status=409)
        return client, verified

    def profile(self, ctx, account_id):
        account, identity = self._account(ctx, account_id)
        _, verified = self._client(ctx, account, identity)
        return {"providerAccountId": account_id, "identity": verified,
                "checkedAt": normalize.iso(self.clock()), "officialViewUrl": normalize.OFFICIAL_VIEW_URL}

    def _spaces(self, ctx, account, identity):
        try:
            client, _ = self._client(ctx, account, identity)
            payload = call_provider(client, "list_spaces")
            if isinstance(payload, dict):
                normalize.check_scope(payload, require_tenant(ctx), account["id"])
            result = normalize.spaces(payload, self.clock())
            for row in payload if isinstance(payload, list) else payload["items"]:
                normalize.check_scope(row, require_tenant(ctx), account["id"], row.get("id"))
            for row in result["items"]:
                age = (self.clock() - normalize.timestamp(row["checkedAt"])).total_seconds()
                if row["access"] == "available" and age > self.space_max_age_seconds:
                    row["access"] = "unknown"
        except SpaceError:
            if self.selections is not None:
                self._store("invalidate_spaces", ctx, account["id"])
            raise
        if self.selections is not None:
            self._store("replace_spaces", ctx, account["id"], result["items"])
        return result

    def list_spaces(self, ctx, account_id):
        account, identity = self._account(ctx, account_id)
        return self._spaces(ctx, account, identity)

    def _accessible_space(self, ctx, account, identity, space_id):
        require_id(space_id)
        result = self._spaces(ctx, account, identity)
        selected = next((row for row in result["items"] if row["id"] == space_id), None)
        if selected is None:
            raise SpaceError("NOT_FOUND", "此账号未返回所选空间。", status=404)
        age = (self.clock() - normalize.timestamp(selected["checkedAt"])).total_seconds()
        if selected["access"] != "available" or age > self.space_max_age_seconds:
            raise SpaceError("SPACE_UNAVAILABLE", "此空间权限尚未确认或已失效，请重新选择。", status=409)
        return selected

    def assert_space_access(self, ctx, account_id, space_id):
        account, identity = self._account(ctx, account_id)
        return self._accessible_space(ctx, account, identity, space_id)

    def quota(self, ctx, account_id, space_id):
        account, identity = self._account(ctx, account_id)
        space = self._accessible_space(ctx, account, identity, space_id)
        client, _ = self._client(ctx, account, identity, space)
        try:
            payload = call_provider(client, "quota", space_id)
        except SpaceError as error:
            if error.code == "PROVIDER_CAPABILITY_UNAVAILABLE":
                result = normalize.unknown_quota(account_id, space_id,
                                                reason="provider_capability_unavailable")
            elif error.code == "PROVIDER_UNAVAILABLE":
                result = normalize.unknown_quota(account_id, space_id, state="unavailable",
                                                reason="provider_temporarily_unavailable")
            else:
                raise
        else:
            normalize.check_scope(payload, require_tenant(ctx), account_id, space_id)
            result = normalize.quota(payload, account_id, space_id, self.clock(),
                                     max_age_seconds=self.quota_max_age_seconds)
        # An attempted check is not an observation of a numeric balance.
        result['checkedAt'] = normalize.iso(self.clock())
        return result

    def list_models(self, ctx, account_id, space_id):
        account, identity = self._account(ctx, account_id)
        space = self._accessible_space(ctx, account, identity, space_id)
        client, _ = self._client(ctx, account, identity, space)
        payload = call_provider(client, "list_models", space_id)
        if isinstance(payload, dict):
            normalize.check_scope(payload, require_tenant(ctx), account_id, space_id)
        result = normalize.models(payload, self.clock())
        for row in payload if isinstance(payload, list) else payload["items"]:
            normalize.check_scope(row, require_tenant(ctx), account_id, space_id)
        return result

    def get_selection(self, ctx):
        require_tenant(ctx)
        return self._store("get", ctx)

    def set_selection(self, ctx, *, providerAccountId, spaceId, expectedRevision):
        require_tenant(ctx)
        if type(expectedRevision) is not int or expectedRevision < 0:
            raise SpaceError("VALIDATION_FAILED", "选择版本无效，请刷新账号状态。", status=422)
        if providerAccountId is None:
            if spaceId is not None:
                raise SpaceError("VALIDATION_FAILED", "清空账号时请同时清空空间。", status=422)
        else:
            account, identity = self._account(ctx, providerAccountId)
            if spaceId is not None:
                self._accessible_space(ctx, account, identity, spaceId)
            else:
                self._client(ctx, account, identity)
        # Only the persistent current-selection record changes. Task ownership
        # is deliberately outside this module and can never be rewritten here.
        return self._store("set", ctx, providerAccountId, spaceId, expected_revision=expectedRevision)
