"""Recheck an existing Concept Forge after control or Agent recovery.

Inventory polling only schedules work; the existing verify task performs the
health check. A failed check is not retried on every WebUI poll.
"""
import logging
import threading
from Archon.Steward.vast_instances import VastError


class ConnectionVerification:
    def __init__(self, manager):
        self.manager = manager
        self.lock = threading.Lock()
        self.pending = set()
        self.attempted = {}

    def consider(self, instance_id):
        manager = self.manager
        if not manager.bridge or manager.status(instance_id).get("status") != "verification_required":
            return
        node = manager.bridge.status(instance_id)
        runtime = node.get("runtime_id")
        if node.get("status") != "online" or not runtime:
            return
        with manager.lock:
            if instance_id in manager.retired_instances or any(
                job["instance_id"] == instance_id and job["status"] == "running"
                for job in manager.jobs.values()
            ):
                return
        with self.lock:
            if instance_id in self.pending or self.attempted.get(instance_id) == runtime:
                return
            self.pending.add(instance_id)
        threading.Thread(target=self._start, args=(instance_id, runtime),
                         daemon=True, name="concept-reconnect-verification").start()

    def _start(self, instance_id, runtime):
        try:
            self.manager.start(instance_id, "verify")
        except VastError as exc:
            # A concurrent user task wins. Try again when it is finished.
            if exc.status == 409:
                return
            with self.lock:
                self.attempted[instance_id] = runtime
        except Exception as exc:
            # The manual verification action remains available after failure.
            logging.getLogger(__name__).warning(
                "Could not schedule Concept verification for instance %s: %s",
                instance_id, type(exc).__name__)
            with self.lock:
                self.attempted[instance_id] = runtime
        else:
            with self.lock:
                self.attempted[instance_id] = runtime
        finally:
            with self.lock:
                self.pending.discard(instance_id)
