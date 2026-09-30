"""Server-clock lease expiry, independently of task traffic and provider inventory."""
import time
from datetime import datetime, timezone
from .errors import NodeError


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Lifecycle:
    def __init__(self, manager):
        self.manager = manager

    def expire(self):
        expired = [node_id for node_id, lease in self.manager.leases.items()
                   if self.manager.registry.nodes[node_id]["status"] in {"online", "unhealthy"}
                   and time.monotonic()-lease.renewed_at > self.manager.lease_timeout]
        if expired:
            nodes, joins = self.manager.registry.candidates()
            for node_id in expired:
                nodes[node_id].update(status="offline", last_seen=self.manager.leases[node_id].last_seen)
            self.manager.registry.publish(nodes, joins)
            self.manager.lock.notify_all()

    def remove(self, node_id):
        with self.manager.lock:
            if not isinstance(node_id, str) or node_id not in self.manager.registry.nodes:
                raise NodeError("Unknown Node", 404)
            nodes, joins = self.manager.registry.candidates()
            nodes[node_id]["status"] = "removed"
            lease = self.manager.leases.get(node_id)
            if lease:
                nodes[node_id]["last_seen"] = lease.last_seen
            joins = {k: v for k, v in joins.items() if v["node_id"] != node_id}
            self.manager.registry.publish(nodes, joins)
            self.manager.leases.pop(node_id, None)
            self.manager.lock.notify_all()
            try:
                self.manager.registry.credential(node_id).delete()
            except (RuntimeError, OSError):
                pass  # Tombstone is authoritative; retry cleanup at next startup.
