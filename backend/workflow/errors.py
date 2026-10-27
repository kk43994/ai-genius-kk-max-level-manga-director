"""Public, credential-free errors for the asset workflow."""


class WorkflowError(Exception):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.retryable = False

    def public(self):
        return {'code': self.code, 'message': self.message, 'retryable': self.retryable, 'details': {}}


def invalid(message):
    raise WorkflowError('VALIDATION_FAILED', message)


def conflict(message):
    raise WorkflowError('VERSION_CONFLICT', message, 409)


def missing():
    raise WorkflowError('NOT_FOUND', '未找到这份项目或素材。', 404)


def value(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def tenant(ctx):
    result = value(ctx, 'tenantId')
    if not isinstance(result, str) or not result:
        raise WorkflowError('SESSION_REQUIRED', '请重新打开页面恢复本站会话。', 401)
    return result


def public_input(body, allowed):
    if not isinstance(body, dict) or set(body) - set(allowed):
        invalid('请求包含不支持的字段。')
    return body
