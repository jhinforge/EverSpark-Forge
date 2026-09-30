"""Control restart recovery must recheck health before enabling discussion."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from Archon.Steward.DeploymentManager.manager import DeploymentManager
from Archon.Steward.vast_instances import VastError


class Machines:
    def one(self, instance_id):
        return {"id": instance_id, "actual_status": "running"}


class Bridge:
    def __init__(self):
        self.runtime = "a" * 32
        self.online = True
        self.fail = False
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def configured(self, instance_id):
        return True

    def instance_ids(self):
        return {99}

    def prune(self, live_ids):
        return set()

    def runtime_id(self, instance_id):
        return self.runtime if self.online else None

    def status(self, instance_id):
        return {"status": "online" if self.online else "offline", "runtime_id": self.runtime_id(instance_id)}

    def execute(self, instance_id, action, message="", **kwargs):
        self.calls.append(action)
        if action == "health":
            self.entered.set()
            if not self.release.wait(3):
                raise RuntimeError("test health timeout")
            if self.fail:
                raise VastError("health failed", 503)
        return "abc123" if action == "revision" else "remote reply"


class ConnectionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        state = root / "states.json"
        state.write_text(json.dumps({"99": {"status": "ready", "runtime_id": "a" * 32}}))
        self.bridge = Bridge()
        self.manager = DeploymentManager(Machines(), object(), bridge=self.bridge,
            state_path=state, log_path=root / "deploy.log")
        self.inventory = {"instances": [{"id": 99, "actual_status": "running"}], "total": 1}

    def settle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.manager.lock:
                busy = any(job["status"] == "running" for job in self.manager.jobs.values())
            with self.manager.connection_verification.lock:
                pending = bool(self.manager.connection_verification.pending)
            if not busy and not pending:
                for worker in list(self.manager.threads.values()):
                    worker.join(1)
                return
            time.sleep(.01)
        self.fail("verification did not finish")

    def test_restart_rechecks_health_and_restores_existing_discussion_channel(self):
        self.assertEqual(self.manager.status(99)["status"], "verification_required")
        self.manager.reconcile_instances(self.inventory)
        self.settle()
        self.assertEqual(self.manager.status(99)["status"], "ready")
        self.assertEqual(self.bridge.calls, ["health", "revision"])
        job = self.manager.start(99, "discuss", "hello")
        self.settle()
        self.assertEqual(self.manager.job(job["id"])["reply"], "remote reply")
        self.assertNotIn("deploy", self.bridge.calls)

    def test_offline_node_waits_and_repeated_polling_schedules_only_one_check(self):
        self.bridge.online = False
        self.manager.reconcile_instances(self.inventory)
        self.assertEqual(self.bridge.calls, [])
        self.bridge.online = True
        self.bridge.release.clear()
        self.manager.reconcile_instances(self.inventory)
        self.assertTrue(self.bridge.entered.wait(2))
        for _ in range(10):
            self.manager.reconcile_instances(self.inventory)
        self.assertEqual(self.bridge.calls, ["health"])
        self.bridge.release.set()
        self.settle()
        self.assertEqual(self.manager.status(99)["status"], "ready")

    def test_failed_check_keeps_discussion_disabled_without_poll_retry_storm(self):
        self.bridge.fail = True
        self.manager.reconcile_instances(self.inventory)
        self.settle()
        for _ in range(5):
            self.manager.reconcile_instances(self.inventory)
        self.assertEqual(self.bridge.calls, ["health"])
        self.assertEqual(self.manager.status(99)["status"], "verification_required")
        with self.assertRaises(VastError):
            self.manager.start(99, "discuss", "hello")
        self.bridge.fail = False
        self.manager.start(99, "verify")
        self.settle()
        self.assertEqual(self.manager.status(99)["status"], "ready")

    def test_new_agent_runtime_triggers_new_verification(self):
        self.manager.reconcile_instances(self.inventory)
        self.settle()
        self.bridge.runtime = "b" * 32
        self.manager.reconcile_instances(self.inventory)
        self.settle()
        self.assertEqual(self.bridge.calls, ["health", "revision", "health", "revision"])
        self.assertEqual(self.manager.status(99)["runtime_id"], "b" * 32)


if __name__ == "__main__":
    unittest.main()
