"""Persist node identities without writing registration secrets to JSON."""

from __future__ import annotations

import json
from pathlib import Path


class NodeRegistry:
    def __init__(self, path: Path, credential_factory):
        self.path = Path(path)
        self.credential_factory = credential_factory
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {"version": 1, "nodes": {}}
        except (OSError, ValueError) as exc:
            raise RuntimeError("Cannot read saved Node Agent identities") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("nodes"), dict):
            raise RuntimeError("Saved Node Agent identities have an invalid format")
        self.nodes = raw["nodes"]

    def load(self) -> list[tuple[int, str, str, str]]:
        restored = []
        for key, phase in self.nodes.items():
            if not isinstance(key, str) or not key.isdecimal() or int(key) < 1 or phase not in {
                "joining", "online"
            }:
                raise RuntimeError("Saved Node Agent identities have an invalid format")
            secret = self._credential(int(key), phase).get()
            if not secret:
                raise RuntimeError("A saved Node Agent credential is missing")
            bootstrap = (secret if phase == "joining"
                         else self._credential(int(key), "joining").get())
            if not bootstrap:
                raise RuntimeError("A saved Node Agent credential is missing")
            restored.append((int(key), phase, secret, bootstrap))
        return restored

    def save(self, instance_id: int, phase: str, secret: str) -> None:
        # Store the credential first: a crash before the index update leaves only
        # an unused credential, never an index pointing at a missing credential.
        self._credential(instance_id, phase).set(secret)
        nodes = {**self.nodes, str(instance_id): phase}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "nodes": nodes}), encoding="utf-8")
        temporary.replace(self.path)
        self.nodes = nodes

    def _credential(self, instance_id: int, phase: str):
        return self.credential_factory(f"EverSpark Forge/Node {instance_id}/{phase}")
