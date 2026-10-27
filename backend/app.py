"""Offline development baseline; not a production or provider-connected server.

Only serves the explicit frontend tree and synthetic empty compatibility responses.
Sessions 2-10 implement their modules under docs/module-ownership.md.
"""
import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'
VERSION = '0.1.0-baseline'


class Handler(BaseHTTPRequestHandler):
    server_version = 'AssetLabBaseline/0.1'

    def send_bytes(self, status, raw, mime):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def reply(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode(),
                        'application/json; charset=utf-8')

    def do_GET(self):
        route = unquote(urlsplit(self.path).path)
        blank = json.loads((ROOT / 'examples/blank-project.json').read_text())
        responses = {
            '/api/health': {'ok': True, 'mode': 'offline-baseline', 'version': VERSION,
                            'generationEnabled': False, 'videoEnabled': False,
                            'customerReady': False},
            '/api/scripts': {'scripts': [], 'analysis': {'configured': False,
                            'status': 'not_configured'}},
            '/api/workflow/state': {'protocolVersion': 1, 'jobs': [], 'plans': [],
                            'recipes': {}, 'transport': 'unconfigured',
                            'generationStarted': False},
            '/api/execution': {'connected': False, 'provider': 'libtv', 'models': [],
                            'accountName': None, 'status': 'not_configured',
                            'message': '客户版官方授权模块尚未接入',
                            'balance': {'state': 'unknown', 'value': None,
                                        'reason': 'not_authorized'}},
            '/dashixiong-image-test/manifest.json': blank,
        }
        if route in responses:
            return self.reply(200, responses[route])
        if route.startswith('/api/'):
            return self.reply(501, {'error': '客户版模块尚未接入',
                                    'code': 'NOT_IMPLEMENTED', 'retryable': False})
        if route in ('/', '/index.html'):
            # Preserve the document's directory so its relative JS/CSS URLs resolve.
            self.send_response(302)
            self.send_header('Location', '/dashixiong-scene-studio/asset-lab.html')
            self.send_header('Content-Length', '0')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        prefix = '/dashixiong-scene-studio/'
        if not route.startswith(prefix):
            return self.reply(404, {'error': '资源不存在', 'code': 'NOT_FOUND'})
        relative = route[len(prefix):]
        path = (FRONTEND / relative).resolve()
        if (not path.is_relative_to(FRONTEND.resolve()) or not path.is_file()
                or path.suffix not in {'.html', '.js', '.css', '.svg', '.png', '.ico'}):
            return self.reply(404, {'error': '资源不存在', 'code': 'NOT_FOUND'})
        raw = path.read_bytes()
        if path.name == 'asset-lab.html':
            notice = ('<aside style="position:fixed;bottom:8px;right:12px;z-index:999;'
                      'background:#202723;color:#fff;padding:8px 12px;border-radius:8px;'
                      'font:12px sans-serif;pointer-events:none" role="status">'
                      '客户版开发基线 · 空白示例 · 授权、保存与生成尚未接入</aside>')
            raw = raw.replace(b'</body>', notice.encode() + b'</body>')
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self.send_bytes(200, raw, mime + ('; charset=utf-8' if path.suffix in
                        {'.html', '.js', '.css', '.svg'} else ''))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        # Do not import Execution/LibTV, launch a CLI, resume work or write customer data.
        self.close_connection = True
        self.reply(501, {'error': '客户版开发基线：此模块尚未接入，未保存或提交任务。',
                         'code': 'NOT_IMPLEMENTED', 'retryable': False,
                         'generationStarted': False})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=int(os.environ.get('ASSET_LAB_PORT', '8870')))
    args = parser.parse_args()
    if args.port == 8768:
        parser.error('8768 is reserved for the original workbench; choose a different port')
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Offline customer baseline: http://127.0.0.1:{args.port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
