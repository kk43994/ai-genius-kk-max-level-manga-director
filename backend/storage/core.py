"""Tenant-scoped SQLite transactions, encrypted secrets and private blobs.

Only trusted server code constructs a context. Never construct it from a request
body's tenantId. No filesystem or legacy CLI credential discovery is performed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import StorageError, conflict, invalid, not_found
from . import platform_fs

SCHEMA_VERSION = 2
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,127}\Z")
_COLLECTION = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SECRET_KEYS = {"accesstoken", "refreshtoken", "clientsecret", "idtoken",
                "authorization", "cookie", "password", "codeverifier"}


@dataclass(frozen=True)
class TenantContext:
    tenantId: str
    siteSessionId: str | None = None
    requestId: str = ""


def field(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def opaque_id(prefix="obj"):
    return prefix + "_" + secrets.token_hex(16)


def checked_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise invalid("对象标识不符合要求")
    return value


def _collection(value):
    if not isinstance(value, str) or not _COLLECTION.fullmatch(value):
        raise invalid("存储集合不符合要求")
    return value


def version(value):
    if type(value) is not int or value < 1:
        raise invalid("必须提供有效的 expectedVersion")
    return value


def canonical_json(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise invalid("数据必须为有效 JSON") from None
    if len(raw.encode()) > 2 * 1024 * 1024:
        raise invalid("单条元数据过大")
    return raw


def request_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _no_credentials(value):
    """Reject recognizable secrets in general JSON; secrets use SecretRepository.

    This is defense in depth, not a content sanitizer. Callers must never put
    arbitrary raw provider responses or signed URLs into public metadata.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise invalid()
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if normalized in _SECRET_KEYS:
                raise invalid("授权秘密必须写入加密凭据存储")
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)


def _no_symlinks(path):
    try:
        platform_fs.no_links(path)
    except OSError:
        raise StorageError("UNSAFE_DATA_PATH", "数据路径不能经过链接", 500) from None


def _private_directory(path):
    try:
        platform_fs.private_directory(path)
    except OSError:
        raise StorageError("UNSAFE_DATA_PATH", "数据目录权限不符合要求", 500) from None


def _inside(path, root):
    return path == root or root in path.parents


class Store:
    def __init__(self, data_dir, *, encryption_key, release_root=None, clock=time.time):
        candidate = Path(data_dir).expanduser()
        if not candidate.is_absolute():
            raise StorageError("UNSAFE_DATA_PATH", "ASSET_LAB_DATA_DIR 必须为绝对路径", 500)
        _no_symlinks(candidate)
        self.data_dir = candidate.resolve()
        self.release_root = Path(release_root or Path(__file__).resolve().parents[2]).resolve()
        if _inside(self.data_dir, self.release_root) or _inside(self.release_root, self.data_dir):
            raise StorageError("UNSAFE_DATA_PATH", "数据目录与发布目录必须分离", 500)
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise StorageError("SECRET_KEY_REQUIRED", "需要独立配置 32 字节存储密钥", 500)
        self._cipher = AESGCM(encryption_key)
        self._csrf_key = hmac.digest(encryption_key, b"asset-lab/session-csrf/v1", "sha256")
        self.clock = clock
        _private_directory(self.data_dir)
        for name in ("private", "tenants", "backups"):
            _private_directory(self.data_dir / name)
        self.db_path = self.data_dir / "state.sqlite3"
        self.migrate()

    @classmethod
    def from_env(cls, *, release_root=None, environ=None, clock=time.time):
        env = os.environ if environ is None else environ
        data = env.get("ASSET_LAB_DATA_DIR")
        key_file = env.get("ASSET_LAB_SECRET_KEY_FILE")
        if not data or not key_file:
            raise StorageError("STORAGE_UNCONFIGURED", "尚未配置独立数据目录与密钥文件", 503)
        data_path, key_path = Path(data), Path(key_file)
        release = Path(release_root or Path(__file__).resolve().parents[2]).resolve()
        if not data_path.is_absolute() or not key_path.is_absolute():
            raise StorageError("UNSAFE_DATA_PATH", "数据和密钥配置必须为绝对路径", 500)
        _no_symlinks(key_path)
        if _inside(key_path.resolve(), data_path.resolve()) or _inside(key_path.resolve(), release):
            raise StorageError("UNSAFE_SECRET_PATH", "密钥必须独立于数据和发布目录", 500)
        try:
            fd = platform_fs.open_private(key_path, os.O_RDONLY)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or not platform_fs.owned(info)
                        or not platform_fs.private_mode(info) or info.st_nlink != 1):
                    raise StorageError("UNSAFE_SECRET_PATH", "密钥文件需为当前服务用户独占的普通文件", 500)
                encoded = handle.read(256).strip()
            key = base64.b64decode(encoded, validate=True)
        except StorageError:
            raise
        except (OSError, ValueError):
            raise StorageError("SECRET_KEY_REQUIRED", "无法读取有效的存储密钥", 500) from None
        return cls(data, encryption_key=key, release_root=release, clock=clock)

    def _connect(self):
        _no_symlinks(self.data_dir)
        for path in (self.db_path, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or not platform_fs.owned(info)
                        or info.st_nlink != 1):
                    raise StorageError("UNSAFE_DATA_PATH", "数据库文件路径不安全", 500)
                path.chmod(0o600)
        # Create the initial database without a permissive umask window.
        fd = platform_fs.open_private(self.db_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        connection = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    @contextmanager
    def _system_transaction(self, *, write=True):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.OperationalError:
            connection.rollback()
            raise StorageError("STORAGE_UNAVAILABLE", "存储暂不可用，请稍后重试", 503, retryable=True) from None
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self):
        with self._system_transaction() as conn:
            existing = conn.execute("PRAGMA user_version").fetchone()[0]
            if existing > SCHEMA_VERSION:
                raise StorageError("SCHEMA_INCOMPATIBLE", "数据版本较新，禁止使用旧版本写入", 503)
            if existing:
                self._verify_key(conn)
            else:
                # executescript implicitly commits; keep migrations atomic instead.
                from .schema import STATEMENTS
                for statement in STATEMENTS:
                    conn.execute(statement)
                probe = self._seal("system", "key-check", "v1", {"check": "asset-lab-storage-v1"})
                conn.execute("INSERT INTO settings(key,value) VALUES('key_check',?)", (probe,))
                existing = 1
            if existing < 2:
                from .workspace_schema import STATEMENTS_V2
                for statement in STATEMENTS_V2:
                    conn.execute(statement)
            conn.execute("PRAGMA user_version=2")

    def _verify_key(self, conn):
        row = conn.execute("SELECT value FROM settings WHERE key='key_check'").fetchone()
        if row is None:
            raise StorageError("STORAGE_CORRUPT", "存储配置不完整", 500)
        self._unseal("system", "key-check", "v1", row[0])

    def readiness(self):
        with self._system_transaction(write=False) as conn:
            schema = conn.execute("PRAGMA user_version").fetchone()[0]
        return {"ready": schema == SCHEMA_VERSION,
                "reason": "schema_ready" if schema == SCHEMA_VERSION else "schema_incompatible",
                "dataSchemaVersion": schema}

    def _seal(self, tenant, namespace, identifier, value):
        nonce = secrets.token_bytes(12)
        aad = canonical_json(["asset-lab-v1", tenant, namespace, identifier]).encode()
        return b"\x01" + nonce + self._cipher.encrypt(nonce, canonical_json(value).encode(), aad)

    def _unseal(self, tenant, namespace, identifier, sealed):
        try:
            if not isinstance(sealed, bytes) or sealed[:1] != b"\x01":
                raise ValueError()
            aad = canonical_json(["asset-lab-v1", tenant, namespace, identifier]).encode()
            return json.loads(self._cipher.decrypt(sealed[1:13], sealed[13:], aad))
        except (InvalidTag, ValueError, TypeError):
            raise StorageError("SECRET_UNAVAILABLE", "无法读取授权凭据，请检查密钥或重新授权", 503) from None

    def csrf_for(self, session_id):
        return base64.urlsafe_b64encode(hmac.digest(self._csrf_key, checked_id(session_id).encode(), "sha256")).rstrip(b"=").decode()

    @contextmanager
    def transaction(self, ctx, *, readonly=False):
        tenant = field(ctx, "tenantId")
        if tenant is None:
            raise StorageError("SESSION_REQUIRED", "请重新打开本站会话", 401)
        checked_id(tenant)
        with self._system_transaction(write=not readonly) as conn:
            if not conn.execute("SELECT 1 FROM tenants WHERE id=?", (tenant,)).fetchone():
                raise StorageError("SESSION_REQUIRED", "本站会话无效", 401)
            session_id = field(ctx, "siteSessionId")
            if session_id is not None:
                session = conn.execute("SELECT 1 FROM site_sessions WHERE id=? AND tenant_id=? AND revoked_at IS NULL AND expires_at>? AND absolute_expires_at>?",
                                       (checked_id(session_id), tenant, self.clock(), self.clock())).fetchone()
                if session is None:
                    raise StorageError("SESSION_REQUIRED", "本站会话已失效", 401)
            tx = Transaction(self, conn, tenant, readonly=readonly)
            try:
                yield tx
            finally:
                tx.closed = True

    def get(self, ctx, collection, identifier):
        with self.transaction(ctx, readonly=True) as tx:
            return tx.get(collection, identifier)

    def list(self, ctx, collection, *, limit=100, after=None):
        with self.transaction(ctx, readonly=True) as tx:
            return tx.list(collection, limit=limit, after=after)

    def create(self, ctx, collection, data, **kwargs):
        with self.transaction(ctx) as tx:
            return tx.create(collection, data, **kwargs)

    def update(self, ctx, collection, identifier, data, *, expected_version):
        with self.transaction(ctx) as tx:
            return tx.update(collection, identifier, data, expected_version=expected_version)

    def idempotency(self, ctx, key, request_hash_value, operation, *, scope):
        """operation(tx) must do local writes only; never call a provider here."""
        with self.transaction(ctx) as tx:
            return tx.idempotency(key, request_hash_value, operation, scope=scope)

    def blob_put(self, ctx, content, *, mime="application/octet-stream"):
        from .blobs import put
        return put(self, ctx, content, mime=mime)

    def blob_get(self, ctx, identifier):
        from .blobs import get
        return get(self, ctx, identifier)


class Transaction:
    def __init__(self, store, connection, tenant, *, readonly=False):
        self.store, self._conn, self.tenant_id = store, connection, tenant
        self.readonly, self.closed = readonly, False

    def _check(self, *, write=False):
        if self.closed or (write and self.readonly):
            raise StorageError("TRANSACTION_INVALID", "存储事务已关闭或不可写", 500)

    @staticmethod
    def _record(row):
        return {"id": row["id"], "tenantId": row["tenant_id"], "collection": row["collection"],
                "version": row["version"], "data": json.loads(row["data"]),
                "createdAt": row["created_at"], "updatedAt": row["updated_at"]}

    def _row(self, collection, identifier):
        self._check()
        row = self._conn.execute("SELECT * FROM records WHERE tenant_id=? AND collection=? AND id=?",
                                 (self.tenant_id, _collection(collection), checked_id(identifier))).fetchone()
        if row is None:
            raise not_found()
        return row

    def get(self, collection, identifier):
        return self._record(self._row(collection, identifier))

    def list(self, collection, *, limit=100, after=None):
        self._check()
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise invalid()
        if after is not None:
            checked_id(after)
        rows = self._conn.execute("SELECT * FROM records WHERE tenant_id=? AND collection=? AND id>? ORDER BY id LIMIT ?",
                                  (self.tenant_id, _collection(collection), after or "", limit + 1)).fetchall()
        items = [self._record(row) for row in rows[:limit]]
        return {"items": items, "nextCursor": items[-1]["id"] if len(rows) > limit else None}

    def _validate_data(self, data):
        if not isinstance(data, dict):
            raise invalid()
        _no_credentials(data)
        if "tenantId" in data and data["tenantId"] != self.tenant_id:
            raise StorageError("OWNERSHIP_MISMATCH", "不能更改对象的客户归属", 409)
        owner = data.get("ownership")
        if owner is not None and (not isinstance(owner, dict) or owner.get("tenantId") != self.tenant_id):
            raise StorageError("OWNERSHIP_MISMATCH", "对象归属与当前客户不一致", 409)
        return canonical_json(data)

    def create(self, collection, data, *, record_id=None, immutable_fields=("ownership",)):
        self._check(write=True)
        collection = _collection(collection)
        identifier = checked_id(record_id) if record_id is not None else opaque_id("obj")
        encoded = self._validate_data(data)
        if not isinstance(immutable_fields, (list, tuple)) or not all(isinstance(k, str) for k in immutable_fields):
            raise invalid()
        # Ownership is always immutable, including attempts to add it after creation.
        immutables = canonical_json(sorted(set(immutable_fields) | {"ownership", "tenantId"}))
        now = utc(self.store.clock())
        try:
            self._conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)",
                               (self.tenant_id, collection, identifier, 1, encoded, immutables, now, now, None))
        except sqlite3.IntegrityError:
            raise conflict() from None
        return self.get(collection, identifier)

    def update(self, collection, identifier, data, *, expected_version):
        self._check(write=True)
        row = self._row(collection, identifier)
        if row["version"] != version(expected_version):
            raise conflict()
        encoded = self._validate_data(data)
        before = json.loads(row["data"])
        for key in json.loads(row["immutable_fields"]):
            if (key in before) != (key in data) or before.get(key) != data.get(key):
                raise StorageError("OWNERSHIP_MISMATCH", "不能更改历史对象的固定归属", 409)
        self._conn.execute("UPDATE records SET data=?,version=version+1,updated_at=? WHERE tenant_id=? AND collection=? AND id=? AND version=?",
                           (encoded, utc(self.store.clock()), self.tenant_id, collection, identifier, expected_version))
        return self.get(collection, identifier)

    def delete(self, collection, identifier, *, expected_version):
        self._check(write=True)
        row = self._row(collection, identifier)
        if row["version"] != version(expected_version):
            raise conflict()
        self._conn.execute("DELETE FROM records WHERE tenant_id=? AND collection=? AND id=?",
                           (self.tenant_id, collection, identifier))

    def secret_put(self, namespace, identifier, value):
        self._check(write=True)
        _collection(namespace)
        checked_id(identifier)
        sealed = self.store._seal(self.tenant_id, namespace, identifier, value)
        self._conn.execute("INSERT INTO secrets(tenant_id,namespace,id,ciphertext) VALUES(?,?,?,?) ON CONFLICT(tenant_id,namespace,id) DO UPDATE SET ciphertext=excluded.ciphertext",
                           (self.tenant_id, namespace, identifier, sealed))

    def secret_get(self, namespace, identifier):
        self._check()
        row = self._conn.execute("SELECT ciphertext FROM secrets WHERE tenant_id=? AND namespace=? AND id=?",
                                 (self.tenant_id, _collection(namespace), checked_id(identifier))).fetchone()
        if row is None:
            raise not_found()
        return self.store._unseal(self.tenant_id, namespace, identifier, row[0])

    def secret_delete(self, namespace, identifier):
        self._check(write=True)
        self._conn.execute("DELETE FROM secrets WHERE tenant_id=? AND namespace=? AND id=?",
                           (self.tenant_id, _collection(namespace), checked_id(identifier)))

    def idempotency(self, key, request_hash_value, operation, *, scope):
        self._check(write=True)
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise invalid("幂等键不符合要求")
        if not isinstance(scope, str) or not 1 <= len(scope) <= 200:
            raise invalid()
        if not isinstance(request_hash_value, str) or not re.fullmatch(r"[0-9a-f]{64}", request_hash_value):
            raise invalid()
        # Hash keys so a mistakenly sensitive idempotency header isn't stored raw.
        digest = hashlib.sha256(key.encode()).hexdigest()
        row = self._conn.execute("SELECT * FROM idempotency WHERE tenant_id=? AND scope=? AND key_hash=?",
                                 (self.tenant_id, scope, digest)).fetchone()
        if row is not None:
            if not hmac.compare_digest(row["request_hash"], request_hash_value):
                raise conflict("IDEMPOTENCY_CONFLICT")
            return json.loads(row["response"])
        result = operation(self)
        _no_credentials(result)
        self._conn.execute("INSERT INTO idempotency VALUES(?,?,?,?,?,?)",
                           (self.tenant_id, scope, digest, request_hash_value,
                            canonical_json(result), utc(self.store.clock())))
        return result

    def claim_lease(self, resource, holder, *, ttl=60):
        """Cross-process worker fencing. A claimant must keep the returned fence."""
        self._check(write=True)
        checked_id(resource)
        checked_id(holder)
        if type(ttl) is not int or not 1 <= ttl <= 3600:
            raise invalid()
        now = self.store.clock()
        row = self._conn.execute("SELECT * FROM leases WHERE tenant_id=? AND resource=?", (self.tenant_id, resource)).fetchone()
        if row and row["expires_at"] > now:
            raise conflict("LEASE_BUSY")
        fence = row["fence"] + 1 if row else 1
        self._conn.execute("INSERT INTO leases VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,resource) DO UPDATE SET holder=excluded.holder,fence=excluded.fence,expires_at=excluded.expires_at",
                           (self.tenant_id, resource, holder, fence, now + ttl))
        return {"resource": resource, "holder": holder, "fence": fence, "expiresAt": utc(now + ttl)}

    def assert_lease(self, resource, holder, fence):
        self._check()
        row = self._conn.execute("SELECT * FROM leases WHERE tenant_id=? AND resource=?",
                                 (self.tenant_id, checked_id(resource))).fetchone()
        if not row or row["holder"] != holder or row["fence"] != fence or row["expires_at"] <= self.store.clock():
            raise conflict("LEASE_LOST")

    def renew_lease(self, resource, holder, fence, *, ttl=60):
        self._check(write=True)
        if type(ttl) is not int or not 1 <= ttl <= 3600:
            raise invalid()
        self.assert_lease(resource, holder, fence)
        self._conn.execute("UPDATE leases SET expires_at=? WHERE tenant_id=? AND resource=? AND holder=? AND fence=?",
                           (self.store.clock() + ttl, self.tenant_id, resource, holder, fence))

    def release_lease(self, resource, holder, fence):
        self._check(write=True)
        self.assert_lease(resource, holder, fence)
        # Preserve fence history; deleting the row would let a stale worker regain it.
        self._conn.execute("UPDATE leases SET expires_at=0 WHERE tenant_id=? AND resource=?", (self.tenant_id, resource))
