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
    "INPUT_INVALID":"模型不接受当前制作参数。请检查画幅、数量或必填选项；尚未提交的记录可以取消后重新准备。",
    "SOURCE_CHANGED":"参考图版本或审核状态已变化，请重新选择已审核的有效图片。",
    "SOURCE_REVIEW_REQUIRED":"请先选用并审核参考图，再准备这次生成。",
    "UPLOAD_UNCONFIRMED":"参考图上传或官方内容检查尚未完成，请核对原任务。",
    "IDEMPOTENCY_CONFLICT":"这份准备记录的内容已改变。尚未提交的记录可取消后重新准备；已提交任务只能查询原结果。",
    "ORIGINAL_RECEIPT_REQUIRED":"原任务缺少可恢复的官方回执，已保留记录；请检查接入状态。",
    "PROVIDER_RECEIPT_MISMATCH":"官方回执、节点或图片归属尚未核对一致，已暂停收取；不会重新生成。",
    "PROVIDER_UNAVAILABLE":"暂未收到官方任务状态，请稍后继续收取原任务。",
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
    if code == 'REFERENCE_PREFLIGHT_REJECTED':
        return ('failed', {'code':code, 'message':'项目同时有其他更新，官方拒绝了这次提交；已核实原节点未生成。请重新准备，原记录保留。',
            'retryable':True, 'details':{'generationSubmitted':False}})
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
