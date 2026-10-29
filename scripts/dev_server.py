"""Local preview: serves web/ and answers the API from a local data folder (AI coding off). Free, local only.

    python -I scripts/dev_server.py --root data/backfill/baseline --port 8734

The site calls http://127.0.0.1:<port>/api/... when opened on localhost (web/app.js), so nothing touches the cloud.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import api  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"


def handler(sink):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB), **kw)

        def _api(self, method):
            u = urlparse(self.path)
            body = None
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            status, out = api.handle(method, u.path[len("/api"):], dict(parse_qsl(u.query)), body, sink, ai_on=False)
            data = json.dumps(out, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/api/"):
                return self._api("GET")
            return super().do_GET()

        def do_POST(self):
            if self.path.startswith("/api/"):
                return self._api("POST")
            self.send_error(405)

        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

    return H


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--port", type=int, default=8734)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), handler(LocalSink(Path(a.root))))
    print(f"http://127.0.0.1:{a.port}/", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
