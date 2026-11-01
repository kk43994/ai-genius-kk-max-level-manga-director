"""Fixed errors; upstream text, signed URLs and credentials never escape."""
MESSAGES = {
    'OWNERSHIP_MISMATCH': '任务、素材或官方项目不属于原账号与空间。',
    'PROVIDER_SCOPE_REQUIRED': '原账号尚未授予本操作所需权限；未扩大授权。',
    'PROVIDER_AUTHORIZATION_REQUIRED': '原账号授权已不可用，请恢复同一身份。',
    'PROVIDER_TOOL_SCHEMA_REQUIRED': '缺少此操作的已核实官方工具 schema。',
    'PROVIDER_RESPONSE_CONTRACT_REQUIRED': '缺少此操作的已核实官方响应结构。',
    'MODEL_CONTRACT_UNVERIFIED': '官方模型 inputContract 结构未能核实。',
    'MODEL_BINDING_REQUIRED': '尚未配置经官方目录核对的图片模型与参数映射。',
    'PROJECT_BINDING_REQUIRED': '尚未核实本站项目与原账号空间内的官方项目映射。',
    'REFERENCE_ROUTE_SCHEMA_REQUIRED': '参考图的官方节点与连线协议尚未核实，未提交生成。',
    'GENERATION_DISABLED': '当前环境禁止收费生成和外部写入。',
    'VIDEO_OR_AUDIO_DISABLED': '此适配器仅支持图片。',
    'CONFIRMATION_REQUIRED': '未找到已确认并持久化的本站提交记录。',
    'SOURCE_CHANGED': '参考素材版本、归属、审核或文件摘要发生变化。',
    'PROVIDER_SNAPSHOT_REVISION_MISMATCH': '官方项目版本已变化，需要核对原节点是否仍未生成。',
    'REFERENCE_PREFLIGHT_REJECTED': '官方因项目版本变化拒绝提交，已核实原节点未生成；可重新准备，原记录保留。',
    'SOURCE_REVIEW_REQUIRED': '参考素材必须先通过人工审核。',
    'INPUT_INVALID': '图片模型参数或请求格式不符合官方 schema。',
    'PROVIDER_PROTOCOL_ERROR': '官方响应无法安全解析，请核对原任务。',
    'PROVIDER_UNAVAILABLE': '官方服务未及时返回，未自动重试。',
    'PROVIDER_ACCOUNT_READ_UNAVAILABLE': 'LibTV 暂时无法读取原账号资料，原任务与回执已保留。',
    'SUBMISSION_UNKNOWN': '提交结果不明，已保留原引用，禁止重新提交。',
    'OPERATION_UNKNOWN': '先前外部操作结果不明，禁止自动重发。',
    'IDEMPOTENCY_CONFLICT': '同一任务或操作编号对应了不同请求。',
    'ORIGINAL_RECEIPT_REQUIRED': '缺少明确的原官方任务引用，不能猜测或重新生成。',
    'PROVIDER_RECEIPT_MISMATCH': '官方返回的任务或项目引用与原记录不一致。',
    'DELIVERY_UNCONFIRMED': '官方交付尚未确认，未直接绕过交付处理下载。',
    'UPLOAD_UNCONFIRMED': '参考图上传或官方内容审核尚未完成。',
    'TRANSFER_HOST_UNVERIFIED': '媒体服务器域名尚未核实，未传输文件。',
    'UNSAFE_MEDIA_URL': '媒体链接不符合允许的 HTTPS 和公开网络边界。',
    'MEDIA_TRANSFER_FAILED': '媒体传输未完成，未自动重试或跟随重定向。',
    'OUTPUT_INVALID': '图片内容、格式、数量、大小或校验摘要不一致。',
}


class GenerationError(Exception):
    def __init__(self, code, *, receipt=None, required_scopes=(), missing=None):
        self.code = code if code in MESSAGES else 'PROVIDER_PROTOCOL_ERROR'
        self.message = MESSAGES[self.code]
        self.status = 403 if self.code in {'PROVIDER_SCOPE_REQUIRED', 'GENERATION_DISABLED'} else 409
        self.retryable = False
        self.provider_receipt = dict(receipt) if receipt else None
        self.details = {}
        if required_scopes:
            self.details['requiredScopes'] = sorted(required_scopes)
        if missing:
            self.details['missingContract'] = missing
        super().__init__(self.message)

    def public(self):
        return dict(code=self.code, message=self.message, retryable=False, details=self.details)
