"""Opaque, tenant-partitioned blob files; no user-controlled filesystem paths."""
import hashlib
import os
import re
import stat

from .core import checked_id, opaque_id, utc
from .errors import StorageError, invalid, not_found
from . import platform_fs

MAX_BLOB_BYTES = 64 * 1024 * 1024
_MIME = re.compile(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+\Z")


def _directory(store, tenant, *, create=False):
    """Walk with dir_fd and O_NOFOLLOW, so swapping a path cannot escape root."""
    if os.name == "nt":
        path = store.data_dir / "tenants" / checked_id(tenant) / "blobs"
        platform_fs.no_links(path)
        if create:
            platform_fs.private_directory(path)
        if not path.is_dir():
            raise FileNotFoundError(path)
        return path
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(store.data_dir, flags)
    try:
        for part in ("tenants", checked_id(tenant), "blobs"):
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, flags, dir_fd=fd)
            info = os.fstat(next_fd)
            if not platform_fs.owned(info) or not platform_fs.private_mode(info):
                os.close(next_fd)
                raise StorageError("UNSAFE_DATA_PATH", "素材目录权限不安全", 500)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def put(store, ctx, content, *, mime):
    if not isinstance(content, bytes) or len(content) > MAX_BLOB_BYTES:
        raise invalid("素材需为字节数据且不超过 64 MiB")
    if not isinstance(mime, str) or not _MIME.fullmatch(mime):
        raise invalid("素材 MIME 无效")
    identifier, digest = opaque_id("blob"), hashlib.sha256(content).hexdigest()
    directory = None
    try:
        with store.transaction(ctx) as tx:
            directory = _directory(store, tx.tenant_id, create=True)
            fd = (platform_fs.open_private(directory / identifier, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                  if os.name == "nt" else os.open(identifier, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory))
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                os.fsync(directory)
            now = utc(store.clock())
            tx._conn.execute("INSERT INTO blobs VALUES(?,?,?,?,?,?)", (tx.tenant_id, identifier, digest, len(content), mime, now))
        return {"id": identifier, "sha256": digest, "size": len(content), "mime": mime, "createdAt": now}
    except BaseException as exc:
        if directory is not None:
            try:
                (directory / identifier).unlink() if os.name == "nt" else os.unlink(identifier, dir_fd=directory)
            except FileNotFoundError:
                pass
        if isinstance(exc, OSError):
            raise StorageError("BLOB_UNAVAILABLE", "素材存储不可用", 503) from None
        raise
    finally:
        if directory is not None and os.name != "nt":
            os.close(directory)


def get(store, ctx, identifier):
    checked_id(identifier)
    with store.transaction(ctx, readonly=True) as tx:
        row = tx._conn.execute("SELECT * FROM blobs WHERE tenant_id=? AND id=?", (tx.tenant_id, identifier)).fetchone()
        if row is None:
            raise not_found()
        directory = None
        try:
            directory = _directory(store, tx.tenant_id)
            fd = (platform_fs.open_private(directory / identifier, os.O_RDONLY) if os.name == "nt"
                  else os.open(identifier, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory))
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not platform_fs.owned(info)
                        or not platform_fs.private_mode(info) or info.st_size != row["size"] or info.st_size > MAX_BLOB_BYTES):
                    raise StorageError("BLOB_INTEGRITY_FAILED", "素材完整性校验失败", 503)
                content = handle.read(MAX_BLOB_BYTES + 1)
            if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                raise StorageError("BLOB_INTEGRITY_FAILED", "素材完整性校验失败", 503)
            return content, {"id": identifier, "sha256": row["sha256"], "size": row["size"], "mime": row["mime"]}
        except OSError:
            raise StorageError("BLOB_UNAVAILABLE", "素材暂不可读", 503) from None
        finally:
            if directory is not None and os.name != "nt":
                os.close(directory)
