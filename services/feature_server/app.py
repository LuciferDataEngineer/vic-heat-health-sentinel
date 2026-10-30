"""Tiny feature server. The image bakes in the latest area features."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_PATH = Path("/app/area_features.json")
PAYLOAD = json.loads(DATA_PATH.read_text())
AREAS = {row["lga_code"]: row for row in PAYLOAD["areas"]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        path = self.path.split("?", 1)[0]
        if path in {"/health", "/healthz"}:
            self._send(200, {"status": "ok", "areas": len(AREAS)})
            return
        if path == "/features":
            self._send(200, PAYLOAD)
            return
        if path.startswith("/features/"):
            code = path.rstrip("/").split("/")[-1]
            row = AREAS.get(code)
            if row is None:
                self._send(404, {"error": "unknown area"})
            else:
                self._send(200, row)
            return
        self._send(404, {"error": "not found"})

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
