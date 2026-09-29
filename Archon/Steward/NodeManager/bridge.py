"""Private, pull-based task channel for short-lived Forge nodes."""

from __future__ import annotations

import hmac
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from Archon.Steward.NodeManager.registry import NodeRegistry
from Archon.Steward.vast_instances import VastError


class NodeBridge:
    def __init__(self, host: str, port: int = 8766, *, state_path: Path | None = None,
                 credential_factory=None):
        if (state_path is None) != (credential_factory is None):
            raise ValueError("Node registry requires both a path and credential storage")
        self.registry = (NodeRegistry(state_path, credential_factory)
                         if state_path is not None else None)
        restored = self.registry.load() if self.registry else []
        self.server = ThreadingHTTPServer((host, port), _NodeHandler)
        self.server.daemon_threads = True
        self.server.bridge = self
        self.lock = threading.Condition()
        self.url = f"http://{host}:{self.server.server_port}"
        self.auth_key = None
        self.agent_requested = False
        self.claimed = False
        self.pending = {}  # bootstrap token -> instance id, assigned after rental
        self.nodes = {}  # instance id -> session and task queue
        self.thread = None
        for instance_id, phase, secret, bootstrap in restored:
            self.nodes[instance_id] = {
                "status": "joining" if phase == "joining" else "offline",
                "seen": 0.0, "session": secret if phase == "online" else None,
                "tasks": deque(), "results": {}, "joined_at": time.monotonic(),
                "bootstrap": bootstrap, "runtime_id": None,
            }
            # A restarted Archon can also complete a registration whose first
            # response was lost as the previous process exited.
            self.pending[bootstrap] = instance_id
        # Existing nodes do not consume a new, distinct auth key supplied on restart.

    def configure_auth_key(self, auth_key: str) -> None:
        self.agent_requested = bool(auth_key)
        used_hash = self.registry.used_key_hash if self.registry else ""
        self.auth_key = (auth_key if auth_key and hashlib.sha256(
            auth_key.encode("utf-8")).hexdigest() != used_hash else None)

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True,
                                       name="archon-node-bridge")
        self.thread.start()

    def close(self):
        if self.thread is not None:
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()

    def reserve(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            if not self.auth_key or self.claimed:
                raise VastError("A one-off node key is already in use", 409)
            self.claimed = True
            self.pending[token] = None
        return token

    def bind(self, token: str, instance_id: int):
        with self.lock:
            if token not in self.pending:
                raise VastError("Unknown node reservation", 400)
            if self.registry:
                self.registry.save(instance_id, "joining", token,
                                   used_key_hash=hashlib.sha256(self.auth_key.encode()).hexdigest())
            self.pending[token] = instance_id
            self.nodes[instance_id] = {"status": "joining", "seen": 0.0,
                                       "session": None, "tasks": deque(), "results": {},
                                       "joined_at": time.monotonic(), "bootstrap": token,
                                       "runtime_id": None}
            self.lock.notify_all()
            self.auth_key = None

    def discard(self, token: str):
        with self.lock:
            if token in self.pending:
                self.pending.pop(token)
                self.claimed = False

    def register(self, token: str, instance_id: int, runtime_id: str | None = None) -> dict:
        with self.lock:
            if not isinstance(instance_id, int) or isinstance(instance_id, bool):
                raise VastError("Invalid node identity", 400)
            if runtime_id is not None and (not isinstance(runtime_id, str) or
                len(runtime_id) != 32 or any(char not in "0123456789abcdef" for char in runtime_id)):
                raise VastError("Invalid Agent runtime identity", 400)
            expected = self.pending.get(token)
            node = self.nodes.get(instance_id)
            restarted = (node is not None and runtime_id is not None and
                         runtime_id != node["runtime_id"] and node["session"] is not None and
                         isinstance(token, str) and hmac.compare_digest(token, node["bootstrap"]))
            if expected != instance_id and not restarted:
                raise VastError("Node registration is not ready or authorized", 403)
            # A bootstrap credential can register only once. The session is
            # kept by the agent for subsequent polls and result submissions.
            session = secrets.token_urlsafe(32)
            if self.registry:
                self.registry.save(instance_id, "online", session)
            self.pending.pop(token, None)
            node["session"] = session
            node["runtime_id"] = runtime_id
            node["seen"] = time.monotonic()
            node["status"] = "online"
            self.lock.notify_all()
            return {"session": session}

    def _authenticated(self, instance_id: int, session: str) -> dict:
        node = self.nodes.get(instance_id)
        if not node or not isinstance(session, str) or not node["session"] or not hmac.compare_digest(
            session, node["session"]
        ):
            raise VastError("Invalid node session", 403)
        node["seen"] = time.monotonic()
        node["status"] = "online"
        return node

    def next_task(self, instance_id: int, session: str) -> dict:
        with self.lock:
            node = self._authenticated(instance_id, session)
            if not node["tasks"]:
                self.lock.wait(12)
                node = self._authenticated(instance_id, session)
            return node["tasks"].popleft() if node["tasks"] else {}

    def finish(self, instance_id: int, session: str, task_id: str, result: dict):
        with self.lock:
            node = self._authenticated(instance_id, session)
            if not isinstance(result, dict):
                raise VastError("Invalid node task result", 400)
            if task_id not in node["results"] or node["results"][task_id] is not None:
                raise VastError("Unknown or completed node task", 409)
            if result.get("status") not in {"completed", "failed"}:
                raise VastError("Invalid node task result", 400)
            node["results"][task_id] = {"status": result["status"],
                                         "output": str(result.get("output", ""))[:4000],
                                         "exit_code": result.get("exit_code")}
            self.lock.notify_all()

    def status(self, instance_id: int) -> dict:
        with self.lock:
            node = self.nodes.get(instance_id)
            if not node:
                return {"status": "unconfigured"}
            if node["status"] == "online" and time.monotonic() - node["seen"] > 45:
                return {"status": "offline", "stage": "agent_disconnected"}
            if node["status"] == "joining":
                return {"status": "joining", "stage": "awaiting_agent",
                        "elapsed_seconds": int(time.monotonic() - node["joined_at"])}
            return {"status": node["status"]}

    def configured(self, instance_id: int) -> bool:
        with self.lock:
            return instance_id in self.nodes

    def runtime_id(self, instance_id: int) -> str | None:
        with self.lock:
            node = self.nodes.get(instance_id)
            return node["runtime_id"] if node else None

    def instance_ids(self) -> set[int]:
        with self.lock:
            return set(self.nodes)

    def prune(self, live_ids: set[int]) -> set[int]:
        """Revoke nodes confirmed absent from a complete provider inventory."""
        with self.lock:
            removed = set(self.nodes) - live_ids
            if not removed:
                return set()
            if self.registry:
                self.registry.remove(removed)
            for instance_id in removed:
                node = self.nodes.pop(instance_id)
                node["status"] = "removed"
            self.pending = {token: instance_id for token, instance_id in self.pending.items()
                            if instance_id not in removed}
            self.lock.notify_all()
            return removed

    def execute(self, instance_id: int, action: str, message: str = "", timeout: int = 240,
                task_id: str | None = None) -> str:
        deadline = time.monotonic() + timeout
        join_deadline = min(deadline, time.monotonic() + 120)
        with self.lock:
            node = self.nodes.get(instance_id)
            if not node:
                raise VastError("Node was not provisioned for agent execution", 409)
            while node["status"] != "online":
                if node["status"] == "removed":
                    raise VastError("Node instance was destroyed", 404)
                remaining = join_deadline - time.monotonic()
                if remaining <= 0:
                    raise NodeRegistrationError(instance_id)
                self.lock.wait(min(remaining, 5))
            task_id = task_id or secrets.token_hex(16)
            if len(task_id) != 32 or any(char not in "0123456789abcdef" for char in task_id):
                raise VastError("Invalid task identity", 400)
            if task_id in node["results"]:
                raise VastError("Task identity is already active", 409)
            node["results"][task_id] = None
            node["tasks"].append({"id": task_id, "action": action, "message": message})
            self.lock.notify_all()
            while node["results"][task_id] is None:
                if node["status"] == "removed":
                    raise VastError("Node instance was destroyed", 404)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    node["results"].pop(task_id, None)
                    node["tasks"] = deque(task for task in node["tasks"] if task["id"] != task_id)
                    raise VastError("Node Agent task timed out")
                self.lock.wait(min(remaining, 5))
            result = node["results"].pop(task_id)
            if result["status"] != "completed":
                raise NodeTaskError(result["output"], result["exit_code"])
            return result["output"]


class NodeTaskError(VastError):
    def __init__(self, detail: str, exit_code: int | None):
        super().__init__("Node Agent execution failed")
        self.stage = "agent_execution"
        self.detail = detail or "Node Agent returned no output"
        self.exit_code = exit_code


class NodeRegistrationError(VastError):
    def __init__(self, instance_id: int):
        super().__init__("Node Agent did not register before timeout")
        self.stage = "agent_registration"
        self.detail = (f"Pod {instance_id}: inspect /workspace/everspark-node.log and "
                       "/workspace/everspark-tailscale.log for startup and Tailscale errors")


class _NodeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Content-Type") != "application/json" or not 0 < length <= 8192:
                raise VastError("Invalid node request", 400)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise VastError("Invalid node request", 400)
            bridge = self.server.bridge
            instance_id = body.get("instance_id")
            if self.path == "/node/register":
                result = bridge.register(body.get("bootstrap", ""), instance_id,
                                         body.get("runtime_id"))
            elif self.path == "/node/next":
                result = bridge.next_task(instance_id, body.get("session", ""))
            elif self.path == "/node/result":
                bridge.finish(instance_id, body.get("session", ""), body.get("task_id", ""),
                              body.get("result", {}))
                result = {}
            else:
                raise VastError("Not found", 404)
            self._send(200, result)
        except (ValueError, TypeError, json.JSONDecodeError):
            self._send(400, {"error": "Invalid node request"})
        except VastError as exc:
            self._send(exc.status, {"error": str(exc)})

    def _send(self, status: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass  # Never print registration credentials in HTTP logs.


def _tailscale_cli() -> str:
    configured = os.environ.get("EVERSPARK_TAILSCALE_EXE")
    if configured:
        if Path(configured).is_file():
            return configured
        raise RuntimeError("EVERSPARK_TAILSCALE_EXE does not point to tailscale.exe")

    executable = shutil.which("tailscale")
    if executable:
        return executable
    # The Windows installer does not always add its CLI to PATH.
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            candidate = Path(root) / "Tailscale" / "tailscale.exe"
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("Tailscale CLI not found. Install Tailscale or set "
                       "EVERSPARK_TAILSCALE_EXE to the full path of tailscale.exe")


def tailscale_ip(run=subprocess.run) -> str:
    try:
        result = run([_tailscale_cli(), "ip", "-4"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError as exc:
        raise RuntimeError("Tailscale CLI executable is missing; check "
                           "EVERSPARK_TAILSCALE_EXE or reinstall Tailscale") from exc
    address = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    try:
        valid = ipaddress.ip_address(address) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        valid = False
    if result.returncode or not valid:
        raise RuntimeError("Connect this Windows host to Tailscale before starting Archon")
    return address
