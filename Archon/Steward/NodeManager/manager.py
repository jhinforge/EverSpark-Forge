"""Provider-independent coordinator for Node registration, leases and task transport."""
import copy
import logging
import threading
from .registry import NodeRegistry
from .registration import Registration
from .heartbeat import Heartbeat
from .lifecycle import Lifecycle
from .tasks import TaskChannel
from .transport.server import NodeServer


class NodeManager:
    def __init__(self, host, port=8766, *, state_path=None, credential_factory=None,
                 heartbeat_interval=10, lease_timeout=45):
        if heartbeat_interval <= 0 or lease_timeout <= heartbeat_interval:
            raise ValueError("Lease timeout must exceed heartbeat interval")
        self.registry = NodeRegistry(state_path, credential_factory)
        self.lock = threading.Condition(threading.RLock())
        self.leases = {}
        self.heartbeat_interval, self.lease_timeout = heartbeat_interval, lease_timeout
        self.tasks = TaskChannel(self)
        self.lifecycle, self.registration, self.heartbeat = Lifecycle(self), Registration(self), Heartbeat(self)
        self.server = NodeServer((host, port), self)
        self.url = f"http://{host}:{self.server.server_port}"
        self.stop = threading.Event()
        self.thread = self.monitor = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="archon-nodes")
        self.monitor = threading.Thread(target=self._monitor, daemon=True, name="archon-node-leases")
        self.thread.start()
        self.monitor.start()

    def listen_on(self, host):
        """Move the listener without replacing identity, leases or task queues."""
        if host == self.server.server_address[0]:
            return
        replacement = NodeServer((host, self.server.server_port), self)
        worker = threading.Thread(target=replacement.serve_forever, daemon=True, name="archon-nodes")
        previous, previous_thread = self.server, self.thread
        self.server, self.thread = replacement, worker
        self.url = f"http://{host}:{replacement.server_port}"
        worker.start()
        if previous_thread:
            previous.shutdown()
            previous_thread.join(5)
        previous.server_close()

    def _monitor(self):
        while not self.stop.wait(min(1, self.heartbeat_interval)):
            try:
                with self.lock:
                    self.lifecycle.expire()
            except (OSError, RuntimeError):
                logging.getLogger(__name__).error("Node lease persistence unavailable")

    def close(self):
        self.stop.set()
        with self.lock:
            self.lock.notify_all()
        if self.thread:
            self.server.shutdown()
            self.thread.join(5)
        if self.monitor:
            self.monitor.join(5)
        self.server.server_close()

    def issue_join_token(self, ttl=3600):
        return self.registration.issue_join(ttl)

    def revoke_join_token(self, token):
        self.registration.revoke_join(token)

    def node_for_join(self, join_ref):
        with self.lock:
            grant = self.registry.joins.get(join_ref, {})
            node_id = grant.get("node_id")
            return node_id if grant.get("enrollment_id") and self.configured(node_id) else None

    def status(self, node_id):
        with self.lock:
            self.lifecycle.expire()
            node = self.registry.nodes.get(node_id)
            if not node:
                return {"status": "unconfigured"}
            result = copy.deepcopy(node)
            result.pop("enrollment_id", None)
            lease = self.leases.get(node_id)
            result["runtime_id"] = lease.runtime_id if lease else None
            if lease:
                result["last_seen"], result["load"] = lease.last_seen, dict(lease.load)
                result["resources"]["allocatable"] = copy.deepcopy(lease.allocatable)
            if result["status"] != "online":
                result["resources"]["allocatable"] = None  # Do not expose stale availability for use.
            if result["status"] == "offline":
                result["stage"] = "agent_disconnected"
            return result

    def list_nodes(self):
        with self.lock:
            return [self.status(key) for key in self.registry.nodes]

    def runtime_id(self, node_id):
        with self.lock:
            lease = self.leases.get(node_id)
            return lease.runtime_id if lease else None

    def configured(self, node_id):
        with self.lock:
            node = self.registry.nodes.get(node_id)
            return bool(node and node["status"] != "removed")

    def remove(self, node_id):
        self.lifecycle.remove(node_id)

    def execute(self, node_id, action, message="", timeout=240, task_id=None, forge="concept"):
        return self.tasks.execute(node_id, action, message, timeout, task_id, forge)
