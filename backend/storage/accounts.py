"""Persistence for provider identities. OAuth itself belongs to backend.auth.

Provider adapters must verify issuer + subject and a minimum official read before
calling complete_authorization. A workspace ID must never be used as subject.
"""
from dataclasses import dataclass
import math
from urllib.parse import urlsplit

from .core import checked_id, opaque_id, utc, version
from .errors import StorageError, conflict, invalid, not_found


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    display_name: str | None = None
    provider: str = "libtv"


_REASONS = {"official_client_registration_unverified", "official_identity_unverified",
            "authorization_started", "authorization_failed", "authorization_expired",
            "provider_revoked", "refresh_failed", "removed_by_user"}


def _label(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120 or any(ord(c) < 32 for c in value):
        raise invalid("账号名称不符合要求")
    return value.strip()


def _identity(identity):
    if not isinstance(identity, VerifiedIdentity) or identity.provider != "libtv":
        raise invalid("必须使用官方核验后的 LibTV 身份")
    if not isinstance(identity.issuer, str):
        raise invalid("官方身份 issuer 不符合要求")
    try:
        issuer = urlsplit(identity.issuer)
    except ValueError:
        raise invalid("官方身份 issuer 不符合要求") from None
    if (issuer.scheme != "https" or not issuer.hostname or issuer.username or issuer.password
            or issuer.query or issuer.fragment):
        raise invalid("官方身份 issuer 不符合要求")
    if (not isinstance(identity.subject, str) or not 1 <= len(identity.subject) <= 1024
            or any(ord(c) < 32 for c in identity.subject)):
        raise invalid("官方身份缺少 subject")
    if identity.display_name is not None:
        _label(identity.display_name)


class AccountRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _authorization_epoch(tx):
        row = tx._conn.execute("SELECT epoch FROM authorization_epochs WHERE tenant_id=?", (tx.tenant_id,)).fetchone()
        return row[0] if row else 0

    def authorization_epoch(self, ctx):
        """Read at begin_authorization and persist with the session-bound attempt.

        Removing any account increments this tenant-local fence, invalidating all
        older pending authorizations (including adds without a known account ID).
        """
        with self.store.transaction(ctx, readonly=True) as tx:
            return self._authorization_epoch(tx)

    @staticmethod
    def _row(tx, account_id):
        tx._check()
        row = tx._conn.execute("SELECT * FROM provider_accounts WHERE tenant_id=? AND id=?",
                               (tx.tenant_id, checked_id(account_id))).fetchone()
        if row is None:
            raise not_found()
        return row

    def _public(self, row):
        state, reason = row["state"], row["reason"]
        if state == "connected" and row["expires_at"] is not None and row["expires_at"] <= self.store.clock():
            state, reason = "expired", "authorization_expired"
        return {"id": row["id"], "provider": row["provider"], "label": row["label"],
                "version": row["version"],
                "identity": {"issuer": row["issuer"], "subject": row["subject"],
                             "displayName": row["display_name"], "verified": bool(row["verified"])},
                "authorization": {"state": state,
                                  "expiresAt": utc(row["expires_at"]) if row["expires_at"] is not None else None,
                                  "lastVerifiedAt": row["last_verified_at"], "reason": reason},
                # ProviderService supplies actual verified capabilities. Storage
                # alone must never make the website look provider-connected.
                "capabilities": {"authorize": False, "spaces": False, "quota": False},
                "removedAt": row["removed_at"]}

    def get(self, ctx, account_id):
        with self.store.transaction(ctx, readonly=True) as tx:
            return self._public(self._row(tx, account_id))

    def list(self, ctx, *, include_removed=False):
        with self.store.transaction(ctx, readonly=True) as tx:
            rows = tx._conn.execute("SELECT * FROM provider_accounts WHERE tenant_id=? ORDER BY created_at,id", (tx.tenant_id,)).fetchall()
            return {"items": [self._public(row) for row in rows if include_removed or row["removed_at"] is None], "nextCursor": None}

    def create_unconfigured(self, ctx, *, label="LibTV 账号"):
        label = _label(label)
        with self.store.transaction(ctx) as tx:
            now, account_id = utc(self.store.clock()), opaque_id("pa")
            tx._conn.execute("""INSERT INTO provider_accounts
                (tenant_id,id,provider,label,verified,state,reason,version,created_at,updated_at)
                VALUES(?,?,'libtv',?,0,'unconfigured','official_identity_unverified',1,?,?)""",
                (tx.tenant_id, account_id, label, now, now))
            return self._public(self._row(tx, account_id))

    def complete_authorization(self, ctx, identity, credentials, *, label="LibTV 账号",
                               expires_at=None, minimum_read_verified=False,
                               account_id=None, expected_version=None,
                               expected_authorization_epoch=None):
        """Commit verified identity and encrypted grant atomically.

        account_id + expected_version mean reauthorization and require the same
        existing subject. New additions of a duplicate subject restore its stable
        ID (even after removal); they cannot invent a second login identity.
        """
        _identity(identity)
        label = _label(label)
        if minimum_read_verified is not True:
            raise StorageError("IDENTITY_UNVERIFIED", "官方身份和最小读取尚未核验", 409)
        if type(expected_authorization_epoch) is not int or expected_authorization_epoch < 0:
            raise StorageError("AUTHORIZATION_ATTEMPT_REQUIRED", "缺少开始授权时的有效存储检查点", 409)
        if (not isinstance(credentials, dict) or not isinstance(credentials.get("access_token"), str)
                or not credentials["access_token"]):
            raise invalid("缺少服务端授权凭据")
        if expires_at is not None and (type(expires_at) not in (int, float) or not math.isfinite(expires_at)
                                       or expires_at <= self.store.clock()):
            raise invalid("授权过期时间无效")
        with self.store.transaction(ctx) as tx:
            if self._authorization_epoch(tx) != expected_authorization_epoch:
                raise StorageError("AUTHORIZATION_ATTEMPT_INVALIDATED", "账号管理状态已变化，请重新发起授权", 409)
            now = utc(self.store.clock())
            existing = None
            if account_id is not None:
                existing = self._row(tx, account_id)
                if existing["version"] != version(expected_version):
                    raise conflict()
                if existing["verified"] and (existing["issuer"] != identity.issuer or existing["subject"] != identity.subject):
                    raise StorageError("OWNERSHIP_MISMATCH", "重新授权必须使用原来的 LibTV 登录身份", 409)
                if existing["removed_at"] is not None:
                    raise StorageError("ACCOUNT_REMOVED", "该账号已移除，请重新添加", 409)
            duplicate = tx._conn.execute("SELECT * FROM provider_accounts WHERE tenant_id=? AND provider=? AND issuer=? AND subject=?",
                                         (tx.tenant_id, identity.provider, identity.issuer, identity.subject)).fetchone()
            if duplicate is not None:
                if existing is not None and existing["id"] != duplicate["id"]:
                    raise StorageError("IDENTITY_ALREADY_LINKED", "此身份已绑定，请使用已有账号", 409)
                existing = duplicate
            if existing is None:
                account_id = opaque_id("pa")
                tx._conn.execute("""INSERT INTO provider_accounts
                    (tenant_id,id,provider,issuer,subject,display_name,label,verified,state,
                     expires_at,last_verified_at,version,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,1,'connected',?,?,1,?,?)""",
                    (tx.tenant_id, account_id, identity.provider, identity.issuer, identity.subject,
                     identity.display_name, label, expires_at, now, now, now))
            else:
                account_id = existing["id"]
                # Preserve user label for a repeated authorization, including recovery.
                tx._conn.execute("""UPDATE provider_accounts SET issuer=?,subject=?,display_name=?,
                    verified=1,state='connected',expires_at=?,last_verified_at=?,reason=NULL,
                    version=version+1,removed_at=NULL,updated_at=? WHERE tenant_id=? AND id=?""",
                    (identity.issuer, identity.subject, identity.display_name, expires_at, now, now, tx.tenant_id, account_id))
            tx.secret_put("provider-grants", account_id, credentials)
            return self._public(self._row(tx, account_id))

    def mark_authorization(self, ctx, account_id, state, *, expected_version, reason):
        if state not in {"unconfigured", "authorizing", "expired", "revoked", "error"} or reason not in _REASONS:
            raise invalid("授权状态不符合要求")
        with self.store.transaction(ctx) as tx:
            row = self._row(tx, account_id)
            if row["version"] != version(expected_version):
                raise conflict()
            if row["removed_at"] is not None:
                raise not_found()
            tx._conn.execute("UPDATE provider_accounts SET state=?,reason=?,version=version+1,updated_at=? WHERE tenant_id=? AND id=?",
                             (state, reason, utc(self.store.clock()), tx.tenant_id, account_id))
            if state in {"revoked", "error", "unconfigured"}:
                tx.secret_delete("provider-grants", account_id)
            return self._public(self._row(tx, account_id))

    def credentials(self, ctx, account_id, *, for_refresh=False):
        """Server-only. Never put this return value in a response or logger."""
        with self.store.transaction(ctx, readonly=True) as tx:
            row = self._row(tx, account_id)
            account = self._public(row)
            allowed = {"connected", "expired"} if for_refresh else {"connected"}
            if account["authorization"]["state"] not in allowed or not account["identity"]["verified"]:
                raise StorageError("AUTHORIZATION_REQUIRED", "该账号需要重新授权", 409)
            return tx.secret_get("provider-grants", account_id)

    def remove_local(self, ctx, account_id, *, expected_version):
        """Destroy local usable grant; retain identity tombstone and historical data.

        ProviderService separately attempts official remote revocation and reports
        confirmed/unsupported/failed. No remote cancellation or revocation is claimed
        here. Task workers must recheck authorization before each external operation.
        """
        with self.store.transaction(ctx) as tx:
            row = self._row(tx, account_id)
            if row["version"] != version(expected_version):
                raise conflict()
            if row["removed_at"] is None:
                now = utc(self.store.clock())
                tx._conn.execute("""INSERT INTO authorization_epochs VALUES(?,1)
                    ON CONFLICT(tenant_id) DO UPDATE SET epoch=epoch+1""", (tx.tenant_id,))
                tx._conn.execute("""UPDATE provider_accounts SET state='removed',reason='removed_by_user',
                    removed_at=?,updated_at=?,version=version+1 WHERE tenant_id=? AND id=?""",
                    (now, now, tx.tenant_id, account_id))
                tx.secret_delete("provider-grants", account_id)
                tx._conn.execute("UPDATE provider_spaces SET access='revoked' WHERE tenant_id=? AND provider_account_id=?", (tx.tenant_id, account_id))
                tx._conn.execute("UPDATE selections SET provider_account_id=NULL,space_id=NULL,revision=revision+1 WHERE tenant_id=? AND provider_account_id=?", (tx.tenant_id, account_id))
            # Return IDs for the task module to show blocked_authorization. Do not
            # rewrite another module's task state machine or immutable ownership.
            import json
            rows = tx._conn.execute("SELECT id,data FROM records WHERE tenant_id=? AND collection='tasks'", (tx.tenant_id,)).fetchall()
            affected = [item["id"] for item in rows if json.loads(item["data"]).get("ownership", {}).get("providerAccountId") == account_id]
            return {"removed": True, "affectedTaskIds": affected,
                    "account": self._public(self._row(tx, account_id))}


class SelectionRepository:
    """Persistence primitive for backend.spaces; performs no provider network I/O."""
    def __init__(self, store):
        self.store = store
        self.accounts = AccountRepository(store)

    @staticmethod
    def _get(tx):
        tx._check()
        row = tx._conn.execute("SELECT * FROM selections WHERE tenant_id=?", (tx.tenant_id,)).fetchone()
        if row is None:
            return {"providerAccountId": None, "spaceId": None, "revision": 0}
        return {"providerAccountId": row["provider_account_id"], "spaceId": row["space_id"], "revision": row["revision"]}

    def get(self, ctx):
        with self.store.transaction(ctx, readonly=True) as tx:
            return self._get(tx)

    def replace_spaces(self, ctx, account_id, spaces):
        """Accept only a successful official result; failure uses invalidate_spaces.

        This snapshot is partitioned by login identity even if two identities have
        identical upstream workspace IDs. It does not create login identities.
        """
        if not isinstance(spaces, list) or len(spaces) > 10000:
            raise invalid()
        parsed, ids = [], set()
        for space in spaces:
            if not isinstance(space, dict):
                raise invalid()
            # Upstream IDs are data (not filesystem paths), so allow their actual
            # opaque format rather than requiring our internal ID prefix.
            space_id = space.get("id")
            if (not isinstance(space_id, str) or not 1 <= len(space_id) <= 256
                    or any(ord(c) < 32 for c in space_id) or space_id in ids):
                raise invalid("空间标识无效或重复")
            if space.get("kind") not in {"personal", "team"} or space.get("access") not in {"available", "revoked", "unknown"}:
                raise invalid()
            ids.add(space_id)
            parsed.append((space_id, space["kind"], _label(space.get("name")), space["access"]))
        with self.store.transaction(ctx) as tx:
            row = self.accounts._row(tx, account_id)
            if self.accounts._public(row)["authorization"]["state"] != "connected":
                raise StorageError("AUTHORIZATION_REQUIRED", "请先恢复账号授权", 409)
            now = utc(self.store.clock())
            # Keep removed space names for history; they can no longer be selected.
            tx._conn.execute("UPDATE provider_spaces SET access='revoked',checked_at=? WHERE tenant_id=? AND provider_account_id=?", (now, tx.tenant_id, account_id))
            for item in parsed:
                tx._conn.execute("""INSERT INTO provider_spaces VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(tenant_id,provider_account_id,id) DO UPDATE SET
                    kind=excluded.kind,name=excluded.name,access=excluded.access,checked_at=excluded.checked_at""",
                    (tx.tenant_id, account_id, *item, now))

    def invalidate_spaces(self, ctx, account_id):
        with self.store.transaction(ctx) as tx:
            self.accounts._row(tx, account_id)
            tx._conn.execute("UPDATE provider_spaces SET access='unknown',checked_at=? WHERE tenant_id=? AND provider_account_id=?",
                             (utc(self.store.clock()), tx.tenant_id, account_id))

    def list_spaces(self, ctx, account_id):
        with self.store.transaction(ctx, readonly=True) as tx:
            self.accounts._row(tx, account_id)
            rows = tx._conn.execute("SELECT * FROM provider_spaces WHERE tenant_id=? AND provider_account_id=? ORDER BY id", (tx.tenant_id, account_id)).fetchall()
            return {"items": [{"id": row["id"], "kind": row["kind"], "name": row["name"],
                               "access": row["access"], "checkedAt": row["checked_at"]} for row in rows], "nextCursor": None}

    def _space(self, tx, account_id, space_id):
        if not isinstance(space_id, str):
            raise not_found()
        row = tx._conn.execute("SELECT * FROM provider_spaces WHERE tenant_id=? AND provider_account_id=? AND id=?",
                               (tx.tenant_id, account_id, space_id)).fetchone()
        if row is None:
            raise not_found()
        if row["access"] != "available":
            raise StorageError("SPACE_UNAVAILABLE", "该空间访问权限尚未确认或已失效", 409)
        return row

    def set(self, ctx, provider_account_id, space_id, *, expected_revision):
        with self.store.transaction(ctx) as tx:
            return self.set_in_transaction(tx, provider_account_id, space_id, expected_revision=expected_revision)

    def set_in_transaction(self, tx, provider_account_id, space_id, *, expected_revision):
        tx._check(write=True)
        if type(expected_revision) is not int or expected_revision < 0:
            raise invalid("必须提供有效的 expectedRevision")
        current = self._get(tx)
        if current["revision"] != expected_revision:
            raise conflict("SELECTION_CHANGED")
        if provider_account_id is None:
            if space_id is not None:
                raise invalid("未选择登录身份时不能选择空间")
        else:
            account = self.accounts._public(self.accounts._row(tx, provider_account_id))
            if account["removedAt"] is not None:
                raise not_found()
            if space_id is not None:
                self._space(tx, provider_account_id, space_id)
        tx._conn.execute("""INSERT INTO selections VALUES(?,?,?,?)
            ON CONFLICT(tenant_id) DO UPDATE SET provider_account_id=excluded.provider_account_id,
            space_id=excluded.space_id,revision=excluded.revision""",
            (tx.tenant_id, provider_account_id, space_id, expected_revision + 1))
        return self._get(tx)

    def bind_ownership(self, tx, *, expected_revision):
        """Use inside the SAME transaction that inserts a task + idempotency result."""
        tx._check()
        current = self._get(tx)
        if type(expected_revision) is not int or current["revision"] != expected_revision:
            raise conflict("SELECTION_CHANGED")
        if current["providerAccountId"] is None or current["spaceId"] is None:
            raise StorageError("SELECTION_REQUIRED", "请选择登录身份及个人或团队空间", 409)
        account = self.accounts._public(self.accounts._row(tx, current["providerAccountId"]))
        if account["authorization"]["state"] != "connected" or not account["identity"]["verified"]:
            raise StorageError("AUTHORIZATION_REQUIRED", "请先恢复此账号的授权", 409)
        space = self._space(tx, current["providerAccountId"], current["spaceId"])
        return {"tenantId": tx.tenant_id, "provider": account["provider"], "providerAccountId": account["id"],
                "providerSubject": account["identity"]["subject"], "spaceId": space["id"], "spaceKind": space["kind"],
                "boundAt": utc(self.store.clock()), "accountLabelAtCreation": account["label"],
                "spaceNameAtCreation": space["name"]}

    def assert_ownership_available(self, ctx, ownership):
        """Resolve ONLY the stored owner; current selection is deliberately ignored."""
        with self.store.transaction(ctx, readonly=True) as tx:
            if not isinstance(ownership, dict) or ownership.get("tenantId") != tx.tenant_id:
                raise not_found()
            account = self.accounts._public(self.accounts._row(tx, ownership.get("providerAccountId")))
            if (account["provider"] != ownership.get("provider") or account["identity"]["subject"] != ownership.get("providerSubject")):
                raise StorageError("OWNERSHIP_MISMATCH", "任务账号身份不一致", 409)
            if account["authorization"]["state"] != "connected":
                raise StorageError("AUTHORIZATION_REQUIRED", "原任务账号需要恢复授权", 409)
            space = self._space(tx, account["id"], ownership.get("spaceId"))
            if space["kind"] != ownership.get("spaceKind"):
                raise StorageError("OWNERSHIP_MISMATCH", "任务空间类型已发生变化", 409)
            return account
