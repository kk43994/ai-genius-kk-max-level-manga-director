"""Bounded images and DNS-pinned HTTPS. No cookies, auth headers or redirects."""
import hashlib
import http.client
import io
import ipaddress
import socket
import ssl
import time
import warnings
from urllib.parse import urlsplit

from PIL import Image
from .errors import GenerationError

MIMES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}


def inspect_image(raw, mime, *, max_bytes=32 * 1024 * 1024, max_pixels=40_000_000, sha256=None):
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise GenerationError('OUTPUT_INVALID')
    actual_hash = hashlib.sha256(raw).hexdigest()
    if sha256 is not None and actual_hash != sha256:
        raise GenerationError('OUTPUT_INVALID')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if (im.format not in MIMES or MIMES[im.format] != mime or getattr(im, 'n_frames', 1) != 1
                        or im.width * im.height > max_pixels or im.width <= 0 or im.height <= 0):
                    raise GenerationError('OUTPUT_INVALID')
                dimensions = (im.width, im.height)
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
    except GenerationError:
        raise
    except Exception:
        raise GenerationError('OUTPUT_INVALID') from None
    return actual_hash, dimensions


class SafeMediaTransfer:
    def __init__(self, allowed_hosts=(), *, evidence='', timeout=20, total_timeout=60,
                 resolver=socket.getaddrinfo, connector=None):
        self.hosts = frozenset(allowed_hosts)
        self.evidence, self.timeout, self.total_timeout = evidence, timeout, total_timeout
        self.resolver, self.connector = resolver, connector

    def preflight(self):
        if not self.hosts or not self.evidence:
            raise GenerationError('TRANSFER_HOST_UNVERIFIED')

    def _target(self, url):
        self.preflight()
        try:
            p = urlsplit(url)
            if (p.scheme != 'https' or not p.hostname or p.hostname not in self.hosts
                    or p.port not in (None, 443) or p.username or p.password or p.fragment
                    or any(ord(c) < 33 for c in url) or '\\' in url or len(url) > 16384):
                raise ValueError()
            addresses = self.resolver(p.hostname, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError()
            return p, addresses[0][4][0]
        except Exception:
            raise GenerationError('UNSAFE_MEDIA_URL') from None

    def _request(self, method, url, body, max_bytes):
        parsed, address = self._target(url)
        connection = None
        try:
            if self.connector:
                connection = self.connector(parsed.hostname, address, self.timeout)
            else:
                # Connect only to the already checked address; TLS still checks the official host.
                connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=self.timeout)
                raw_socket = socket.create_connection((address, 443), timeout=self.timeout)
                try:
                    connection.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=parsed.hostname)
                except BaseException:
                    raw_socket.close()
                    raise
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            headers = {'Accept': 'image/png,image/jpeg,image/webp'} if method == 'GET' else {'Content-Type': 'application/octet-stream'}
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            if response.status not in ({200} if method == 'GET' else {200, 201, 204}):
                raise GenerationError('MEDIA_TRANSFER_FAILED')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise GenerationError('OUTPUT_INVALID')
            chunks, size, deadline = [], 0, time.monotonic() + self.total_timeout
            while True:
                if time.monotonic() > deadline:
                    raise GenerationError('MEDIA_TRANSFER_FAILED')
                chunk = response.read(min(65536, max_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise GenerationError('OUTPUT_INVALID')
                chunks.append(chunk)
            if length is not None and size != int(length):
                raise GenerationError('MEDIA_TRANSFER_FAILED')
            return b''.join(chunks), (response.getheader('Content-Type') or '').split(';')[0].strip().lower()
        except GenerationError:
            raise
        except Exception:
            raise GenerationError('MEDIA_TRANSFER_FAILED') from None
        finally:
            if connection is not None:
                connection.close()

    def put(self, url, raw):
        self._request('PUT', url, raw, 1024 * 1024)

    def get(self, url, *, mime, max_bytes, max_pixels, sha256=None):
        raw, declared = self._request('GET', url, None, max_bytes)
        if declared != mime:
            raise GenerationError('OUTPUT_INVALID')
        inspect_image(raw, mime, max_bytes=max_bytes, max_pixels=max_pixels, sha256=sha256)
        return raw
