"""Existing pull/result queue. Forge is only an opaque task execution label."""
import secrets
import time
from collections import deque
from .identity import validate_id
from .errors import NodeError, NodeTaskError, NodeRegistrationError
from .transport.auth import authenticate


class TaskChannel:
    def __init__(self, manager):
        self.manager, self.queues = manager, {}

    def ensure(self, node_id):
        self.queues.setdefault(node_id, {"tasks": deque(), "results": {}})

    def _authenticated(self, body, pulling=False):
        record, _ = authenticate(self.manager, body)
        self.manager.lifecycle.expire()
        if pulling and self.manager.registry.nodes[record["node_id"]]["status"] != "online":
            raise NodeError("Node heartbeat required before task pull", 409)
        self.ensure(record["node_id"])
        return self.queues[record["node_id"]]

    def next_task(self, body: dict) -> dict:
        with self.manager.lock:
            node = self._authenticated(body, pulling=True)
            if not node["tasks"]:
                self.manager.lock.wait(12)
                node = self._authenticated(body, pulling=True)
            return node["tasks"].popleft() if node["tasks"] else {}

    def finish(self, body: dict):
        task_id, result = body.get("task_id"), body.get("result")
        with self.manager.lock:
            node = self._authenticated(body)
            if not isinstance(result, dict):
                raise NodeError("Invalid node task result", 400)
            if not isinstance(task_id, str) or task_id not in node["results"] or node["results"][task_id] is not None:
                raise NodeError("Unknown or completed node task", 409)
            if result.get("status") not in {"completed", "failed"}:
                raise NodeError("Invalid node task result", 400)
            if len(str(result.get("output", "")).encode("utf-8")) > 60000:
                raise NodeError("Node task result is too large", 400)
            node["results"][task_id] = {"status": result["status"],
                                         "output": str(result.get("output", "")),
                                         "exit_code": result.get("exit_code")}
            self.manager.lock.notify_all()


    def execute(self, node_id: str, action: str, message: str = "", timeout: int = 240,
                task_id: str | None = None, forge: str = "concept") -> str:
        validate_id(node_id)
        if not isinstance(forge, str) or not 1 <= len(forge) <= 64 or not isinstance(action, str) or not action:
            raise NodeError("Invalid task routing label", 400)
        if not isinstance(message, str) or len(message.encode()) > 60000:
            raise NodeError("Invalid task message", 400)
        deadline = time.monotonic() + timeout
        join_deadline = min(deadline, time.monotonic() + 120)
        with self.manager.lock:
            record = self.manager.registry.nodes.get(node_id)
            if not record:
                raise NodeError("Unknown Node", 404)
            self.ensure(node_id)
            node = self.queues.get(node_id)
            if not node:
                raise NodeError("Node was not provisioned for agent execution", 409)
            self.manager.lifecycle.expire()
            record = self.manager.registry.nodes[node_id]
            while record["status"] != "online":
                if record["status"] == "removed":
                    raise NodeError("Node instance was destroyed", 404)
                remaining = join_deadline - time.monotonic()
                if remaining <= 0:
                    raise NodeRegistrationError(node_id)
                self.manager.lock.wait(min(remaining, 5))
                self.manager.lifecycle.expire()
                record = self.manager.registry.nodes[node_id]
            task_id = task_id or secrets.token_hex(16)
            if not isinstance(task_id, str) or len(task_id) != 32 or any(char not in "0123456789abcdef" for char in task_id):
                raise NodeError("Invalid task identity", 400)
            if task_id in node["results"]:
                raise NodeError("Task identity is already active", 409)
            node["results"][task_id] = None
            node["tasks"].append({"id": task_id, "forge": forge,
                                  "action": action, "message": message})
            self.manager.lock.notify_all()
            try:
                while node["results"][task_id] is None:
                    record = self.manager.registry.nodes[node_id]
                    if record["status"] == "removed":
                        raise NodeError("Node instance was destroyed", 404)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        node["results"].pop(task_id, None)
                        node["tasks"] = deque(task for task in node["tasks"] if task["id"] != task_id)
                        raise NodeError("Node Agent task timed out", 504)
                    self.manager.lock.wait(min(remaining, 5))
            except BaseException:
                node["results"].pop(task_id, None)
                node["tasks"] = deque(task for task in node["tasks"] if task["id"] != task_id)
                raise
            result = node["results"].pop(task_id)
            if result["status"] != "completed":
                raise NodeTaskError(result["output"], result["exit_code"])
            return result["output"]
