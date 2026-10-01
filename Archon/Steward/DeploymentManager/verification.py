"""Recheck an existing Forge after control or Agent recovery.

Inventory polling only schedules work; the existing verify task performs the
health check. A failed check is not retried on every WebUI poll.
"""
import logging
import threading
from Archon.Steward.vast_instances import VastError


class ConnectionVerification:
    def __init__(self, manager, name="concept"):
        self.manager, self.name = manager, name
        self.lock = threading.Lock()
        self.pending = set()
        self.attempted = {}
        self.online = {}
        self.connections = {}

    def consider(self, instance_id):
        manager = self.manager
        if not manager.bridge:
            return
        node = manager.bridge.status(instance_id)
        runtime = node.get("runtime_id")
        connection = node.get("connection_id") or runtime
        available = node.get("status") == "online" and bool(runtime)
        with self.lock:
            previous = self.online.get(instance_id)
            self.online[instance_id] = available
            changed = available and (
                (instance_id in self.connections and self.connections[instance_id] != connection)
                or (instance_id in self.attempted and self.attempted[instance_id] != connection))
            if available:
                self.connections[instance_id] = connection
            if previous is True and not available:
                self.attempted.pop(instance_id, None)
        if changed:
            with manager.lock:
                if manager.states.get(instance_id, {}).get("status") == "ready":
                    manager.states[instance_id] = {"status": "verification_required"}
                    manager._save()
        if not available:
            with manager.lock:
                if manager.states.get(instance_id, {}).get("status") == "ready":
                    manager.states[instance_id] = {"status": "verification_required"}
                    manager._save()
            return
        if manager.status(instance_id).get("status") != "verification_required":
            return
        with manager.lock:
            if instance_id in getattr(manager, "retired_instances", set()) or any(
                job["instance_id"] == instance_id and job["status"] == "running"
                for job in manager.jobs.values()
            ):
                return
        with self.lock:
            if instance_id in self.pending or self.attempted.get(instance_id) == connection:
                return
            self.pending.add(instance_id)
        threading.Thread(target=self._start, args=(instance_id, connection),
                         daemon=True, name=f"{self.name}-reconnect-verification").start()

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
                "Could not schedule %s verification for instance %s: %s",
                self.name, instance_id, type(exc).__name__)
            with self.lock:
                self.attempted[instance_id] = runtime
        else:
            with self.lock:
                self.attempted[instance_id] = runtime
        finally:
            with self.lock:
                self.pending.discard(instance_id)
