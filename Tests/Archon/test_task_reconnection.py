"""A new runtime reconciles original task identities rather than rerunning blindly."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from Tests.Archon import test_node_registration as protocol
from Archon.Steward.NodeManager import NodeManager
from Archon.Steward.NodeManager.errors import NodeError, NodeTaskError
from Legate.Envoy.executor.journal import execute_once


class TaskReconnectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.manager = NodeManager("127.0.0.1", 0, heartbeat_interval=.1, lease_timeout=.7)
        self.addCleanup(self.manager.close)
        self.body = {"join_token": self.manager.issue_join_token(), "enrollment_id": "e"*32,
                     "runtime_id": "a"*32, "info": protocol.INFO}
        self.first = self.manager.registration.register(self.body)
        self.journal = Path(self.directory.name)/"tasks.json"

    def start_task(self):
        self.result = {}
        def work():
            try:
                self.result["output"] = self.manager.execute(self.first["node_id"], "deploy", timeout=3)
            except NodeError as exc:
                self.result["error"] = exc
        self.worker = threading.Thread(target=work)
        self.worker.start()
        self.addCleanup(self.worker.join, 4)
        return self.manager.tasks.next_task(protocol.auth(self.first))

    def restart(self):
        return self.manager.registration.register({"node_id": self.first["node_id"],
            "credential": self.first["credential"], "enrollment_id": "e"*32,
            "runtime_id": "b"*32, "info": protocol.INFO})

    def finish(self, session, task, result):
        self.manager.tasks.finish({**protocol.auth(session), "task_id": task["id"], "result": result})
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())

    def test_completed_result_is_replayed_after_agent_restart_without_duplicate_command(self):
        task = self.start_task()
        calls = []
        def execute(*args):
            calls.append(args)
            return {"status": "completed", "output": "ready", "exit_code": 0}
        execute_once(task, self.journal, executor=execute)
        second = self.restart()
        with self.assertRaises(NodeError):
            self.manager.tasks.next_task(protocol.auth(self.first))
        recovered = self.manager.tasks.next_task(protocol.auth(second))
        self.assertEqual(recovered, task)
        self.finish(second, recovered, execute_once(recovered, self.journal, executor=execute))
        self.assertEqual(calls, [("deploy", "", "concept")])
        self.assertEqual(self.result, {"output": "ready"})

    def test_interrupted_result_is_terminal_unknown_and_never_reexecuted(self):
        task = self.start_task()
        def interrupted(*args):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            execute_once(task, self.journal, executor=interrupted)
        second = self.restart()
        recovered = self.manager.tasks.next_task(protocol.auth(second))
        result = execute_once(recovered, self.journal, executor=lambda *args: self.fail("reexecuted"))
        self.finish(second, recovered, result)
        self.assertIsInstance(self.result["error"], NodeTaskError)
        self.assertIn("outcome unknown", self.result["error"].detail)
        self.assertEqual(json.loads(self.journal.read_text())[task["id"]]["state"], "completed")

    def test_progress_is_authenticated_and_expires_with_lease_without_task_traffic(self):
        task = self.start_task()
        self.manager.heartbeat.receive({**protocol.auth(self.first), "allocatable": protocol.INFO["resources"]["allocatable"],
            "task": {"task_id": task["id"], "stage": "downloading_models", "elapsed_seconds": 10}})
        status = self.manager.tasks.status(self.first["node_id"], task["id"])
        self.assertEqual(status["stage"], "downloading_models")
        with self.manager.lock:
            self.manager.leases[self.first["node_id"]].renewed_at -= 2
            self.manager.lifecycle.expire()
        self.assertEqual(self.manager.status(self.first["node_id"])["status"], "offline")
        self.assertIsNone(self.manager.status(self.first["node_id"])["resources"]["allocatable"])
        self.assertTrue(self.manager.tasks.status(self.first["node_id"], task["id"])["stale"])
        self.finish(self.first, task, {"status": "completed", "output": "done", "exit_code": 0})

    def test_invalid_progress_does_not_renew_lease(self):
        before = self.manager.leases[self.first["node_id"]].renewed_at
        with self.assertRaises(NodeError):
            self.manager.heartbeat.receive({**protocol.auth(self.first), "allocatable": protocol.INFO["resources"]["allocatable"],
                "task": {"task_id": "f"*32, "stage": "secret command", "elapsed_seconds": 10}})
        self.assertEqual(before, self.manager.leases[self.first["node_id"]].renewed_at)

    def test_heartbeat_records_disconnect_even_without_inventory_poll(self):
        node_id = self.first["node_id"]
        first = self.manager.status(node_id)["connection_id"]
        with self.manager.lock:
            self.manager.leases[node_id].renewed_at -= 2
        self.manager.heartbeat.receive({**protocol.auth(self.first),
            "allocatable": protocol.INFO["resources"]["allocatable"]})
        restored = self.manager.status(node_id)
        self.assertEqual(restored["status"], "online")
        self.assertEqual(restored["runtime_id"], self.first["runtime_id"])
        self.assertNotEqual(first, restored["connection_id"])
        self.manager.heartbeat.receive({**protocol.auth(self.first),
            "allocatable": protocol.INFO["resources"]["allocatable"]})
        self.assertEqual(restored["connection_id"], self.manager.status(node_id)["connection_id"])
