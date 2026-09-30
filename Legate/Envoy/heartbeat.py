"""Independent lease renewal continues during long Forge execution."""
import threading
from .fingerprint.hardware import dynamic
from .transport import BridgeError


class Heartbeat:
    def __init__(self, registration, data_dir):
        self.registration, self.data_dir = registration, data_dir
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="node-heartbeat")

    def run(self):
        while not self.stop.is_set():
            authentication = self.registration.authentication()
            if authentication:
                try:
                    available, load = dynamic(self.data_dir, self.registration.info["resources"]["capacity"])
                    self.registration.transport.request("/node/heartbeat", {**authentication, "status": "online", "allocatable": available, "load": load})
                except BridgeError as exc:
                    if exc.status == 403:
                        self.registration.invalidate(authentication)
                except (OSError, ValueError, RuntimeError):
                    pass  # Archon lease expires independently; never pretend transport succeeded.
            self.registration.changed.wait(self.registration.interval)
            self.registration.changed.clear()

    def close(self):
        self.stop.set()
        self.registration.changed.set()
        if self.thread.ident:
            self.thread.join(30)
