"""Persist manual Forge endpoint choices; no scheduling or Forge instances."""
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from Archon.Steward.NodeManager.errors import NodeError
from Archon.Steward.NodeManager.identity import validate_id
from .remote_runtime import create_runtime

ROLES = frozenset({"concept", "image", "audio"})


class ForgeBindings:
    def __init__(self, nodes, path, control_url, *, factory=create_runtime):
        self.nodes, self.path, self.control_url, self.factory = nodes, Path(path), control_url, factory
        self.lock = threading.RLock()
        self.runtime, self.error = None, ""
        self.active_requests = 0
        try:
            bindings = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            bindings = {}
        if not isinstance(bindings, dict) or set(bindings) - ROLES:
            raise ValueError("Invalid Forge Node selections")
        for node_id in bindings.values():
            validate_id(node_id)
        self.bindings = bindings

    @property
    def url(self):
        with self.lock:
            has_api = bool(self.runtime and getattr(self.runtime, "has_api", lambda: False)())
            valid = all(self.nodes.configured(node_id) for role, node_id in self.bindings.items()
                        if role != "audio" and (role != "concept" or not has_api))
            return self.runtime.url if self.runtime and valid else ""

    def status(self):
        with self.lock:
            states = {role: self.nodes.status(node_id).get("status", "offline")
                      for role, node_id in self.bindings.items()}
            has_api = bool(self.runtime and getattr(self.runtime, "has_api", lambda: False)())
            return {"bindings": dict(self.bindings), "nodes": states, "connected": bool(self.url),
                    "ready": bool(self.url) and states.get("image") == "online"
                        and (states.get("concept") == "online" or has_api),
                    "error": self.error}

    def restore(self):
        with self.lock:
            available = {role: node for role, node in self.bindings.items() if self.nodes.configured(node)}
            if available:
                try:
                    self.runtime = self.factory(available, self.control_url)
                except Exception as exc:
                    self.error = str(exc)[-500:]

    def select(self, body):
        if not isinstance(body, dict) or set(body) != {"forge", "node_id"} or body.get("forge") not in ROLES:
            raise NodeError("Invalid Forge Node selection", 400)
        node_id = validate_id(body["node_id"])
        if self.nodes.status(node_id).get("status") != "online":
            raise NodeError("Select an online Node", 409)
        with self.lock:
            candidate = {**self.bindings, body["forge"]: node_id}
            # A removed endpoint must not prevent replacing the other role first.
            # Keep valid (including temporarily offline) choices, but require an
            # explicit selection for every removed role before composing a runtime.
            candidate = {role: selected for role, selected in candidate.items()
                         if role == body["forge"] or self.nodes.configured(selected)}
            if candidate == self.bindings and self.runtime:
                return self.status()
            if self.active_requests or (self.runtime and self.runtime.busy()):
                raise NodeError("Wait for the current task before changing Forge Nodes", 409)
            replacement = None
            try:
                if candidate:
                    if not all(self.nodes.configured(n) for n in candidate.values()):
                        raise NodeError("Selected Forge Node was removed; select its replacement", 409)
                    replacement = self.factory(candidate, self.control_url)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name(self.path.name + ".tmp")
                temporary.write_text(json.dumps(candidate), encoding="utf-8")
                temporary.replace(self.path)
            except Exception:
                if replacement:
                    replacement.close()
                raise
            previous = self.runtime
            self.bindings, self.runtime, self.error = candidate, replacement, ""
            if previous:
                previous.close()
            return self.status()

    @contextmanager
    def request(self):
        # A Portal request pins its runtime through response/file transfer.
        # This also closes the race between checking busy() and submitting.
        with self.lock:
            url = self.url
            self.active_requests += 1
        try:
            yield url
        finally:
            with self.lock:
                self.active_requests -= 1

    def close(self):
        with self.lock:
            if self.runtime:
                self.runtime.close()
                self.runtime = None
