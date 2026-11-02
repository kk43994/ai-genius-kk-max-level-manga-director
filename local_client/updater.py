"""Official-feed desktop updates; never replace workspace data or running files."""
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin, urlsplit

from backend.storage.platform_fs import private_directory, open_private, no_links

FEED = 'https://kk666.best/asset-lab/release.json'
MAX_INSTALLER = 512 * 1024 * 1024


def version_key(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|preview|rc)\.(\d+))?', str(value))
    if not match:
        raise ValueError('更新版本格式无效')
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch),
            {'alpha': 0, 'beta': 1, 'preview': 2, 'rc': 3, None: 4}[stage], int(number or 0))


def platform_key():
    if sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64'):
        return 'windows-x64'
    if sys.platform == 'darwin' and platform.machine().lower() in ('arm64', 'aarch64'):
        return 'macos-arm64'
    return None


def installer_record(manifest, target):
    if not isinstance(manifest, dict) or manifest.get('product') != 'AssetLab' or manifest.get('channel') not in ('stable', 'preview'):
        raise ValueError('更新来源或渠道不匹配')
    version_key(manifest.get('version'))
    rows = [r for r in manifest.get('installers', []) if isinstance(r, dict) and r.get('platform') == target]
    if len(rows) != 1:
        raise ValueError('当前系统尚无可用更新包')
    row = copy.deepcopy(rows[0])
    url = urlsplit(urljoin(FEED, str(row.get('url', ''))))
    extension = '.exe' if target == 'windows-x64' else '.pkg'
    if (url.scheme != 'https' or url.netloc != 'kk666.best' or url.query or url.fragment
            or not re.fullmatch(r'/asset-lab/downloads/[A-Za-z0-9._-]+' + re.escape(extension), url.path)):
        raise ValueError('更新包地址不属于官方发布目录')
    if not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256', ''))):
        raise ValueError('更新包缺少有效校验值')
    if type(row.get('bytes')) is not int or not 0 < row['bytes'] <= MAX_INSTALLER:
        raise ValueError('更新包大小无效')
    return dict(row, url=url.geturl(), version=manifest['version'], extension=extension)


def official_read(url, limit, sink=None):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'kk666.best' or parsed.query or parsed.fragment:
        raise ValueError('更新来源无效')
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=30)
    try:
        connection.request('GET', parsed.path, headers={'User-Agent': 'AssetLab-Desktop-Updater/1'})
        response = connection.getresponse()
        # Do not follow redirects to another download source.
        if response.status != 200:
            raise ValueError('官方更新源暂不可用，请稍后检查')
        total, blocks, deadline = 0, [], time.monotonic() + 600
        while True:
            block = response.read(min(65536, limit - total + 1))
            if not block:
                break
            total += len(block)
            if total > limit or time.monotonic() > deadline:
                raise ValueError('更新下载超出大小或时间限制')
            if sink:
                sink.write(block)
            else:
                blocks.append(block)
        return total if sink else b''.join(blocks)
    finally:
        connection.close()


def verified_file(path, row):
    no_links(path)
    if not path.is_file() or path.stat().st_size != row['bytes']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            digest.update(block)
    return digest.hexdigest() == row['sha256']


class DesktopUpdater:
    def __init__(self, instance, version, *, target=None, packaged=False, reader=official_read):
        self.root = Path(instance) / 'updates'
        no_links(self.root); private_directory(self.root)
        self.version, self.target, self.packaged, self.reader = version, target or platform_key(), packaged, reader
        self.lock, self.stop_event = threading.RLock(), threading.Event()
        self.row, self.path, self.working = None, None, False
        self.state = {'enabled': True, 'status': 'idle', 'currentVersion': version,
                      'latestVersion': None, 'message': '自动检查并下载新版，安装前会保存并检查当前任务。',
                      'canInstall': False, 'packaged': packaged}
        settings = self.root / 'settings.json'
        no_links(settings)
        if settings.exists():
            try:
                data = json.loads(settings.read_text())
                if type(data.get('enabled')) is bool:
                    self.state['enabled'] = data['enabled']
            except (ValueError, OSError):
                pass

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('请选择有效的自动更新设置')
        with self.lock:
            temp = self.root / 'settings.tmp'
            no_links(temp)
            with os.fdopen(open_private(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), 'w') as handle:
                json.dump({'enabled': enabled}, handle)
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, self.root / 'settings.json')
            self.state['enabled'] = enabled
        if enabled:
            self.check()
        return self.snapshot()

    def check(self):
        with self.lock:
            if self.working or self.state['status'] == 'installing':
                return self.snapshot()
            self.working = True
            self.state.update(status='checking', message='正在检查官方更新…', canInstall=False)
        threading.Thread(target=self._check, daemon=True).start()
        return self.snapshot()

    def _check(self):
        try:
            manifest = json.loads(self.reader(FEED, 131072))
            row = installer_record(manifest, self.target)
            with self.lock:
                self.state['latestVersion'] = row['version']
            if version_key(row['version']) <= version_key(self.version):
                with self.lock:
                    self.state.update(status='current', message='当前版本无需更新。', canInstall=False)
                return
            path = self.root / (row['sha256'] + row['extension'])
            if not verified_file(path, row):
                with self.lock:
                    self.state.update(status='downloading', message='发现新版，正在自动下载…')
                temp = path.with_suffix(path.suffix + '.part')
                no_links(temp)
                try:
                    with os.fdopen(open_private(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC), 'wb') as handle:
                        self.reader(row['url'], row['bytes'], handle)
                        handle.flush(); os.fsync(handle.fileno())
                    if not verified_file(temp, row):
                        raise ValueError('更新包校验未通过，未替换程序')
                    os.replace(temp, path)
                finally:
                    temp.unlink(missing_ok=True)
            with self.lock:
                self.row, self.path = row, path
                self.state.update(status='ready', canInstall=self.packaged,
                    message='新版已下载并校验。保存后可退出并安装。' if self.packaged else '新版已下载并校验；当前为源码运行，请从官方页面安装客户端。')
        except Exception as error:
            with self.lock:
                self.state.update(status='error', canInstall=False,
                    message=str(error) if isinstance(error, ValueError) else '更新检查暂时失败，原程序与项目保持可用。')
        finally:
            with self.lock:
                self.working = False

    def start(self):
        def loop():
            if self.stop_event.wait(3): return
            while not self.stop_event.is_set():
                if self.snapshot()['enabled']: self.check()
                if self.stop_event.wait(4 * 60 * 60): break
        threading.Thread(target=loop, daemon=True).start()

    def install(self):
        with self.lock:
            if not self.packaged or self.state['status'] != 'ready' or not self.row or not verified_file(self.path, self.row):
                raise ValueError('更新包尚未准备好，请先检查更新')
            prefix = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('launch.py'))]
            command = prefix + ['--install-update-helper', str(os.getpid()), str(self.path),
                                self.row['sha256'], str(self.row['bytes']), self.row['version'], self.target]
            options = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            if getattr(sys, 'frozen', False):
                options['env'] = {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'}
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
            self.state.update(status='installing', canInstall=False, message='工作台即将退出；Windows 安装后重新打开，Mac 请完成系统安装窗口。')
            return self.snapshot()


def register_update_routes(app, updater, shutdown):
    from backend.app import APIError, Response
    def action(ctx, params, kind):
        try:
            if kind == 'install':
                cursor = None
                while True:
                    page = app.services.tasks.list(ctx, cursor=cursor, limit=100)
                    if any(t['status'] in {'preparing','submitting','queued','submitted','running','downloading'} for t in page['items']):
                        raise ValueError('还有任务正在处理，请完成后安装更新')
                    cursor = page.get('nextCursor')
                    if not cursor: break
                state = updater.install()
                threading.Thread(target=shutdown, daemon=True).start()
            elif kind == 'settings':
                state = updater.set_enabled((ctx.json or {}).get('enabled'))
            else:
                state = updater.check()
            return Response(body=state)
        except ValueError as error:
            raise APIError(409, 'UPDATE_NOT_READY', str(error)) from None
    app.router.add('GET', '/api/v1/local-runtime/update', lambda ctx, params: Response(body=updater.snapshot()))
    for kind in ('check', 'settings', 'install'):
        app.router.add('POST', '/api/v1/local-runtime/update/' + kind,
                       lambda ctx, params, kind=kind: action(ctx, params, kind))
