"""Private, pull-based task channel for short-lived Forge nodes."""

from __future__ import annotations

import hmac
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

from Archon.Steward.vast_instances import VastError


class NodeBridge:
    def __init__(self, host: str, port: int = 8766):
        self.server = ThreadingHTTPServer((host, port), _NodeHandler)
        self.server.daemon_threads = True
        self.server.bridge = self
        self.lock = threading.Condition()
        self.url = f"http://{host}:{self.server.server_port}"
        self.auth_key = None
        self.claimed = False
        self.pending = {}  # bootstrap token -> instance id, assigned after rental
        self.nodes = {}  # instance id -> session and task queue
        self.thread = None

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
            self.pending[token] = instance_id
            self.nodes[instance_id] = {"status": "joining", "seen": 0.0,
                                       "session": None, "tasks": deque(), "results": {}}
            self.lock.notify_all()
            self.auth_key = None

    def discard(self, token: str):
        with self.lock:
            if token in self.pending:
                self.pending.pop(token)
                self.claimed = False

    def register(self, token: str, instance_id: int) -> dict:
        with self.lock:
            if not isinstance(instance_id, int) or isinstance(instance_id, bool):
                raise VastError("Invalid node identity", 400)
            expected = self.pending.get(token)
            if expected is None or expected != instance_id:
                raise VastError("Node registration is not ready or authorized", 403)
            node = self.nodes[instance_id]
            # A bootstrap credential can register only once. The session is
            # kept by the agent for subsequent polls and result submissions.
            self.pending.pop(token)
            node["session"] = secrets.token_urlsafe(32)
            node["seen"] = time.monotonic()
            node["status"] = "online"
            self.lock.notify_all()
            return {"session": node["session"]}

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
                return {"status": "offline"}
            return {"status": node["status"]}

    def configured(self, instance_id: int) -> bool:
        with self.lock:
            return instance_id in self.nodes

    def execute(self, instance_id: int, action: str, message: str = "", timeout: int = 240) -> str:
        deadline = time.monotonic() + timeout
        join_deadline = min(deadline, time.monotonic() + 120)
        with self.lock:
            node = self.nodes.get(instance_id)
            if not node:
                raise VastError("Node was not provisioned for agent execution", 409)
            while node["status"] != "online":
                remaining = join_deadline - time.monotonic()
                if remaining <= 0:
                    raise NodeRegistrationError()
                self.lock.wait(min(remaining, 5))
            task_id = secrets.token_hex(16)
            node["results"][task_id] = None
            node["tasks"].append({"id": task_id, "action": action, "message": message})
            self.lock.notify_all()
            while node["results"][task_id] is None:
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
    def __init__(self):
        super().__init__("Node Agent did not register before timeout")
        self.stage = "agent_registration"


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
                result = bridge.register(body.get("bootstrap", ""), instance_id)
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
