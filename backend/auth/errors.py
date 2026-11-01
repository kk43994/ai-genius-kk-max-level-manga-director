"""Public errors deliberately contain no upstream bodies, credentials or URLs."""
from dataclasses import dataclass

MESSAGES = {
    'SESSION_REQUIRED': ('请先刷新页面恢复本站会话。', 401, False),
    'CSRF_FAILED': ('页面会话已变化，请刷新后重试。', 403, False),
    'NOT_FOUND': ('未找到此授权或账号。', 404, False),
    'VALIDATION_FAILED': ('授权请求参数无效。', 422, False),
    'VERSION_CONFLICT': ('账号状态已变化，请刷新后重试。', 409, False),
    'OWNERSHIP_MISMATCH': ('任务与授权账号不一致。', 409, False),
    'AUTHORIZATION_STATE_INVALID': ('授权回调已失效或不属于当前会话，请重新发起。', 400, False),
    'AUTHORIZATION_EXPIRED': ('授权已超时，请重新发起。', 410, False),
    'AUTHORIZATION_CANCELLED': ('本次授权已取消。', 409, False),
    'AUTHORIZATION_DENIED': ('你未完成 LibTV 授权，可以重新发起。', 403, False),
    'AUTHORIZATION_FAILED': ('LibTV 授权未完成，请重新发起。', 502, False),
    'AUTHORIZATION_BUSY': ('已有多个授权正在进行，请完成或取消后重试。', 429, False),
    'AUTHORIZATION_IN_PROGRESS': ('账号正在更新授权，请稍后重试。', 409, True),
    'PROVIDER_UNCONFIGURED': ('网站的 LibTV 官方授权尚未配置完成。', 503, False),
    'PROVIDER_UNAVAILABLE': ('LibTV 暂时无法连接，请稍后重新发起授权。', 503, True),
    'PROVIDER_PROTOCOL_ERROR': ('LibTV 返回的授权协议无法安全校验。', 502, False),
    'PROVIDER_NODE_NAME_CONFLICT': ('LibTV 拒绝了重名节点，尚未提交本次生成。', 409, False),
    'PROVIDER_RESPONSE_TOO_LARGE': ('LibTV 返回的项目内容超过当前查询容量，原任务已保留，请联系支持处理；无需重复授权或重新生成。', 502, False),
    'PROVIDER_REGISTRATION_REJECTED': ('LibTV 尚未允许此网站的授权回调，请联系网站管理员。', 503, False),
    'PROVIDER_SCOPE_UNAVAILABLE': ('LibTV 尚未提供网站所需的授权权限。', 503, False),
    'PROVIDER_IDENTITY_UNAVAILABLE': ('LibTV 官方身份读取尚未验证，此账号暂不能连接。', 503, False),
    'PROVIDER_IDENTITY_MISMATCH': ('本次授权不是原来的 LibTV 账号，请使用原账号重授权。', 409, False),
    'PROVIDER_AUTHORIZATION_REQUIRED': ('此账号授权已不可用，请重新授权。', 401, False),
    'PROVIDER_CAPABILITY_UNAVAILABLE': ('此项 LibTV 官方能力尚未接入。', 503, False),
    'SECRET_STORAGE_UNAVAILABLE': ('授权安全存储暂不可用，请联系网站管理员。', 503, False),
}


class AuthError(Exception):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'AUTHORIZATION_FAILED'
        self.message, self.status, self.retryable = MESSAGES[self.code]
        super().__init__(self.message)

    def public(self):
        return {'code': self.code, 'message': self.message,
                'retryable': self.retryable, 'details': {}}


def field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


@dataclass(frozen=True)
class ProviderWorkerContext:
    """Construct in trusted task-worker code from persisted task ownership only."""
    tenantId: str
    siteSessionId: None = None


def require_context(ctx, *, allow_worker=False):
    tenant = field(ctx, 'tenantId')
    session = field(ctx, 'siteSessionId')
    if allow_worker and isinstance(ctx, ProviderWorkerContext) and isinstance(tenant, str) and tenant:
        return tenant, ''
    if not isinstance(tenant, str) or not tenant or not isinstance(session, str) or not session:
        raise AuthError('SESSION_REQUIRED')
    return tenant, session
