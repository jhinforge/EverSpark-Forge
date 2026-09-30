import math
import time
from .transport.auth import authenticate
from .resources import allocatable
from .lifecycle import timestamp
from .errors import NodeError


class Heartbeat:
    def __init__(self, manager):
        self.manager = manager

    def receive(self, body):
        with self.manager.lock:
            node, lease = authenticate(self.manager, body)
            state = body.get("status", "online")
            load = body.get("load", {})
            if state not in {"online", "unhealthy"} or not isinstance(load, dict) or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in load.values()
            ):
                raise NodeError("Invalid heartbeat state or load", 400)
            available = allocatable(body.get("allocatable"), node["resources"]["capacity"])
            seen = timestamp()
            if node["status"] != state:
                nodes, joins = self.manager.registry.candidates()
                nodes[node["node_id"]].update(status=state, last_seen=seen)
                self.manager.registry.publish(nodes, joins)
            lease.renewed_at, lease.last_seen = time.monotonic(), seen
            lease.allocatable, lease.load = available, dict(load)
            self.manager.lock.notify_all()
            return {"status": state, "last_seen": seen}
