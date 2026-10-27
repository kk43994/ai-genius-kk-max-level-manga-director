"""First-party site sessions; provider account switching never changes site ownership."""
from dataclasses import dataclass, field as dataclass_field
import hashlib
import hmac
from http.cookies import SimpleCookie
import re
import secrets
from urllib.parse import urlsplit

from backend.storage import SelectionRepository, StorageError, TenantContext, WorkspaceRepository
from backend.storage.core import checked_id, field, opaque_id, utc

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
DEFAULT_FEATURES = {"providerAuthorization": False, "imageGeneration": False,
                    "videoGeneration": False, "scriptAnalysis": False,
                    "persistentProjects": False}


@dataclass(frozen=True)
class SessionResult:
    context: TenantContext
    data: dict
    # Do not expose bearer cookies through accidental object repr/logging.
    set_cookie: str = dataclass_field(repr=False)


def _origin(value, *, local_http=False):
    try:
        parsed = urlsplit(value)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError()
        scheme = parsed.scheme.lower()
        if scheme != "https" and not (local_http and scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError()
        port = parsed.port
        host = parsed.hostname.lower()
        host = f"[{host}]" if ":" in host else host
        standard = 443 if scheme == "https" else 80
        return f"{scheme}://{host}" + (f":{port}" if port is not None and port != standard else "")
    except (ValueError, TypeError, AttributeError):
        raise StorageError("ORIGIN_INVALID", "站点来源配置无效", 500) from None


class SessionService:
    def __init__(self, store, *, public_origin, idle_seconds=30 * 86400,
                 absolute_seconds=90 * 86400, features=None):
        if (type(idle_seconds) is not int or type(absolute_seconds) is not int
                or not 60 <= idle_seconds <= absolute_seconds <= 366 * 86400):
            raise ValueError("Invalid session lifetime")
        self.store = store
        self.public_origin = _origin(public_origin, local_http=True)
        self.secure = self.public_origin.startswith("https:")
        self.cookie_name = "__Host-asset_lab_session" if self.secure else "asset_lab_session"
        self.idle_seconds, self.absolute_seconds = idle_seconds, absolute_seconds
        self.features = dict(DEFAULT_FEATURES)
        if features is not None:
            if not isinstance(features, dict) or any(k not in DEFAULT_FEATURES or type(v) is not bool for k, v in features.items()):
                raise ValueError("Features must be explicit verified capability flags")
            self.features.update(features)
        # This release is not authorized to enable final video submission.
        self.features["videoGeneration"] = False
        self.selections = SelectionRepository(store)

    def _cookie(self, token, max_age):
        cookie = SimpleCookie()
        cookie[self.cookie_name] = token
        morsel = cookie[self.cookie_name]
        morsel["path"] = "/"
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["max-age"] = max(0, int(max_age))
        if self.secure:
            morsel["secure"] = True
        if max_age <= 0:
            morsel["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        return morsel.OutputString()

    @staticmethod
    def _hash(token):
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise StorageError("SESSION_REQUIRED", "本站会话无效，请重新登录本站", 401)
        return hashlib.sha256(token.encode()).hexdigest()

    def token_from_cookie(self, cookie_header):
        if not cookie_header:
            return None
        if not isinstance(cookie_header, str) or len(cookie_header) > 16384:
            raise StorageError("SESSION_REQUIRED", "本站会话 Cookie 无效", 401)
        matches = [part for part in cookie_header.split(";") if part.strip().split("=", 1)[0] == self.cookie_name]
        if len(matches) > 1:
            raise StorageError("SESSION_REQUIRED", "本站会话 Cookie 重复", 401)
        try:
            cookie = SimpleCookie()
            cookie.load(cookie_header)
        except Exception:
            raise StorageError("SESSION_REQUIRED", "本站会话 Cookie 无效", 401) from None
        if self.cookie_name not in cookie:
            if matches:
                raise StorageError("SESSION_REQUIRED", "本站会话 Cookie 无效", 401)
            return None
        token = cookie[self.cookie_name].value
        self._hash(token)
        return token

    def _result(self, row, token, *, request_id=""):
        context = TenantContext(row["tenant_id"], row["id"], request_id)
        data = {"session": {"id": row["id"], "expiresAt": utc(row["expires_at"])},
                "tenant": {"id": row["tenant_id"]}, "csrfToken": self.store.csrf_for(row["id"]),
                "selection": self.selections.get(context), "features": dict(self.features),
                "workspace": WorkspaceRepository(self.store).get(context)}
        return SessionResult(context, data, self._cookie(token, row["expires_at"] - self.store.clock()))

    def _insert(self, conn, tenant_id, now):
        session_id, token = opaque_id("ss"), secrets.token_urlsafe(32)
        conn.execute("INSERT INTO site_sessions VALUES(?,?,?,?,?,?,?,NULL)",
                     (session_id, tenant_id, self._hash(token), now, now,
                      now + self.idle_seconds, now + self.absolute_seconds))
        return conn.execute("SELECT * FROM site_sessions WHERE id=?", (session_id,)).fetchone(), token

    def create(self, *, request_id=""):
        """First visit only. Does not accept a caller-provided tenant or session ID."""
        with self.store._system_transaction() as conn:
            now, tenant_id = self.store.clock(), opaque_id("tenant")
            conn.execute("INSERT INTO tenants VALUES(?,?)", (tenant_id, utc(now)))
            conn.execute("INSERT INTO selections VALUES(?,NULL,NULL,0)", (tenant_id,))
            row, token = self._insert(conn, tenant_id, now)
        return self._result(row, token, request_id=request_id)

    def restore(self, token, *, request_id="", touch=True):
        hashed, now = self._hash(token), self.store.clock()
        with self.store._system_transaction(write=touch) as conn:
            row = conn.execute("SELECT * FROM site_sessions WHERE token_hash=?", (hashed,)).fetchone()
            if row is None or row["revoked_at"] is not None or min(row["expires_at"], row["absolute_expires_at"]) <= now:
                raise StorageError("SESSION_REQUIRED", "本站会话已失效，请重新登录本站", 401)
            if touch:
                expires = min(now + self.idle_seconds, row["absolute_expires_at"])
                conn.execute("UPDATE site_sessions SET last_seen_at=?,expires_at=? WHERE id=?", (now, expires, row["id"]))
                row = conn.execute("SELECT * FROM site_sessions WHERE id=?", (row["id"],)).fetchone()
        return self._result(row, token, request_id=request_id)

    def bootstrap(self, cookie_header=None, *, request_id=""):
        token = self.token_from_cookie(cookie_header)
        # Invalid/expired cookies fail explicitly; never silently substitute another
        # customer while an existing cookie is supplied.
        return self.create(request_id=request_id) if token is None else self.restore(token, request_id=request_id)

    def _require(self, conn, ctx):
        session_id, tenant = field(ctx, "siteSessionId"), field(ctx, "tenantId")
        if not session_id or not tenant:
            raise StorageError("SESSION_REQUIRED", "需要本站会话", 401)
        row = conn.execute("SELECT * FROM site_sessions WHERE id=? AND tenant_id=?", (checked_id(session_id), checked_id(tenant))).fetchone()
        if row is None or row["revoked_at"] is not None or min(row["expires_at"], row["absolute_expires_at"]) <= self.store.clock():
            raise StorageError("SESSION_REQUIRED", "本站会话已失效", 401)
        return row

    def verify_mutation(self, ctx, *, origin, csrf_token):
        with self.store._system_transaction(write=False) as conn:
            row = self._require(conn, ctx)
        try:
            normalized_origin = _origin(origin, local_http=not self.secure)
        except StorageError:
            normalized_origin = None
        if (normalized_origin != self.public_origin or not isinstance(csrf_token, str) or not _TOKEN.fullmatch(csrf_token)
                or not hmac.compare_digest(csrf_token, self.store.csrf_for(row["id"]))):
            raise StorageError("CSRF_FAILED", "请求来源或 CSRF 校验失败，请刷新页面重试", 403)

    def rotate(self, ctx):
        """For verified site login boundaries. Never call for generation account switching."""
        with self.store._system_transaction() as conn:
            old = self._require(conn, ctx)
            now = self.store.clock()
            conn.execute("UPDATE site_sessions SET revoked_at=? WHERE id=?", (now, old["id"]))
            row, token = self._insert(conn, old["tenant_id"], now)
        return self._result(row, token, request_id=field(ctx, "requestId", ""))

    def logout(self, ctx, *, all_sessions=False):
        """Invalidate site access only. Never delete provider grants or project data."""
        with self.store._system_transaction() as conn:
            row = self._require(conn, ctx)
            if all_sessions:
                conn.execute("UPDATE site_sessions SET revoked_at=? WHERE tenant_id=? AND revoked_at IS NULL", (self.store.clock(), row["tenant_id"]))
            else:
                conn.execute("UPDATE site_sessions SET revoked_at=? WHERE id=?", (self.store.clock(), row["id"]))
        return self._cookie("", 0)
