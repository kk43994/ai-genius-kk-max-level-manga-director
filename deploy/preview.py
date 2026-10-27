#!/usr/bin/env python3
"""Loopback-only release-chain preview server; not the customer auth/API server."""
import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.releases import ReleaseService, register_routes
from deploy.release import pointer


def create_server(root, *, port=0, public_base_path='/', channel='preview'):
    root = Path(root).resolve()
    if not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*', public_base_path):
        raise ValueError('Invalid publicBasePath')
    class Router:
        routes = {}
        def add(self, method, path, handler): self.routes[path] = handler
    router = Router()
    class Handler(BaseHTTPRequestHandler):
        server_version = 'AssetLabReleasePreview/1'
        def log_message(self, *_): pass
        def send(self, status, body, headers=None):
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            for k, v in (headers or {}).items(): self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(body)
        def do_GET(self):
            url = urlsplit(self.path); route = unquote(url.path)
            if not route.startswith(public_base_path): return self.send(404, b'not found')
            relative = route[len(public_base_path):]
            api_path = '/' + relative
            if api_path in router.routes:
                response = router.routes[api_path]({'requestId':'preview-read', 'query':parse_qs(url.query)}, {})
                return self.send(response.status, json.dumps(response.body).encode(), response.headers)
            if relative.startswith('api/'): return self.send(404, b'not found')
            immutable = False
            if relative.startswith('releases/'):
                parts = relative.split('/', 2)
                if len(parts) != 3 or not re.fullmatch(r'[A-Za-z0-9._+-]+', parts[1]): return self.send(404, b'not found')
                directory = (root / 'releases' / parts[1] / 'public').resolve()
                if directory.parent.parent != root / 'releases': return self.send(404, b'not found')
                relative = parts[2]; immutable = True
            else:
                current = pointer(root, channel, 'current')
                if current is None: return self.send(503, b'release unavailable')
                directory = current / 'public'
            file = (directory / (relative or 'index.html')).resolve()
            if not file.is_relative_to(directory) or not file.is_file() or file.suffix.lower() not in {'.html','.css','.js','.mjs','.json','.svg','.png','.jpg','.jpeg','.webp','.ico','.woff','.woff2'}:
                return self.send(404, b'not found')
            headers = {'Content-Type':mimetypes.guess_type(file.name)[0] or 'application/octet-stream',
                       'X-Content-Type-Options':'nosniff',
                       'Cache-Control':'public, max-age=31536000, immutable' if immutable and file.suffix != '.html' else 'no-store'}
            return self.send(200, file.read_bytes(), headers)
        do_HEAD = do_GET
        def do_POST(self): self.send(405, b'read-only preview', {'Allow':'GET, HEAD'})
        do_PUT = do_POST
        do_DELETE = do_POST
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    origin = f'http://127.0.0.1:{server.server_port}'
    current = pointer(root, channel, 'current')
    if current is None: server.server_close(); raise ValueError('Install a preview artifact first')
    service = ReleaseService(release_root=root, running_manifest=current/'release.json', origin=origin, base_path=public_base_path)
    register_routes(router, {'releases':service})
    return server


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--port',type=int,default=0)
    p.add_argument('--public-base-path',default='/');p.add_argument('--channel',choices=['preview','stable'],default='preview');a=p.parse_args()
    if a.port in (8768,8870):p.error('8768/8870 reserved for other services')
    with create_server(a.root,port=a.port,public_base_path=a.public_base_path,channel=a.channel) as server:
        print(f'Loopback synthetic preview: http://127.0.0.1:{server.server_port}{a.public_base_path}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass

if __name__=='__main__':main()
