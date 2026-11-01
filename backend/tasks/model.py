"""Strict public projections and stable hashes for immutable task snapshots."""

import base64
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime, timezone

from .errors import TaskError

RECIPES = frozenset({"mj_style", "image2_asset", "nano_refine", "storyboard_image", "script_analysis"})
ACTIVE = frozenset({"preparing", "submitting", "queued", "running", "downloading"})
TERMINAL = frozenset({"completed", "cancelled"})
RECEIPT_KEYS = frozenset({"taskId", "projectId", "nodeId", "requestId"})
OWNER_KEYS = ("tenantId", "provider", "providerAccountId", "providerIssuer",
              "providerSubject", "spaceId", "spaceKind")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}\Z")
HASH_RE = re.compile(r"[a-f0-9]{64}\Z")


def field(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (TypeError, ValueError, AttributeError):
        raise TaskError("INVALID_RECORD", "任务时间记录无效，需要核对。", 409) from None


def digest(value):
    try:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode()
    except (TypeError, ValueError):
        raise TaskError("VALIDATION_FAILED", "参数必须是可保存的 JSON 数据。", 422) from None
    return hashlib.sha256(raw).hexdigest()


def opaque(value, name="标识"):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise TaskError("VALIDATION_FAILED", f"{name}格式无效。", 422)
    return value


def tenant(ctx):
    value = field(ctx, "tenantId")
    if not value:
        raise TaskError("SESSION_REQUIRED", "请恢复本站会话后继续。", 401)
    return opaque(value, "会话")


def version(value):
    if type(value) is not int or value < 1:
        raise TaskError("VALIDATION_FAILED", "expectedVersion 必须是正整数。", 422)
    return value


def selection_revision(value):
    if type(value) is not int or value < 0:
        raise TaskError("VALIDATION_FAILED", "选择版本无效。", 422)
    return value


def receipt(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - RECEIPT_KEYS:
        raise TaskError("INVALID_PROVIDER_RECEIPT", "官方任务引用格式未确认。", 409)
    result = {k: opaque(v, "官方任务引用") for k, v in value.items() if v is not None}
    return result or None


def merge_receipt(old, new):
    old, new = receipt(old) or {}, receipt(new) or {}
    if any(k in old and old[k] != v for k, v in new.items()):
        raise TaskError("PROVIDER_RECEIPT_MISMATCH", "查回结果不属于原任务，已停止收取。", 409)
    return {**old, **new} or None


def owner_match(first, second):
    return all(first.get(key) == second.get(key) for key in OWNER_KEYS)


def validate_spec(spec):
    keys = {"projectId", "recipe", "entityId", "prompt", "sourceRevisionIds", "settings"}
    if not isinstance(spec, dict) or set(spec) - keys:
        raise TaskError("VALIDATION_FAILED", "任务含不支持的字段，不能指定归属或凭据。", 422)
    if spec.get("recipe") not in RECIPES:
        raise TaskError("VIDEO_OR_RECIPE_DISABLED", "当前仅支持已定义的资产步骤，视频生成暂停。", 403)
    for key in ("projectId", "entityId"):
        opaque(spec.get(key), key)
    prompt = spec.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 50000:
        raise TaskError("VALIDATION_FAILED", "请填写不超过 50000 字的提示词。", 422)
    sources = spec.get("sourceRevisionIds", [])
    if not isinstance(sources, list) or len(sources) > 20 or len(set(map(str, sources))) != len(sources):
        raise TaskError("VALIDATION_FAILED", "参考版本列表无效。", 422)
    for item in sources:
        opaque(item, "参考版本")
    settings = spec.get("settings", {})
    if not isinstance(settings, dict) or len(json.dumps(settings, default=str)) > 20000:
        raise TaskError("VALIDATION_FAILED", "模型设置无效。", 422)
    # Model settings remain schema-owned; credentials and transport are not settings.
    forbidden = {"token", "accesstoken", "refreshtoken", "secret", "authorization",
                 "cookie", "credential", "credentials", "tenantid", "ownership",
                 "provideraccountid", "spaceid", "url", "path", "root", "endpoint"}
    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or key.replace("_", "").replace("-", "").lower() in forbidden:
                    raise TaskError("VALIDATION_FAILED", "模型设置不能携带凭据或访问路径。", 422)
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif not isinstance(value, (str, int, float, bool, type(None))) or isinstance(value, float) and not math.isfinite(value):
            raise TaskError("VALIDATION_FAILED", "模型设置必须是有效 JSON。", 422)
    inspect(settings)
    return deepcopy({**spec, "sourceRevisionIds": sources, "settings": settings})


def cost(value):
    unknown = {"state": "unknown", "amount": None, "unit": None}
    if not isinstance(value, dict) or value.get("state") != "known":
        return unknown
    amount, unit = value.get("amount"), value.get("unit")
    if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0 or not isinstance(unit, str) or not unit or len(unit) > 32:
        raise TaskError("INVALID_PROVIDER_QUOTE", "官方报价格式未确认。", 409)
    result = {"state": "known", "amount": amount, "unit": unit}
    if value.get("expiresAt") is not None:
        parse_time(value["expiresAt"])
        result["expiresAt"] = value["expiresAt"]
    return result


def safe_prepared(value, request_hash, max_outputs):
    if not isinstance(value, dict):
        raise TaskError("INVALID_PROVIDER_PREPARATION", "官方参数准备未确认。", 409)
    model_key = opaque(value.get("modelKey"), "模型")
    schema_hash = value.get("schemaHash")
    count = value.get("count")
    if not isinstance(schema_hash, str) or not HASH_RE.fullmatch(schema_hash) or value.get("requestHash") != request_hash or type(count) is not int or not 1 <= count <= max_outputs:
        raise TaskError("INVALID_PROVIDER_PREPARATION", "官方模型、参数或数量回读不一致。", 409)
    return {"modelKey": model_key, "schemaHash": schema_hash, "requestHash": request_hash,
            "count": count, "cost": cost(value.get("cost")),
            "providerReceipt": receipt(value.get("providerReceipt"))}


def workflow_snapshot(value, sources):
    required = {"entityVersion", "styleVersion", "sourceHashes"}
    if not isinstance(value, dict) or not required <= value.keys() or set(value) - (required | {"planVersion"}):
        raise TaskError("WORKFLOW_SNAPSHOT_MISSING", "任务缺少服务端资产版本快照，已停止处理。", 409)
    if any(type(value[k]) is not int or value[k] < 0 for k in value if k != "sourceHashes"):
        raise TaskError("WORKFLOW_SNAPSHOT_MISSING", "资产版本快照格式无效。", 409)
    hashes = {source["revisionId"]: source["sha256"] for source in sources}
    if value.get("sourceHashes") != hashes:
        raise TaskError("SOURCE_CHANGED", "资产版本快照与参考文件摘要不一致。", 409)
    return deepcopy(value)


def public_task(task):
    keys = ("id", "version", "projectId", "entityId", "recipe", "ownership", "status",
            "sourceRevisionIds", "outputs", "review", "createdAt", "updatedAt",
            "providerReceipt", "submissionAttempted", "submittedAt", "error", "cost",
            "cancellation", "remoteStatus", "preparedAt", "completedAt")
    result = {key: deepcopy(task[key]) for key in keys if key in task}
    result["workflowSnapshot"] = deepcopy(task.get("inputs", {}).get("workflowSnapshot"))
    result["canRecover"] = bool(task["submissionAttempted"] and task.get("providerReceipt")
                                and task["status"] not in TERMINAL)
    result["canConfirm"] = task["status"] == "draft" and not task["submissionAttempted"]
    result["canResubmit"] = False
    return result


def encode_cursor(task_id):
    return base64.urlsafe_b64encode(task_id.encode()).decode().rstrip("=")


def decode_cursor(cursor):
    try:
        if not isinstance(cursor, str) or len(cursor) > 512:
            raise ValueError
        return opaque(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode())
    except (ValueError, UnicodeError):
        raise TaskError("VALIDATION_FAILED", "分页位置无效。", 422) from None
