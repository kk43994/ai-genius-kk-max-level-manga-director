"""Owner-bound recovery persistence. Only the server-authenticated callback writes owners."""
import json

from .core import canonical_json, checked_id, utc
from .errors import StorageError, not_found

OWNER_PROVIDER = "libtv"
OWNER_ISSUER = "https://mcp.liblib.tv/"


class WorkspaceRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def owner(conn, tenant_id):
        return conn.execute("SELECT * FROM workspace_owners WHERE tenant_id=?", (tenant_id,)).fetchone()

    @staticmethod
    def matches(row, issuer, subject):
        return bool(row and row["provider"] == OWNER_PROVIDER and row["issuer"] == issuer and row["subject"] == subject)

    @staticmethod
    def content(conn, tenant_id):
        revision = conn.execute("SELECT revision FROM workspace_content_revisions WHERE tenant_id=?", (tenant_id,)).fetchone()
        counts = {name: conn.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=?", (tenant_id,)).fetchone()[0]
                  for name, table in (("records", "records"), ("blobs", "blobs"), ("providerAccounts", "provider_accounts"))}
        return {"revision": revision[0] if revision else 0, "hasContent": any(counts.values()), **counts}

    def summary(self, conn, tenant_id):
        row = self.owner(conn, tenant_id)
        return {"id": tenant_id, "label": row["label"] if row else "未绑定工作区",
                "ownerBound": row is not None, "owner": {"provider": OWNER_PROVIDER,
                "issuer": row["issuer"], "subject": row["subject"]} if row else None,
                "boundAt": row["bound_at"] if row else None,
                "content": self.content(conn, tenant_id)}

    def get(self, ctx):
        with self.store.transaction(ctx, readonly=True) as tx:
            return self.summary(tx._conn, tx.tenant_id)

    @staticmethod
    def candidates(conn, issuer, subject):
        return conn.execute("SELECT tenant_id FROM workspace_owners WHERE provider=? AND issuer=? AND subject=? ORDER BY bound_at,tenant_id",
                            (OWNER_PROVIDER, issuer, subject)).fetchall()

    def bind(self, conn, tenant_id, issuer, subject, *, label, authorization_attempt_id):
        # Internal callback/confirmation primitive, intentionally no HTTP route.
        row = self.owner(conn, tenant_id)
        if row:
            if not self.matches(row, issuer, subject):
                raise StorageError("WORKSPACE_OWNER_MISMATCH", "当前工作区已有其他主所有者，不能转移所有权", 409)
            return
        conn.execute("INSERT INTO workspace_owners VALUES(?,?,?,?,?,?,?)",
                     (tenant_id, OWNER_PROVIDER, issuer, subject, label, utc(self.store.clock()), authorization_attempt_id))

    @staticmethod
    def intent(conn, ctx, identifier):
        from .core import field
        row = conn.execute("SELECT * FROM workspace_intents WHERE id=? AND tenant_id=? AND site_session_id=?",
                           (checked_id(identifier), field(ctx, "tenantId"), field(ctx, "siteSessionId"))).fetchone()
        if row is None:
            raise not_found()
        return row

    @staticmethod
    def data(row):
        return json.loads(row["data"])

    @staticmethod
    def update(conn, row, status, data):
        conn.execute("UPDATE workspace_intents SET status=?,version=version+1,data=? WHERE id=? AND version=?",
                     (status, canonical_json(data), row["id"], row["version"]))
