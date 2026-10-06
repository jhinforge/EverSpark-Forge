"""Local Gate API for the Archon-only mode, with no execution-side imports."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from Archon.Steward.vast_instances import VastError
from Archon.Vault.windows_credentials import CredentialError
from Archon.Steward.DeploymentManager.base_image import select_base_image
from Archon.Steward.DeploymentManager.providers import onboarding
from Archon.Steward.NodeManager.transport.operator import handle as handle_nodes
from .forge_binding_routes import handle as handle_forge_bindings


_REMOTE_FORGE_ACTIONS = {
    "concept": frozenset({"chat", "models", "probe"}),
    "image": frozenset({"probe", "resources", "plugins", "default_negative", "submit", "poll", "history", "fetch"}),
    "audio": frozenset({"probe", "health", "synthesize", "fetch", "history"}),
}


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], machines=None, offers=None, deployments=None,
                 image_deployments=None, node_manager=None, forge_bindings=None, audio_deployments=None,
                 logger=None):
        self.logger = logger
        self.forge_bindings = forge_bindings
        self.node_manager = node_manager
        self.machines = machines
        self.offers = offers
        self.deployments = deployments
        self.image_deployments = image_deployments
        self.audio_deployments = audio_deployments
        super().__init__(address, ControlHandler)


class ControlHandler(BaseHTTPRequestHandler):
    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def log_message(self, format: str, *args) -> None:
        if self.server.logger is not None:
            self.server.logger.info("http.access", "HTTP request completed",
                                    client=self.address_string(), request=format % args)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if handle_forge_bindings(self, self.server.forge_bindings, "GET", path):
            return
        if handle_nodes(self, self.server.node_manager, "GET", path):
            return
        if path.startswith("/machines/"):
            if not self._local_request():
                return
            if self.server.machines is None:
                self._send(503, {"ok": False, "error": "Machine management is unavailable"})
                return
            try:
                if path == "/machines/vast/node-connection":
                    bridge = self.server.deployments.bridge if self.server.deployments else None
                    self._send(200, {"ok": True, **onboarding.status(bridge)})
                elif path == "/machines/vast/credential":
                    self._send(200, {"ok": True, "configured": self.server.machines.configured()})
                elif path == "/machines/vast/balance":
                    self._send(200, {"ok": True, **self.server.machines.balance()})
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
                            machine["node"] = {"status": "unconfigured"}
                            if self.server.deployments.bridge:
                                machine["node"] = self.server.deployments.bridge.status(machine["id"])
                                if machine.get("actual_status") == "stopped" and machine["node"]["status"] != "unconfigured":
                                    machine["node"].update(status="offline", stage="pod_stopped")
                                    if machine["node"].get("resources"):
                                        machine["node"]["resources"]["allocatable"] = None
                    if self.server.image_deployments:
                        for machine in result["instances"]:
                            self.server.image_deployments.reconcile_machine(machine)
                            machine["image_forge"] = self.server.image_deployments.status(machine["id"])
                            if machine.get("actual_status") == "stopped" and machine["image_forge"]["status"] == "ready":
                                machine["image_forge"] = {"status": "verification_required"}
                    if self.server.audio_deployments:
                        for machine in result["instances"]:
                            self.server.audio_deployments.reconcile_machine(machine)
                            machine["audio_forge"] = self.server.audio_deployments.status(machine["id"])
                    self._send(200, {"ok": True, **result})
                elif path == "/machines/vast/deployment-job":
                    from urllib.parse import parse_qs
                    job_id = parse_qs(parsed.query).get("id", [""])[0]
                    if not self.server.deployments:
                        self._send(503, {"ok": False, "error": "Deployment is unavailable"})
                    else:
                        self._send(200, {"ok": True, "job": self.server.deployments.job(job_id)})
                elif path == "/machines/vast/audio-deployment-job":
                    from urllib.parse import parse_qs
                    if not self.server.audio_deployments:
                        raise VastError("Audio deployment is unavailable", 503)
                    job_id = parse_qs(parsed.query).get("id", [""])[0]
                    self._send(200, {"ok": True, "job": self.server.audio_deployments.job(job_id)})
                elif path == "/machines/vast/image-deployment-job":
                    from urllib.parse import parse_qs
                    if not self.server.image_deployments:
                        raise VastError("Image deployment is unavailable", 503)
                    job_id = parse_qs(parsed.query).get("id", [""])[0]
                    self._send(200, {"ok": True, "job": self.server.image_deployments.job(job_id)})
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
        if handle_forge_bindings(self, self.server.forge_bindings, "POST", path):
            return
        if handle_nodes(self, self.server.node_manager, "POST", path):
            return
        if path == "/storage/reconfigure":
            if self._local_request():
                self._send(200, {"ok": True})
            return
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
                if not 0 < length <= 131072:
                    raise ValueError
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError
                if path == "/machines/vast/node-connection":
                    bridge = self.server.deployments.bridge if self.server.deployments else None
                    self._send(200, {"ok": True, **onboarding.configure(bridge, payload)})
                elif path == "/machines/vast/credential":
                    page = self.server.machines.save(payload.get("key"))
                    self._send(200, {"ok": True, "configured": True, **page})
                elif path == "/machines/vast/credential/remove":
                    self.server.machines.remove()
                    self._send(200, {"ok": True, "configured": False})
                elif path == "/machines/vast/destroy":
                    if set(payload) != {"instance_id"}:
                        raise VastError("Invalid destruction request", 400)
                    instance_id = payload["instance_id"]
                    self.server.machines.destroy(instance_id)
                    if self.server.deployments:
                        self.server.deployments.retire_instance(instance_id)
                    if self.server.image_deployments:
                        self.server.image_deployments.retire_instance(instance_id)
                    if self.server.audio_deployments:
                        self.server.audio_deployments.retire_instance(instance_id)
                    self._send(200, {"ok": True, "instance_id": instance_id})
                elif path == "/machines/vast/offers":
                    if self.server.offers is None:
                        self._send(503, {"ok": False, "error": "Offer search is unavailable"})
                    else:
                        self._send(200, {"ok": True, **self.server.offers.search(payload)})
                elif path == "/machines/vast/rent":
                    if not self.server.offers or not self.server.deployments or (set(payload) - {"offer_id", "require_agent"} or "offer_id" not in payload):
                        raise VastError("Invalid rental request", 400)
                    require_agent = payload.get("require_agent", False)
                    if not isinstance(require_agent, bool):
                        raise VastError("Invalid rental mode", 400)
                    bridge = self.server.deployments.bridge
                    if require_agent and not onboarding.status(bridge)["ready"]:
                        raise VastError("Configure automatic Node connection before renting", 409)
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
                        node_env = bridge.environment(token)
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
                elif path == "/machines/vast/forge-task":
                    if set(payload) != {"instance_id", "forge", "action", "message"}:
                        raise VastError("Invalid Forge task", 400)
                    if (not isinstance(payload["forge"], str) or
                        not isinstance(payload["action"], str) or
                        not isinstance(payload["message"], str)):
                        raise VastError("Invalid Forge task", 400)
                    if payload["action"] not in _REMOTE_FORGE_ACTIONS.get(payload["forge"], ()):
                        raise VastError("Unsupported Forge task", 400)
                    bridge = self.server.deployments.bridge if self.server.deployments else None
                    if not bridge:
                        raise VastError("Node bridge is unavailable", 503)
                    self._send(200, {"ok": True, "output": bridge.execute(
                        payload["instance_id"], payload["action"], payload["message"],
                        timeout=600 if payload["forge"] == "audio" else 240, forge=payload["forge"])})
                elif path in {"/machines/vast/deploy-audio", "/machines/vast/verify-audio"}:
                    if set(payload) != {"instance_id"} or not self.server.audio_deployments:
                        raise VastError("Invalid Audio Forge deployment request", 400)
                    action = "verify" if path.endswith("/verify-audio") else "deploy"
                    self._send(202, {"ok": True, "job": self.server.audio_deployments.start(payload["instance_id"], action)})
                elif path in {"/machines/vast/deploy-image", "/machines/vast/verify-image"}:
                    if set(payload) != {"instance_id"} or not self.server.image_deployments:
                        raise VastError("Invalid Image Forge deployment request", 400)
                    action = "verify" if path.endswith("/verify-image") else "deploy"
                    self._send(202, {"ok": True, "job": self.server.image_deployments.start(payload["instance_id"], action)})
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
