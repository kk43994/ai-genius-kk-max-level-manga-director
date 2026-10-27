"""Only controlled messages may cross the task API boundary."""


class TaskError(Exception):
    def __init__(self, code, message, status=409, *, retryable=False, details=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.retryable, self.details = retryable, details or {}

    def public(self):
        return {"code": self.code, "message": self.message,
                "retryable": self.retryable, "details": self.details}


AUTH_CODES = frozenset({
    "AUTHORIZATION_EXPIRED", "AUTHORIZATION_REVOKED", "ACCOUNT_REMOVED",
    "PROVIDER_AUTHORIZATION_REQUIRED", "PROVIDER_AUTHORIZATION_EXPIRED",
    "PROVIDER_AUTHORIZATION_REVOKED", "SPACE_ACCESS_REVOKED", "OWNERSHIP_MISMATCH",
    "PROVIDER_IDENTITY_MISMATCH", "AUTHORIZATION_REQUIRED", "SPACE_UNAVAILABLE",
})


def provider_failure(exc, *, attempted=False):
    # Never stringify an upstream exception: it may contain tokens/signed URLs.
    code = getattr(exc, "code", None)
    if code in AUTH_CODES:
        return ("blocked_authorization", {
            "code": "ORIGINAL_AUTHORIZATION_REQUIRED",
            "message": "原账号或空间的授权不可用。请恢复同一登录身份的授权后查回原任务。",
            "retryable": False, "details": {},
        })
    if code == "PROVIDER_CAPABILITY_UNAVAILABLE":
        return ("needs_attention", {
            "code": code, "message": "官方接入尚未支持此操作，任务已保留。",
            "retryable": False, "details": {},
        })
    return ("needs_attention", {
        "code": "SUBMISSION_UNKNOWN" if attempted else "PROVIDER_OPERATION_UNCONFIRMED",
        "message": ("提交结果尚未确认。只能核对原任务，不会再次提交生成。" if attempted
                    else "此步骤未完成，记录已保留。请核对原任务后继续。"),
        "retryable": False, "details": {},
    })
