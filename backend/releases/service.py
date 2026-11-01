"""Read-only version endpoints, independent of tenant/provider credentials."""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
import time
from .manifest import manifest_valid

NO_CACHE_HEADERS = {
    'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    'Pragma': 'no-cache', 'Expires': '0',
    'Content-Type': 'application/json; charset=utf-8',
    'X-Content-Type-Options': 'nosniff',
}
PUBLIC_ROUTES = (('GET', '/api/v1/version'), ('GET', '/api/v1/releases/latest'))


class ReleaseUnavailable(Exception):
    pass


@dataclass
class ReleaseResponse:
    status: int
    body: dict
    headers: dict = field(default_factory=lambda: dict(NO_CACHE_HEADERS))


class ReleaseService:
    def __init__(self, *, release_root, running_manifest, origin, base_path='/'):
        self.root = Path(release_root).resolve()
        self.origin, self.base_path = origin, base_path
        self._lock, self._cache = threading.Lock(), {}
        # A running backend retains its own metadata even after current switches.
        # No filesystem refresh here: starting a new process loads its new stamp.
        self._running = self._read(Path(running_manifest).resolve())

    def _read(self, path):
        try:
            if path.stat().st_size > 131072:
                raise ValueError('oversized')
            return manifest_valid(json.loads(path.read_text(encoding='utf-8')), self.origin, self.base_path)
        except (OSError, ValueError, TypeError, KeyError):
            raise ReleaseUnavailable('版本信息暂时不可用') from None

    def current(self):
        return deepcopy(self._running)

    def latest(self, channel='stable'):
        if channel not in ('stable', 'preview'):
            raise ValueError('channel 必须为 stable 或 preview')
        try:
            directory = (self.root / 'channels' / channel / 'current').resolve(strict=True)
            if directory.parent != self.root / 'releases':
                raise ReleaseUnavailable('版本目录不受信任')
            path = directory / 'release.json'
            stat = path.stat()
            key = (channel, str(path), stat.st_mtime_ns, stat.st_size)
        except OSError:
            raise ReleaseUnavailable('最新版本暂时不可用') from None
        with self._lock:
            cached = self._cache.get(channel)
            if cached and cached[0] == key and time.monotonic() - cached[1] < 3:
                return deepcopy(cached[2])
            value = self._read(path)
            if value['channel'] != channel:
                raise ReleaseUnavailable('版本渠道不匹配')
            self._cache[channel] = (key, time.monotonic(), value)
            return deepcopy(value)


def _get(source, name, default=None):
    return source.get(name, default) if isinstance(source, dict) else getattr(source, name, default)


def _reply(ctx, value=None, *, status=200, code=None, message=None):
    meta = {'requestId': _get(ctx, 'requestId', 'release'), 'apiVersion': 1}
    body = {'data': value, 'meta': meta} if status == 200 else {
        'error': {'code': code, 'message': message, 'retryable': status == 503, 'details': {}}, 'meta': meta}
    return ReleaseResponse(status=status, body=body)


def register_routes(router, services):
    """Three-argument router.add; PUBLIC_ROUTES declares metadata-only public reads.

    Responses contain the complete v1 envelope. The HTTP adapter sends body as-is
    and retains the no-store headers. services.releases is an initialized service.
    """
    def handle(ctx, params, latest=False):
        service = _get(services, 'releases')
        if service is None:
            return _reply(ctx, status=503, code='RELEASE_UNAVAILABLE', message='版本服务尚未配置')
        try:
            query = _get(ctx, 'query', {})
            channel = query.get('channel', 'stable')
            if isinstance(channel, list):
                if len(channel) != 1: raise ValueError('invalid channel')
                channel = channel[0]
            value = service.latest(channel) if latest else service.current()
            return _reply(ctx, value)
        except ValueError:
            return _reply(ctx, status=422, code='VALIDATION_FAILED', message='请选择有效的版本渠道')
        except ReleaseUnavailable:
            return _reply(ctx, status=503, code='RELEASE_UNAVAILABLE', message='版本信息暂时不可用，请稍后重试')
    router.add('GET', '/api/v1/version', lambda ctx, params: handle(ctx, params))
    router.add('GET', '/api/v1/releases/latest', lambda ctx, params: handle(ctx, params, True))
