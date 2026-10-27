"""Local, synthetic account UI fixture. No provider or customer data is accessed."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path.startswith('/asset-lab/'):
            path = path[len('/asset-lab'):]
        if not path.startswith(('/tests/accounts-ui/', '/frontend/accounts/')) or '..' in path.split('/'):
            self.send_error(404)
            return
        resolved = (ROOT / path.lstrip('/')).resolve()
        if not resolved.is_relative_to(ROOT) or not resolved.is_file() or resolved.suffix not in {'.html', '.js', '.css'}:
            self.send_error(404)
            return
        self.path = path
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8896)
    args = parser.parse_args()
    if args.port in {8768, 8870}:
        parser.error('8768 and 8870 belong to other services')
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        print(f'Synthetic fixture: http://127.0.0.1:{args.port}/tests/accounts-ui/fixture.html', flush=True)
        server.serve_forever()
