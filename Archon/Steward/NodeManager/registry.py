"""Atomic v2 Node index; no provider inventory or provider credentials."""
import copy
import json
import math
import os
from pathlib import Path
from .identity import validate_id
from .errors import NodeError
from .inventory import inventory
from .transport.credentials import FileCredential, MemoryCredential

STATES = {"joining", "online", "offline", "unhealthy", "removed"}


class NodeRegistry:
    def __init__(self, path=None, credential_factory=None):
        self.path = Path(path) if path else None
        self.credential_factory = credential_factory
        self._secrets = {}
        try:
            raw = json.loads(self.path.read_text()) if self.path else None
        except FileNotFoundError:
            raw = None
        if raw is None:
            raw = {"version": 2, "nodes": {}, "joins": {}}
        if not isinstance(raw, dict) or raw.get("version") != 2 or not isinstance(raw.get("nodes"), dict) or not isinstance(raw.get("joins"), dict):
            raise RuntimeError("Invalid Node registry; legacy registries need deployment-side migration")
        nodes, joins = raw["nodes"], raw["joins"]
        try:
            for node_id, node in nodes.items():
                validate_id(node_id)
                if not isinstance(node, dict) or node.get("node_id") != node_id or node.get("status") not in STATES:
                    raise RuntimeError("Invalid Node record")
                validate_id(node.get("enrollment_id"), "enrollment_id")
                inventory(node)
                if node.get("last_seen") is not None and not isinstance(node["last_seen"], str):
                    raise RuntimeError("Invalid Node timestamp")
                if not self.credential(node_id).get() and node["status"] != "removed":
                    raise RuntimeError("Saved Node credential missing")
                if node["status"] != "removed":
                    node["status"] = "offline"
                else:
                    try:
                        self.credential(node_id).delete()
                    except (RuntimeError, OSError):
                        pass  # Durable tombstone denies access; cleanup retries next startup.
            for key, grant in joins.items():
                if (not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key)
                        or not isinstance(grant, dict) or set(grant) != {"expires_at", "enrollment_id", "node_id"}
                        or isinstance(grant["expires_at"], bool) or not isinstance(grant["expires_at"], (int, float)) or not math.isfinite(grant["expires_at"])):
                    raise RuntimeError("Invalid join grant")
                if grant["node_id"] is not None:
                    validate_id(grant["node_id"])
                if grant["enrollment_id"] is not None:
                    validate_id(grant["enrollment_id"], "enrollment_id")
                    if grant["node_id"] not in nodes:
                        raise RuntimeError("Claimed join references a missing Node")
        except (NodeError, TypeError, KeyError) as exc:
            raise RuntimeError("Invalid Node registry") from exc
        self.nodes, self.joins = {}, {}
        self.publish(nodes, joins)

    def credential(self, node_id):
        if self.credential_factory:
            return self.credential_factory(f"EverSpark Forge/Node {node_id}/credential")
        if self.path:
            return FileCredential(self.path.parent/(self.path.stem+"_credentials")/node_id)
        return MemoryCredential(self._secrets, node_id)

    def publish(self, nodes, joins):
        # Candidates are detached from live state. Failed publication consumes nothing.
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name+".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump({"version": 2, "nodes": nodes, "joins": joins}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        self.nodes, self.joins = nodes, joins

    def candidates(self):
        return copy.deepcopy(self.nodes), copy.deepcopy(self.joins)
