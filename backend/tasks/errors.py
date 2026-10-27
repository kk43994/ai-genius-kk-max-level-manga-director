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

PREPARATION_CODES = {
    "UNSAFE_MEDIA_URL":"素材下载地址未通过网络校验，原生成和导出记录已保留。",
    "MEDIA_TRANSFER_FAILED":"图片已经生成，下载暂未完成；请查询原任务继续收取。",
    "DELIVERY_UNCONFIRMED":"原任务仍在生成或准备导出，请稍后查询原任务。",
    "OUTPUT_INVALID":"返回文件未通过格式、数量或完整性校验，请核对原任务。",
    "PROVIDER_PROTOCOL_ERROR":"官方返回的数据结构无法读取，请核对原任务。",
    "OPERATION_UNKNOWN":"原操作结果待核对，系统不会另建任务或重复生成。",
    "PROVIDER_SCOPE_REQUIRED":"原账号缺少此操作所需权限，请先核对授权范围。",
    "PROVIDER_SCOPE_UNAVAILABLE":"原账号缺少此操作所需权限，请先核对授权范围。",
    "PROVIDER_TOOL_SCHEMA_REQUIRED":"此步骤的官方工具定义尚未核实。",
    "PROVIDER_RESPONSE_CONTRACT_REQUIRED":"此步骤的官方响应结构尚未完成核实与适配。",
    "MODEL_CONTRACT_UNVERIFIED":"官方模型参数结构尚未核实。",
    "MODEL_BINDING_REQUIRED":"MJ、Image2 或 Nano 的准确模型与参数映射尚未配置。",
    "PROJECT_BINDING_REQUIRED":"本站项目与原账号空间中的官方项目映射尚未核实。",
    "REFERENCE_ROUTE_SCHEMA_REQUIRED":"参考图上传、节点与连线协议尚未核实。",
    "TRANSFER_HOST_UNVERIFIED":"官方媒体服务器及传输要求尚未核实。",
    "GENERATION_DISABLED":"当前版本禁止收费生成和外部写入。",
}


def provider_failure(exc, *, attempted=False):
    # Never stringify an upstream exception: it may contain tokens/signed URLs.
    code = getattr(exc, "code", None)
    if code in PREPARATION_CODES:
        return ("needs_attention", {"code":code,"message":PREPARATION_CODES[code],
            "retryable":False,"details":{"submissionAttempted":bool(attempted)}})
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
