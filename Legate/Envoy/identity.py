"""Durable enrollment/Node credential, with atomic private local writes."""
import json
import os
import secrets
from pathlib import Path


def valid_id(value):
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


class Identity:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.value = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.value = {"enrollment_id": secrets.token_hex(16)}
            self.save(self.value)  # Commit enrollment before the first registration request.
        if (not isinstance(self.value, dict) or not valid_id(self.value.get("enrollment_id"))
                or ("node_id" in self.value and (not valid_id(self.value["node_id"]) or
                    not isinstance(self.value.get("credential"), str) or not self.value["credential"]))):
            raise RuntimeError("Invalid Agent identity; refusing to silently create a new Node")

    def save(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(self.path.name+".tmp")
        descriptor = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        self.value = dict(value)

    def bootstrap(self, token):
        if "node_id" not in self.value and token and self.value.get("join_token") != token:
            self.save({**self.value, "join_token": token})
        if "node_id" not in self.value and not self.value.get("join_token"):
            raise RuntimeError("First start requires EVERSPARK_NODE_JOIN_TOKEN")

    def registered(self, response):
        if not valid_id(response.get("node_id")) or not isinstance(response.get("credential"), str) or not response["credential"]:
            raise RuntimeError("Invalid Node registration response")
        if self.value.get("node_id") and self.value["node_id"] != response["node_id"]:
            raise RuntimeError("Archon changed Node identity")
        self.save({"enrollment_id": self.value["enrollment_id"], "node_id": response["node_id"], "credential": response["credential"]})
