"""Developer-only official OAuth probe. Customer deployment must use backend.auth.

No CLI credentials or browser storage are read. Secrets are encrypted under an
operator-supplied key outside the repository; only loopback is served. Callback
completion is deliberately called identity-unverified until an official subject
read is audited. This is not a production session or account implementation.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

from backend.auth.errors import AuthError
from backend.auth.secrets import AesGcmSecretCodec
from backend.providers.libtv_identity import MCPReadSession
from backend.providers.libtv_oauth import ClientRegistration, LibTVOAuth, OAuthConfig, ISSUER


def shape(value, depth=0):
    if depth > 7:
        return type(value).__name__
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return {'type': 'array', 'length': len(value), 'itemShape': shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18872)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--read-tool')
    parser.add_argument('--arguments', default='{}')
    args = parser.parse_args()
    if args.port in (8768, 8870) or not 1024 <= args.port <= 65535:
        parser.error('Use an isolated unprivileged development port.')
    root = Path(__file__).resolve().parents[2]
    data = args.data_dir.resolve()
    key_file = args.key_file.resolve()
    if root in data.parents or root == data or data in key_file.parents or root in key_file.parents:
        parser.error('Probe data and encryption key must be separate and outside the repository.')
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    data.chmod(0o700)
    if key_file.stat().st_mode & 0o077:
        parser.error('Key file must have mode 0600 or stricter.')
    codec = AesGcmSecretCodec({'probe': base64.b64decode(key_file.read_bytes().strip(), validate=True)}, 'probe')
    private_file = data / 'private.enc'
    lock = threading.RLock()

    def load():
        return codec.open(private_file.read_text(), binding='developer-official-oauth-probe') if private_file.exists() else {}

    def save(value):
        encrypted = codec.seal(value, binding='developer-official-oauth-probe')
        tmp = private_file.with_suffix('.tmp')
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, private_file)

    oauth = LibTVOAuth(OAuthConfig(f'http://127.0.0.1:{args.port}/api/v1/oauth/libtv/callback',
                                 allow_loopback_development=True))
    if args.read_tool:
        private = load()
        tokens = private.get('tokens')
        if not tokens or tokens['expires_at'] <= time.time():
            parser.error('Authorize locally first; no usable token is available.')
        session = MCPReadSession(oauth.http, tokens['access_token'])
        tools = session.tools()
        matches = [t for t in tools if t.get('name') == args.read_tool]
        if len(matches) != 1 or matches[0].get('annotations', {}).get('readOnlyHint') is not True:
            parser.error('Tool was not officially advertised as read-only.')
        if matches[0].get('annotations', {}).get('destructiveHint') is True:
            parser.error('Destructive tool is forbidden in this probe.')
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            parser.error('Arguments must be an object.')
        result = session.read_identity(matches[0], arguments)
        private.setdefault('reads', {})
        if private.get('lastRead'):
            private['reads'][private['lastRead']['tool']] = private['lastRead']['result']
        private['lastRead'] = {'tool': args.read_tool, 'result': result}
        private['reads'][args.read_tool] = result
        save(private)
        print(json.dumps({'tool': args.read_tool, 'responseShape': shape(result), 'rawValues': 'encrypted-only'}, ensure_ascii=False))
        return

    browser_session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log callback query/code/state.

        def cookie_ok(self):
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get('Cookie', ''))
                value = cookies.get('asset_lab_oauth_probe')
                return bool(value and hmac.compare_digest(value.value, browser_session))
            except Exception:
                return False

        def reply(self, message, status=200, location=None, set_cookie=False):
            raw = ('<!doctype html><html lang="zh"><meta charset="utf-8"><title>LibTV 官方授权开发验证</title>'
                   '<style>body{font:17px system-ui;max-width:720px;margin:64px auto;padding:24px;line-height:1.8;background:#f6f7f9}'
                   'button{padding:12px 24px;border:0;background:#234b3b;color:white;border-radius:9px;font:inherit}</style>'
                   '<h1>LibTV 官方授权 · 本机验证</h1>' + message + '</html>').encode()
            self.send_response(status)
            for k, v in {'Content-Type': 'text/html; charset=utf-8', 'Content-Length': str(len(raw)),
                         'Cache-Control': 'no-store', 'Referrer-Policy': 'same-origin' if urlsplit(self.path).path == '/' else 'no-referrer',
                         'X-Content-Type-Options': 'nosniff'}.items():
                self.send_header(k, v)
            if location:
                self.send_header('Location', location)
            if set_cookie:
                self.send_header('Set-Cookie', f'asset_lab_oauth_probe={browser_session}; HttpOnly; SameSite=Lax; Path=/')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/':
                verified = load().get('status') == 'identity_verified'
                notice = ('<p><strong>本机官方授权与账号身份读取已验证。</strong></p>'
                          '<p>已完成官方页面确认、回调、令牌兑换及两次一致的账号身份读取。授权仅为账号只读；'
                          '图片模型查询需要额外权限，未申请。公网客户版回调仍未获准。</p>') if verified else ''
                return self.reply(notice + '<p>只验证你自己的 LibTV 官方授权和只读工具目录，不提交图片或视频生成。</p>'
                    '<p>此页只在本机开放；公网客户版回调需另行获准。</p>'
                    f'<form method="post" action="/authorize"><input type="hidden" name="csrf" value="{csrf}">'
                    '<button>打开 LibTV 官方授权</button></form>', set_cookie=True)
            if path != '/api/v1/oauth/libtv/callback':
                return self.reply('<p>页面不存在。</p>', 404)
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            try:
                with lock:
                    private = load()
                    supplied = query.get('state', [])
                    if (not self.cookie_ok() or len(supplied) != 1 or not private.get('stateHash')
                            or not hmac.compare_digest(hashlib.sha256(supplied[0].encode()).hexdigest(), private['stateHash'])
                            or private.get('status') != 'pending' or private.get('expiresAt', 0) <= time.time()):
                        raise AuthError('AUTHORIZATION_STATE_INVALID')
                    private['status'] = 'exchanging'
                    save(private)
                if query.get('error'):
                    raise AuthError('AUTHORIZATION_DENIED')
                if len(query.get('code', [])) != 1 or not query['code'][0]:
                    raise AuthError('AUTHORIZATION_STATE_INVALID')
                if query.get('iss') not in (None, [ISSUER]):
                    raise AuthError('AUTHORIZATION_STATE_INVALID')
                tokens = oauth.exchange(private['metadata'], ClientRegistration(**private['client']),
                                        query['code'][0], private['verifier'], time.time())
                private.update(tokens=tokens, verifier=None, stateHash=None, status='identity_unverified')
                save(private)
                catalogue = MCPReadSession(oauth.http, tokens['access_token']).tools()
                # Tool schema is evidence; all user-specific return data remains encrypted.
                (data / 'tool-catalogue.json').write_text(json.dumps(catalogue, ensure_ascii=False, indent=2))
                (data / 'tool-catalogue.json').chmod(0o600)
                return self.reply('<p>官方授权已返回，后台已读取工具目录。</p><p><strong>身份字段尚未核验，未将账号标记为已连接。</strong></p>'
                                  '<p>开发者可继续做官方只读验证；没有提交生成任务。</p>')
            except AuthError as err:
                return self.reply('<p>' + err.message + '</p><p>未标记账号连接成功。</p>', err.status)
            except Exception:
                return self.reply('<p>本机验证未完成。请查看脱敏诊断后重新发起。</p>', 500)

        def do_POST(self):
            if self.path != '/authorize':
                return self.reply('<p>页面不存在。</p>', 404)
            if self.headers.get('Origin') != f'http://127.0.0.1:{args.port}' or not self.cookie_ok():
                return self.reply('<p>请从本机验证首页发起。</p>', 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise AuthError('VALIDATION_FAILED')
                values = parse_qs(self.rfile.read(length).decode())
                if values.get('csrf') != [csrf]:
                    raise AuthError('CSRF_FAILED')
                metadata = oauth.discover()
                with lock:
                    previous = load()
                    client = ClientRegistration(**previous['client']) if previous.get('client') else oauth.register(metadata)
                    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
                    private = {'client': client.secret_value(), 'metadata': metadata, 'verifier': verifier,
                               'stateHash': hashlib.sha256(state.encode()).hexdigest(),
                               'status': 'pending', 'expiresAt': time.time() + 600}
                    save(private)
                return self.reply('<p>正在打开官方授权页面。</p>', 303, oauth.authorization_url(metadata, client, state, verifier))
            except AuthError as err:
                return self.reply('<p>' + err.message + '</p>', err.status)

    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Developer-only official OAuth probe: http://127.0.0.1:{args.port}/', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
