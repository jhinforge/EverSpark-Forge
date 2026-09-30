"""Vast deployment correlation. Provider IDs never become Node identities."""
import json
import threading
import time
from pathlib import Path
from Archon.Steward.NodeManager.errors import NodeError
from Archon.Steward.NodeManager.transport.auth import digest
from Archon.Steward.vast_instances import VastError


class VastNodes:
    def __init__(self, manager, path=None, auth_key=""):
        self.manager, self.path = manager, Path(path) if path else None
        self.lock = threading.RLock()
        self.pending = set()
        try:
            raw = json.loads(self.path.read_text()) if self.path else {}
        except FileNotFoundError:
            raw = {}
        if not isinstance(raw, dict) or not isinstance(raw.get("bindings", {}), dict):
            raise RuntimeError("Invalid Vast Node bindings")
        self.bindings = raw.get("bindings", {})
        self.used_key_hash = raw.get("used_key_hash", "")
        for key, reference in self.bindings.items():
            if not key.isdecimal() or int(key) < 1 or not isinstance(reference, str) or len(reference) != 64:
                raise RuntimeError("Invalid Vast Node binding")
        self.reusable = raw.get("reusable", False) is True
        self.configure_auth_key(auth_key)

    @property
    def url(self):
        return self.manager.url

    def configure_auth_key(self, auth_key, reusable=None):
        if reusable is not None:
            self.reusable = reusable
        self.agent_requested = bool(auth_key)
        self.auth_key = auth_key if auth_key and (self.reusable or digest(auth_key) != self.used_key_hash) else None

    def _save(self, bindings, key_hash):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name+".tmp")
            temporary.write_text(json.dumps({"bindings": bindings, "used_key_hash": key_hash, "reusable": self.reusable}))
            temporary.replace(self.path)
        self.bindings, self.used_key_hash = bindings, key_hash

    def reserve(self):
        with self.lock:
            if not self.auth_key or self.pending:
                raise VastError("A one-off node key is already in use", 409)
            token = self.manager.issue_join_token(ttl=86400)
            self.pending.add(digest(token))
            return token

    def environment(self, token):
        return {"EVERSPARK_TAILSCALE_AUTH_KEY": self.auth_key,
                "EVERSPARK_NODE_JOIN_TOKEN": token, "EVERSPARK_NODE_URL": self.url,
                "EVERSPARK_NODE_PROVIDER": "vast"}

    def bind(self, token, instance_id):
        with self.lock:
            reference = digest(token)
            if reference not in self.pending or isinstance(instance_id, bool) or not isinstance(instance_id, int) or instance_id < 1:
                raise VastError("Invalid Node rental binding", 400)
            self._save({**self.bindings, str(instance_id): reference}, digest(self.auth_key))
            self.pending.remove(reference)
            if not self.reusable:
                self.auth_key = None

    def discard(self, token):
        with self.lock:
            self.manager.revoke_join_token(token)
            self.pending.discard(digest(token))

    def node_id(self, instance_id):
        with self.lock:
            return self.manager.node_for_join(self.bindings.get(str(instance_id)))

    def configured(self, instance_id):
        with self.lock:
            return str(instance_id) in self.bindings

    def instance_ids(self):
        with self.lock:
            return {int(key) for key in self.bindings}

    def status(self, instance_id):
        with self.lock:
            if not self.configured(instance_id):
                return {"status": "unconfigured"}
            node_id = self.node_id(instance_id)
            if node_id:
                return self.manager.status(node_id)
            reference = self.bindings[str(instance_id)]
            with self.manager.lock:
                grant = self.manager.registry.joins.get(reference)
                return ({"status": "joining", "stage": "awaiting_agent"} if grant and grant["expires_at"] > time.time()
                        else {"status": "offline", "stage": "join_expired_or_revoked"})

    def runtime_id(self, instance_id):
        node_id = self.node_id(instance_id)
        return self.manager.runtime_id(node_id) if node_id else None

    def prune(self, live_ids):
        with self.lock:
            removed = self.instance_ids() - live_ids
            for instance_id in removed:
                reference = self.bindings[str(instance_id)]
                node_id = self.node_id(instance_id)
                if node_id:
                    self.manager.remove(node_id)
                else:
                    with self.manager.lock:
                        nodes, joins = self.manager.registry.candidates()
                        joins.pop(reference, None)
                        self.manager.registry.publish(nodes, joins)
            self._save({k: v for k, v in self.bindings.items() if int(k) not in removed}, self.used_key_hash)
            return removed

    def task_status(self, instance_id, task_id):
        node_id = self.node_id(instance_id)
        return self.manager.tasks.status(node_id, task_id) if node_id else {}

    def execute(self, instance_id, action, message="", timeout=240, **kwargs):
        deadline = time.monotonic()+timeout
        if not self.configured(instance_id):
            raise VastError("Node was not provisioned for Agent execution", 409)
        while not (node_id := self.node_id(instance_id)):
            if not self.configured(instance_id):
                raise VastError("Node instance was destroyed", 404)
            if time.monotonic() >= deadline:
                raise VastError("Node Agent did not register before timeout", 504)
            with self.manager.lock:
                self.manager.lock.wait(min(1, max(0, deadline-time.monotonic())))
        try:
            return self.manager.execute(node_id, action, message, timeout=max(.001, deadline-time.monotonic()), **kwargs)
        except NodeError as exc:
            error = VastError(str(exc), exc.status)
            for field in ("stage", "detail", "exit_code"):
                if hasattr(exc, field):
                    setattr(error, field, getattr(exc, field))
            raise error from exc
