"""Stable, deliberately non-sensitive errors for the HTTP adapter."""


class StorageError(Exception):
    def __init__(self, code, message, status=400, *, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def public(self):
        return {"code": self.code, "message": self.message,
                "retryable": self.retryable, "details": {}}


def not_found():
    return StorageError("NOT_FOUND", "对象不存在或不可访问", 404)


def conflict(code="VERSION_CONFLICT"):
    return StorageError(code, "内容已发生变化，请重新读取后操作", 409)


def invalid(message="输入不符合要求"):
    return StorageError("VALIDATION_FAILED", message, 422)
