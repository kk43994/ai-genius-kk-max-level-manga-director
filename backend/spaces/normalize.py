"""Validate the v1 ProviderClient contract, not guessed LibTV wire schemas.

The OAuth module is responsible for verifying real tool names, response schemas
and subject evidence. CLI activeAccount and subscription allowances are never
accepted as substitutes for those facts here.
"""
from datetime import datetime, timezone
import math
import re

from .errors import SpaceError, invalid_response

OFFICIAL_ISSUER = "https://mcp.liblib.tv/"
OFFICIAL_RESOURCE = "https://mcp.liblib.tv/mcp"
OFFICIAL_VIEW_URL = "https://www.liblib.tv/"


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise invalid_response()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise invalid_response() from None


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def identifier(value):
    # IDs are opaque strings, not necessarily UUIDs. Reject controls/whitespace.
    return (isinstance(value, str) and 0 < len(value) <= 512
            and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value))


def label(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise invalid_response()
    return value


def identity(payload):
    if not isinstance(payload, dict):
        raise invalid_response()
    if (payload.get("verified") is not True or payload.get("issuer") != OFFICIAL_ISSUER
            or not identifier(payload.get("subject"))):
        raise SpaceError("PROVIDER_IDENTITY_UNVERIFIED", "尚未取得官方可核验的登录身份。")
    return {"issuer": OFFICIAL_ISSUER, "subject": payload["subject"],
            "verified": True, "displayName": label(payload.get("displayName"))}


def check_scope(payload, tenant_id, account_id, space_id=None):
    """Reject conflicting metadata even if a provider adapter supplied it."""
    if not isinstance(payload, dict):
        raise invalid_response()
    for key, expected in (("tenantId", tenant_id), ("providerAccountId", account_id),
                          ("spaceId", space_id)):
        if key in payload and payload[key] != expected:
            raise SpaceError("OWNERSHIP_MISMATCH", "返回的资料不属于所选账号或空间。", status=409)


def spaces(payload, now):
    # A bare list is the other permitted ProviderClient collection representation.
    rows = payload if isinstance(payload, list) else payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 1000:
        raise invalid_response()
    if isinstance(payload, dict) and payload.get("nextCursor") is not None:
        # ProviderClient must complete pagination; a partial list is not authority
        # for deciding that a previously selected workspace has been revoked.
        raise SpaceError("PROVIDER_CAPABILITY_UNAVAILABLE", "官方空间列表尚未完整读取。")
    result, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or not identifier(row.get("id"))
                or row.get("kind") not in ("personal", "team")
                or row.get("access") not in ("available", "revoked", "unknown")
                or row["id"] in seen or not row.get("name")):
            raise invalid_response()
        checked_at = timestamp(row["checkedAt"]) if row.get("checkedAt") else now
        if (checked_at - now).total_seconds() > 5:
            raise invalid_response()
        seen.add(row["id"])
        result.append({"id": row["id"], "kind": row["kind"], "name": label(row["name"]),
                       "access": row["access"], "checkedAt": iso(checked_at)})
    return {"items": result, "nextCursor": None}


def unknown_quota(account_id, space_id, *, reason="provider_did_not_return_balance",
                  state="unknown", plan_name=None):
    return {"providerAccountId": account_id, "spaceId": space_id, "state": state,
            "remaining": None, "unit": "credits", "buckets": [], "planName": plan_name,
            "source": "official", "observedAt": None, "expiresAt": None, "reason": reason,
            "officialViewUrl": OFFICIAL_VIEW_URL}


def amount(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0 or value > 9007199254740991 or not math.isfinite(value)):
        raise invalid_response()
    return value


def unit(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value):
        raise invalid_response()
    return value


def quota(payload, account_id, space_id, now, *, max_age_seconds=120):
    if not isinstance(payload, dict) or "error" in payload or payload.get("isError") is True:
        raise invalid_response()
    plan_name = label(payload.get("planName"))
    state = payload.get("state", "unknown")
    if state in ("unknown", "unavailable"):
        # Drop allowance/points/remaining fields in an explicitly unknown result.
        return unknown_quota(account_id, space_id, plan_name=plan_name, state=state,
                             reason="provider_capability_unavailable" if state == "unavailable"
                             else "provider_did_not_return_balance")
    if state not in ("known", "stale") or payload.get("source") != "official":
        raise invalid_response()
    # Known values require an explicit, account-and-space-specific observation.
    if payload.get("providerAccountId") != account_id or payload.get("spaceId") != space_id:
        raise invalid_response()
    observed = timestamp(payload.get("observedAt"))
    if (observed - now).total_seconds() > 5:
        raise invalid_response()
    expires = timestamp(payload["expiresAt"]) if payload.get("expiresAt") else None
    if expires is not None and expires < observed:
        raise invalid_response()
    result = unknown_quota(account_id, space_id, plan_name=plan_name)
    raw_buckets = payload.get("buckets", [])
    if not isinstance(raw_buckets, list) or len(raw_buckets) > 100:
        raise invalid_response()
    buckets, seen = [], set()
    for row in raw_buckets:
        if not isinstance(row, dict) or not identifier(row.get("id")) or row["id"] in seen:
            raise invalid_response()
        seen.add(row["id"])
        bucket_expiry = timestamp(row["expiresAt"]) if row.get("expiresAt") else None
        if bucket_expiry is not None and bucket_expiry <= now:
            state = "stale"
        buckets.append({"id": row["id"], "name": label(row.get("name")),
                        "remaining": amount(row.get("remaining")), "unit": unit(row.get("unit")),
                        "expiresAt": iso(bucket_expiry) if bucket_expiry else None})
    # Different buckets and currencies are never added together. If the official
    # response gives only buckets, there is deliberately no aggregate balance.
    remaining = payload.get("remaining")
    if remaining is not None:
        remaining = amount(remaining)
    elif not buckets:
        raise invalid_response()
    if (now - observed).total_seconds() > max_age_seconds or (expires is not None and expires <= now):
        state = "stale"
    result.update(state=state, remaining=remaining, unit=unit(payload.get("unit")), buckets=buckets,
                  observedAt=iso(observed), expiresAt=iso(expires) if expires else None,
                  reason="observation_expired" if state == "stale" else None)
    return result


def models(payload, now):
    rows = payload if isinstance(payload, list) else payload.get("items") if isinstance(payload, dict) else None
    if (not isinstance(rows, list) or len(rows) > 2000
            or (isinstance(payload, dict) and payload.get("nextCursor") is not None)):
        raise invalid_response()
    result, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or not identifier(row.get("modelKey"))
                or not row.get("modelName") or row["modelKey"] in seen
                or row.get("mediaType") not in ("image", "video", "audio", "text")):
            raise invalid_response()
        seen.add(row["modelKey"])
        result.append({"modelKey": row["modelKey"], "modelName": label(row["modelName"]),
                       "mediaType": row["mediaType"], "generationEnabled": False})
    return {"items": result, "nextCursor": None, "observedAt": iso(now),
            "source": "official", "generationEnabled": False}
