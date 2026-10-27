"""Isolated desktop development edition of the comic production workbench."""
import argparse
import base64
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from backend.app import APIError, Response
from backend.storage.platform_fs import private_directory
from local_client.launch import run
from manju_client import APP_NAME, APP_VERSION


def default_instance():
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA', '')
        if not base or not Path(base).is_absolute():
            raise ValueError('Cannot identify the local application directory')
        return Path(base) / 'ManjuWorkbenchDev'
    return Path.home() / 'Library/Application Support/ManjuWorkbenchDev'


def configure_workbench(app):
    """Serve only inventoried public prototype files; retain the existing API boundary."""
    root = app.config.frontend_dir
    manifest = json.loads((root / 'studio-inventory.json').read_text())
    allowed = set(manifest['files'])
    original = app.static
    base = app.config.public_base_path

    def serve(ctx):
        relative = ctx.path[len(base):] if ctx.path.startswith(base) else None
        if relative in ('', 'index.html'):
            relative = 'index.html'
        if relative not in allowed:
            return original(ctx)
        if ctx.method not in {'GET', 'HEAD'}:
            raise APIError(405, 'METHOD_NOT_ALLOWED', '此资源只支持读取')
        target = root / relative
        if not target.resolve().is_relative_to(root) or target.is_symlink() or not target.is_file():
            raise APIError(404, 'NOT_FOUND', '资源不存在')
        raw = target.read_bytes()
        mime = {'.glb':'model/gltf-binary', '.json':'application/json', '.md':'text/plain',
                '.txt':'text/plain'}.get(target.suffix) or mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        headers = {'Content-Type':mime, 'Cache-Control':'no-cache'}
        if target.suffix == '.html':
            # Import maps are immutable build content. Do not allow arbitrary inline scripts.
            scripts = re.findall(rb'<script type="importmap">(.*?)</script>', raw, re.S)
            hashes = ' '.join("'sha256-" + base64.b64encode(hashlib.sha256(s).digest()).decode() + "'" for s in scripts)
            headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self' " + hashes + "; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
            headers['Content-Type'] = 'text/html; charset=utf-8'
        return Response(body=raw, headers=headers)

    app.static = serve
    app.build_info.update(product='manju-workbench', channel='development')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path)
    parser.add_argument('--port', type=int, default=18878)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--frontend', type=Path)
    args = parser.parse_args()
    instance = (args.instance or default_instance()).absolute()
    try:
        private_directory(instance / 'logs')
        logging.basicConfig(filename=instance/'logs/launcher.log', level=logging.ERROR)
        return run(instance, port=args.port, open_browser=not args.no_browser,
                   frontend=args.frontend or SERVER/'frontend', version=APP_VERSION,
                   base_path='/workbench/', process_lock='Local\\ManjuWorkbench.Dev',
                   configure_app=configure_workbench)
    except Exception as error:
        logging.error('launcher_failed type=%s', type(error).__name__)
        message = '漫剧工作台暂时无法打开。请先退出正在运行的测试版，再双击桌面图标重试。'
        if os.name == 'nt' and not args.no_browser:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
        elif sys.platform == 'darwin' and getattr(sys, 'frozen', False) and not args.no_browser:
            subprocess.run([str(Path(sys.executable).parents[2]/'MacOS/ManjuWorkbench'),'--show-error'],check=False)
        else:
            print(message,file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
