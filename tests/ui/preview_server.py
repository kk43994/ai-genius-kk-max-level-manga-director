"""Local-only visual fixture: no app backend, credentials, storage or provider calls.

python3 tests/ui/preview_server.py --port 8875
Preview the same page at / and /asset-lab/ with ?state=empty|connected|expired.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
FIXTURES = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = unquote(urlsplit(self.path).path)
        if route == "/asset-lab":
            self.send_response(308)
            self.send_header("Location", "/asset-lab/")
            self.end_headers()
            return
        if route.startswith("/asset-lab/"):
            route = route[len("/asset-lab"):]
        if route in ("/", "/preview.html", "/asset-lab.html"):
            html = (FRONTEND / "asset-lab.html").read_text()
            html = html.replace('<script type="module" src="shell/bootstrap.js"></script>', '')
            html = html.replace('<script type="module" src="asset-lab.js"></script>', '<script type="module" src="__ui__/preview.js"></script>')
            html = html.replace('</head>', '<link rel="stylesheet" href="__ui__/preview.css"></head>')
            return self.send(200, html.encode(), "text/html; charset=utf-8")
        directory = FIXTURES if route.startswith("/__ui__/") else FRONTEND
        relative = route[len("/__ui__/"):] if directory == FIXTURES else route.lstrip("/")
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or path.suffix not in {".js", ".css", ".svg"}:
            return self.send(404, b"Not found", "text/plain")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send(200, path.read_bytes(), mime + "; charset=utf-8")

    def do_POST(self):
        self.send(405, b"Visual fixture is read-only", "text/plain")

    do_PUT = do_PATCH = do_DELETE = do_POST

    def send(self, code, data, mime):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8875)
    args = parser.parse_args()
    if args.port in (8768, 8870):
        parser.error("Port is reserved for the original workbench or shared baseline")
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Synthetic shell preview: http://127.0.0.1:{args.port}/", flush=True)
        server.serve_forever()
