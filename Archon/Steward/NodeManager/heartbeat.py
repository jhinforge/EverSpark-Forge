import math
import time
from .transport.auth import authenticate
from .resources import allocatable
from .lifecycle import timestamp
from .errors import NodeError
from .identity import new_id


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
            self.manager.tasks.progress(node["node_id"], body.get("task"))
            reconnected = (node["status"] == "offline" or
                           time.monotonic()-lease.renewed_at > self.manager.lease_timeout)
            seen = timestamp()
            from .bandwidth import validate
            bandwidth = validate(body.get("bandwidth"))
            changed = bandwidth is not None and bandwidth != node.get("bandwidth")
            if node["status"] != state or changed:
                nodes, joins = self.manager.registry.candidates()
                nodes[node["node_id"]].update(status=state, last_seen=seen)
                if changed:
                    nodes[node["node_id"]]["bandwidth"] = bandwidth
                self.manager.registry.publish(nodes, joins)
            if reconnected:
                lease.connection_id = new_id()
            lease.renewed_at, lease.last_seen = time.monotonic(), seen
            lease.allocatable, lease.load = available, dict(load)
            self.manager.lock.notify_all()
            return {"status": state, "last_seen": seen}
