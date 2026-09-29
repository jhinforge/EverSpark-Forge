"""Persist node identities without writing registration secrets to JSON."""

from __future__ import annotations

import json
from pathlib import Path

from Archon.Vault.windows_credentials import CredentialError


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
        self.used_key_hash = raw.get("used_key_hash", "")
        retired = raw.get("retired", [])
        if not isinstance(self.used_key_hash, str) or not isinstance(retired, list) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in retired
        ):
            raise RuntimeError("Saved Node Agent identities have an invalid format")
        self.retired = set(retired)
        self._clean_retired()

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

    def save(self, instance_id: int, phase: str, secret: str, *, used_key_hash: str = "") -> None:
        # Store the credential first: a crash before the index update leaves only
        # an unused credential, never an index pointing at a missing credential.
        self._credential(instance_id, phase).set(secret)
        nodes = {**self.nodes, str(instance_id): phase}
        key_hash = used_key_hash or self.used_key_hash
        self._write(nodes, key_hash, self.retired)
        self.nodes = nodes
        self.used_key_hash = key_hash

    def remove(self, instance_ids: set[int]) -> None:
        if not instance_ids:
            return
        nodes = {key: value for key, value in self.nodes.items() if int(key) not in instance_ids}
        # Revoke the identities in the index before removing their credentials.
        retired = self.retired | instance_ids
        self._write(nodes, self.used_key_hash, retired)
        self.nodes = nodes
        self.retired = retired
        self._clean_retired()

    def _clean_retired(self) -> None:
        cleaned = set()
        for instance_id in self.retired:
            try:
                self._credential(instance_id, "joining").delete()
                self._credential(instance_id, "online").delete()
            except CredentialError:
                continue  # Retry next time the registry is opened or pruned.
            cleaned.add(instance_id)
        if cleaned:
            self.retired.difference_update(cleaned)
            self._write(self.nodes, self.used_key_hash, self.retired)

    def _write(self, nodes: dict, key_hash: str, retired: set[int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "nodes": nodes,
                                         "used_key_hash": key_hash,
                                         "retired": sorted(retired)}), encoding="utf-8")
        temporary.replace(self.path)

    def _credential(self, instance_id: int, phase: str):
        return self.credential_factory(f"EverSpark Forge/Node {instance_id}/{phase}")
