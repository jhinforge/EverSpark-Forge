"""Registration and ephemeral session fencing, separate from execution."""
import secrets
import threading


class Registration:
    def __init__(self, identity, transport, info):
        self.identity, self.transport, self.info = identity, transport, info
        self.runtime_id = secrets.token_hex(16)
        self.session = None
        self.lock = threading.RLock()
        self.interval = 10
        self.changed = threading.Event()

    def register(self):
        with self.lock:
            response = self.transport.request("/node/register", {**self.identity.value, "runtime_id": self.runtime_id, "info": self.info})
            if response.get("runtime_id") != self.runtime_id or not isinstance(response.get("session"), str) or not response["session"]:
                raise RuntimeError("Invalid Node session response")
            interval = response.get("heartbeat_interval")
            if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 < interval < response.get("lease_timeout", 0):
                raise RuntimeError("Invalid heartbeat configuration")
            self.identity.registered(response)  # Persist durable recovery before exposing session.
            self.interval, self.session = interval, response["session"]
            self.changed.set()
            return response

    def authentication(self):
        with self.lock:
            if not self.session:
                return None
            return {"node_id": self.identity.value["node_id"], "runtime_id": self.runtime_id, "session": self.session}

    def invalidate(self, authentication):
        with self.lock:
            if authentication and authentication.get("session") == self.session:
                self.session = None
