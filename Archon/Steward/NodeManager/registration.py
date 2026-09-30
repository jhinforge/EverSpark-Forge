"""Join grants bootstrap a durable Node credential; sessions fence Agent runtimes."""
import hmac
import time
from dataclasses import asdict
from .identity import new_id, validate_id
from .models.node import Node, Lease
from .inventory import inventory
from .transport.auth import digest, secret
from .errors import NodeError
from .lifecycle import timestamp


class Registration:
    def __init__(self, manager):
        self.manager = manager

    def issue_join(self, ttl=3600):
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not 1 <= ttl <= 86400:
            raise NodeError("Join TTL must be 1..86400 seconds", 400)
        token = secret()
        with self.manager.lock:
            nodes, joins = self.manager.registry.candidates()
            joins = {k: v for k, v in joins.items() if v["node_id"] is not None or v["expires_at"] > time.time()}
            joins[digest(token)] = {"expires_at": time.time()+ttl, "enrollment_id": None, "node_id": None}
            self.manager.registry.publish(nodes, joins)
        return token

    def revoke_join(self, token):
        with self.manager.lock:
            nodes, joins = self.manager.registry.candidates()
            joins.pop(digest(token), None)
            self.manager.registry.publish(nodes, joins)

    def register(self, body):
        runtime = validate_id(body.get("runtime_id"), "runtime_id")
        enrollment = validate_id(body.get("enrollment_id"), "enrollment_id")
        info = inventory(body.get("info"))
        capacity = info["resources"]
        manager = self.manager
        with manager.lock:
            nodes, joins = manager.registry.candidates()
            node_id = body.get("node_id")
            if node_id:
                validate_id(node_id)
                previous = nodes.get(node_id)
                credential = manager.registry.credential(node_id).get() if previous else None
                if (not previous or previous["status"] == "removed" or previous["enrollment_id"] != enrollment or not credential
                        or not hmac.compare_digest(digest(body.get("credential")), digest(credential))):
                    raise NodeError("Invalid Node credential", 403)
            else:
                grant = joins.get(digest(body.get("join_token")))
                if not grant or grant["expires_at"] <= time.time() or grant["enrollment_id"] not in (None, enrollment):
                    raise NodeError("Join token expired, claimed or unauthorized", 403)
                node_id = grant["node_id"] or new_id()
                if nodes.get(node_id, {}).get("status") == "removed":
                    raise NodeError("Node removed", 403)
                credential = manager.registry.credential(node_id).get() or secret()
                manager.registry.credential(node_id).set(credential)  # before publishing the index
                grant.update(node_id=node_id, enrollment_id=enrollment)
            previous_lease = manager.leases.get(node_id)
            session = previous_lease.session if previous_lease and previous_lease.runtime_id == runtime else secret()
            seen = timestamp()
            record = asdict(Node(node_id, enrollment, info["hostname"], info["system"], info["hardware"], capacity,
                                 info.get("provider_metadata", {}), "online", seen))
            if node_id not in manager.registry.nodes:
                # Commit the claimed identity before admission. If admission storage
                # fails, retries resume this joining Node instead of allocating another.
                nodes[node_id] = {**record, "status": "joining"}
                manager.registry.publish(nodes, joins)
                nodes, joins = manager.registry.candidates()
            nodes[node_id] = record
            manager.registry.publish(nodes, joins)  # session becomes usable only after durable publication
            manager.leases[node_id] = Lease(runtime, session, time.monotonic(), seen, capacity["allocatable"])
            manager.tasks.ensure(node_id)
            if previous_lease and previous_lease.runtime_id != runtime:
                manager.tasks.reconnect(node_id)
            manager.lock.notify_all()
            return {"node_id": node_id, "credential": credential, "runtime_id": runtime, "session": session,
                    "heartbeat_interval": manager.heartbeat_interval, "lease_timeout": manager.lease_timeout}
