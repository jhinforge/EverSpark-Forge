"""Control-only Orchestrator endpoint, with no execution-side imports."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int]):
        super().__init__(address, ControlHandler)


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            self._send(200, {"ok": True, "mode": "archon-only", "execution_available": False})
        elif path == "/image/health":
            self._unavailable()
        elif path == "/resources":
            self._send(200, {"ok": True, "workflows": [], "checkpoints": [],
                             "vaes": [], "loras": [], "llms": [], "defaults": {},
                             "concept_providers": [], "concept_models": {}})
        elif path == "/image/plugins":
            self._send(200, {"ok": True, "default": "", "plugins": []})
        elif path == "/concept/connections":
            self._send(200, {"ok": True, "default": "", "connections": []})
        elif path == "/subjects":
            self._send(200, {"ok": True, "subjects": []})
        elif path == "/subjects/current":
            self._send(200, {"ok": True, "document": None})
        elif path == "/memory/history":
            self._send(200, {"ok": True, "messages": []})
        elif path == "/image/history":
            self._send(200, {"ok": True, "images": []})
        elif path == "/storage/resources":
            self._send(200, {"ok": True, "enabled": False, "backend": "local",
                             "image": {}, "concept": {"models": []}})
        elif path == "/storage/scan":
            self._send(200, {"ok": True, "status": "completed", "result": {
                "enabled": False, "image": {}, "concept": {"models": []}}})
        elif path in {"/storage/jobs", "/backup/jobs", "/downloads/jobs"}:
            self._send(200, {"ok": True, "job": None})
        elif path == "/backup/resources":
            self._send(200, {"ok": True, "enabled": False})
        elif path == "/backup/restore-points":
            self._send(200, {"ok": True, "points": []})
        elif path in {"/tasks/jobs", "/image/plugins/jobs",
                      "/concept/connections/test/jobs"}:
            self._unavailable()
        else:
            self._send(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        self._unavailable()

    def _unavailable(self) -> None:
        self._send(503, {"ok": False, "error": "No Legate is connected in Archon-only mode"})

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
