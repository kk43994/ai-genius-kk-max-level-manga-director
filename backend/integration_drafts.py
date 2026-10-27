"""Integration-owned browser drafts with tenant isolation and version checks.

These are editable drafts, never workflow approval or generation authority.
The acknowledgement can be used by the update and workspace recovery gates.
"""
import json

from .storage import StorageError
from .storage.errors import invalid

COLLECTION, RECORD_ID = "drafts", "browser_drafts_v1"


def register_routes(router, services):
    store = services.storage

    def read(tx):
        try:
            return tx.get(COLLECTION, RECORD_ID)
        except StorageError as error:
            if error.code != "NOT_FOUND":
                raise
            return None

    def public(record):
        return {"id": RECORD_ID, "version": record["version"] if record else 0,
                "content": record["data"] if record else {"workflow": {}, "accountSelection": None},
                "updatedAt": record["updatedAt"] if record else None}

    def get(ctx, params):
        with store.transaction(ctx, readonly=True) as tx:
            return public(read(tx))

    def put(ctx, params):
        body = ctx.json
        if not isinstance(body, dict) or set(body) != {"expectedVersion", "content"}:
            raise invalid()
        version, content = body["expectedVersion"], body["content"]
        if type(version) is not int or version < 0 or not isinstance(content, dict):
            raise invalid()
        if set(content) != {"workflow", "accountSelection"} or not isinstance(content["workflow"], dict):
            raise invalid()
        selection = content["accountSelection"]
        if selection is not None and (not isinstance(selection, dict)
                or set(selection) != {"providerAccountId", "spaceId"}
                or any(value is not None and (not isinstance(value, str) or len(value) > 200)
                       for value in selection.values())):
            raise invalid()
        allowed = {"selectedProject", "selectedEntity", "page", "new-project", "quick-start"}
        if any(key not in allowed and not key.startswith(("plan:", "compose:", "review:", "flow:"))
               for key in content["workflow"]):
            raise invalid("草稿包含不支持的字段")
        if len(json.dumps(content, ensure_ascii=False).encode()) > 2 * 1024 * 1024:
            raise invalid("草稿超过 2 MiB，请先保存项目清单")
        with store.transaction(ctx) as tx:
            current = read(tx)
            if version != (current["version"] if current else 0):
                raise StorageError("VERSION_CONFLICT", "草稿已在另一个页面更新；当前编辑内容已保留，请核对后重试", 409)
            record = (tx.update(COLLECTION, RECORD_ID, content, expected_version=version) if current
                      else tx.create(COLLECTION, content, record_id=RECORD_ID))
        return {**public(record), "saved": True,
                "savedDrafts": [{"collection": COLLECTION, "id": RECORD_ID, "version": record["version"]}]}

    router.add("GET", "/api/v1/drafts/browser", get)
    router.add("PUT", "/api/v1/drafts/browser", put)
