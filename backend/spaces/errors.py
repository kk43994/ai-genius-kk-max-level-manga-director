"""Safe errors at the account/space boundary; never forward provider messages."""


class SpaceError(Exception):
    def __init__(self, code, message, *, status=503, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def public(self):
        return {"code": self.code, "message": self.message,
                "retryable": self.retryable, "details": {}}


def invalid_response():
    return SpaceError("PROVIDER_RESPONSE_INVALID", "官方资料格式尚未核实，请在 LibTV 官网查看。")


def unavailable():
    return SpaceError("PROVIDER_CAPABILITY_UNAVAILABLE", "当前官方接入尚不支持这项资料读取。")


def call_provider(target, method, *args):
    """Use only the explicitly bound client. No retry, CLI or account fallback."""
    operation = getattr(target, method, None)
    if not callable(operation):
        raise unavailable()
    try:
        return operation(*args)
    except SpaceError:
        raise
    except NotImplementedError:
        raise unavailable() from None
    except Exception as error:
        code = getattr(error, "code", None)
        if code == "PROVIDER_ACCOUNT_READ_UNAVAILABLE":
            raise SpaceError(code, "LibTV 暂时无法读取原账号资料。已有任务保留，请稍后刷新账号或收取原任务。", retryable=True) from None
        if code in {"PROVIDER_CAPABILITY_UNAVAILABLE", "NOT_IMPLEMENTED"}:
            raise unavailable() from None
        if code in {"PROVIDER_UNCONFIGURED", "PROVIDER_IDENTITY_UNAVAILABLE", "PROVIDER_SCOPE_UNAVAILABLE"}:
            raise SpaceError(code, "官方授权或身份读取尚未完成核验。") from None
        if code in {"NOT_FOUND", "ACCOUNT_NOT_FOUND"}:
            raise SpaceError("NOT_FOUND", "未找到此账号或空间。", status=404) from None
        if code in {"PROVIDER_AUTHORIZATION_REQUIRED", "AUTHORIZATION_REQUIRED",
                    "TOKEN_EXPIRED", "UNAUTHORIZED"}:
            raise SpaceError("PROVIDER_AUTHORIZATION_REQUIRED", "请重新授权此 LibTV 账号。",
                             status=409) from None
        if code in {"OWNERSHIP_MISMATCH", "IDENTITY_MISMATCH", "PROVIDER_IDENTITY_MISMATCH"}:
            raise SpaceError("OWNERSHIP_MISMATCH", "返回的登录身份与所选账号不一致。",
                             status=409) from None
        raise SpaceError("PROVIDER_UNAVAILABLE", "暂时无法读取 LibTV 资料，请稍后重试。",
                         retryable=True) from None
