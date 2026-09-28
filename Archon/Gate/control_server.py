"""Local Gate API for the Archon-only mode, with no execution-side imports."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from Archon.Steward.vast_instances import VastError
from Archon.Vault.windows_credentials import CredentialError


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], machines=None):
        self.machines = machines
        super().__init__(address, ControlHandler)


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.startswith("/machines/"):
            if not self._local_request():
                return
            if self.server.machines is None:
                self._send(503, {"ok": False, "error": "Machine management is unavailable"})
                return
            try:
                if path == "/machines/vast/credential":
                    self._send(200, {"ok": True, "configured": self.server.machines.configured()})
                elif path == "/machines/vast/instances":
                    from urllib.parse import parse_qs
                    cursor = parse_qs(parsed.query).get("after_token", [""])[0]
                    self._send(200, {"ok": True, **self.server.machines.list(cursor)})
                else:
                    self._send(404, {"ok": False, "error": "Not found"})
            except VastError as exc:
                self._send(exc.status, {"ok": False, "error": str(exc)})
            except CredentialError as exc:
                self._send(503, {"ok": False, "error": str(exc)})
            return
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
        path = urlsplit(self.path).path
        if path.startswith("/machines/"):
            if not self._local_request():
                return
            if self.server.machines is None:
                self._send(503, {"ok": False, "error": "Machine management is unavailable"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._send(415, {"ok": False, "error": "JSON request required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError
                if path == "/machines/vast/credential":
                    page = self.server.machines.save(payload.get("key"))
                    self._send(200, {"ok": True, "configured": True, **page})
                elif path == "/machines/vast/credential/remove":
                    self.server.machines.remove()
                    self._send(200, {"ok": True, "configured": False})
                else:
                    self._send(404, {"ok": False, "error": "Not found"})
            except (ValueError, UnicodeError):
                self._send(400, {"ok": False, "error": "Invalid JSON request"})
            except VastError as exc:
                self._send(exc.status, {"ok": False, "error": str(exc)})
            except CredentialError as exc:
                self._send(503, {"ok": False, "error": str(exc)})
            return
        self._unavailable()

    def _local_request(self) -> bool:
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}",
                   f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin != f"http://{host}"):
            self._send(403, {"ok": False, "error": "Local origin required"})
            return False
        return True

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
