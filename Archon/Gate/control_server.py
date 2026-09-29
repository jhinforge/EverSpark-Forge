"""Local Gate API for the Archon-only mode, with no execution-side imports."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from Archon.Steward.vast_instances import VastError
from Archon.Vault.windows_credentials import CredentialError
from Legate.Envoy.base_image import select_base_image


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], machines=None, offers=None, deployments=None):
        self.machines = machines
        self.offers = offers
        self.deployments = deployments
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
                    result = self.server.machines.list(cursor)
                    if self.server.deployments:
                        if not cursor:
                            self.server.deployments.reconcile_instances(result)
                        for machine in result["instances"]:
                            machine["forge"] = self.server.deployments.status(machine["id"])
                            if machine.get("actual_status") == "stopped" and machine["forge"]["status"] == "ready":
                                machine["forge"] = {"status": "verification_required"}
                            if self.server.deployments.bridge:
                                machine["node"] = self.server.deployments.bridge.status(machine["id"])
                                if machine.get("actual_status") == "stopped" and machine["node"]["status"] != "unconfigured":
                                    machine["node"] = {"status": "offline", "stage": "pod_stopped"}
                    self._send(200, {"ok": True, **result})
                elif path == "/machines/vast/deployment-job":
                    from urllib.parse import parse_qs
                    job_id = parse_qs(parsed.query).get("id", [""])[0]
                    if not self.server.deployments:
                        self._send(503, {"ok": False, "error": "Deployment is unavailable"})
                    else:
                        self._send(200, {"ok": True, "job": self.server.deployments.job(job_id)})
                elif path == "/machines/vast/gpu-names":
                    if self.server.offers is None:
                        self._send(503, {"ok": False, "error": "Offer search is unavailable"})
                    else:
                        self._send(200, {"ok": True, **self.server.offers.gpu_names()})
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
                elif path == "/machines/vast/offers":
                    if self.server.offers is None:
                        self._send(503, {"ok": False, "error": "Offer search is unavailable"})
                    else:
                        self._send(200, {"ok": True, **self.server.offers.search(payload)})
                elif path == "/machines/vast/rent":
                    if not self.server.offers or not self.server.deployments or set(payload) != {"offer_id"}:
                        raise VastError("Invalid rental request", 400)
                    offer = self.server.offers.quote(payload["offer_id"])
                    try:
                        image = select_base_image(offer)
                    except ValueError as exc:
                        raise VastError(str(exc), 400) from None
                    bridge = self.server.deployments.bridge
                    node_env = None
                    token = None
                    if bridge and bridge.agent_requested and not bridge.auth_key:
                        raise VastError("Tailscale auth key already used; set a new key and restart Archon", 409)
                    if bridge and bridge.auth_key:
                        token = bridge.reserve()
                        node_env = {"EVERSPARK_TAILSCALE_AUTH_KEY": bridge.auth_key,
                                    "EVERSPARK_NODE_BOOTSTRAP": token,
                                    "EVERSPARK_NODE_BRIDGE_URL": bridge.url}
                    try:
                        rental = self.server.machines.create(offer, image, node_env=node_env)
                        if token:
                            bridge.bind(token, rental["instance_id"])
                    except Exception:
                        if token:
                            bridge.discard(token)
                        raise
                    self._send(200, {"ok": True, **rental,
                                     "node_mode": "agent" if token else "ssh"})
                elif path == "/machines/vast/startup-diagnostics":
                    if set(payload) != {"instance_id"}:
                        raise VastError("Invalid startup diagnostics request", 400)
                    self._send(200, {"ok": True, **self.server.machines.startup_diagnostics(payload["instance_id"])})
                elif path in {"/machines/vast/deploy", "/machines/vast/verify", "/machines/vast/update-source",
                              "/machines/vast/discuss"}:
                    if not self.server.deployments or set(payload) - {"instance_id", "message"}:
                        raise VastError("Invalid deployment request", 400)
                    action = {"/machines/vast/deploy": "deploy",
                              "/machines/vast/verify": "verify",
                              "/machines/vast/update-source": "update",
                              "/machines/vast/discuss": "discuss"}[path]
                    self._send(202, {"ok": True, "job": self.server.deployments.start(
                        payload.get("instance_id"), action, payload.get("message", ""))})
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
