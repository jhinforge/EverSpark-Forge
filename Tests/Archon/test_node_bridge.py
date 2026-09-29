from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from Archon.Steward.DeploymentManager.manager import DeploymentManager
from Archon.Gate.control_server import ControlServer
from Archon.Steward.NodeManager.bridge import NodeBridge, NodeRegistrationError, tailscale_ip
from Archon.Steward.vast_instances import VastError
from Archon.Vault.windows_credentials import CredentialError
from Legate.Envoy.node_agent import BridgeError, execute, execute_once, run as run_agent


class Machine:
    def one(self, instance_id):
        return {"id": instance_id, "actual_status": "running", "ssh_host": None,
                "ssh_port": None}


class Identity:
    def public_key(self):
        raise AssertionError("Agent deployment must not attach an SSH key")


class Credentials:
    values = {}
    fail_targets = set()

    def __init__(self, target):
        self.target = target

    def get(self):
        return self.values.get(self.target)

    def set(self, secret):
        self.values[self.target] = secret

    def delete(self):
        if self.target in self.fail_targets:
            raise CredentialError("Cannot delete the Windows credential")
        self.values.pop(self.target, None)


def post(url, path, body):
    request = Request(url + path, data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


class NodeBridgeTests(unittest.TestCase):
    def test_agent_journal_replays_result_without_running_command_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "agent.json"
            task = {"id": "a" * 32, "action": "deploy", "message": ""}
            with patch("Legate.Envoy.node_agent.execute", return_value={
                "status": "completed", "output": "ready", "exit_code": 0}) as command:
                self.assertEqual(execute_once(task, journal)["output"], "ready")
                self.assertEqual(execute_once(task, journal)["output"], "ready")
                command.assert_called_once()
            self.assertNotIn("message", journal.read_text())
            with self.assertRaisesRegex(ValueError, "collision"):
                execute_once({**task, "message": "changed"}, journal)

    def test_agent_journal_never_reexecutes_uncertain_task(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "agent.json"
            task = {"id": "b" * 32, "action": "deploy", "message": ""}
            with patch("Legate.Envoy.node_agent.execute", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    execute_once(task, journal)
            with patch("Legate.Envoy.node_agent.execute") as command:
                result = execute_once(task, journal)
                command.assert_not_called()
            self.assertEqual(result["status"], "failed")
            self.assertIn("outcome unknown", result["output"])

    def test_archon_restart_keeps_interrupted_job_visible_without_replaying(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "deployment_states.json"
            state.write_text(json.dumps({"99": {"status": "deploying"}}))
            jobs = Path(directory) / "deployment_states_jobs.json"
            jobs.write_text(json.dumps({"job123": {"id": "job123", "instance_id": 99,
                "action": "deploy", "status": "running", "stage": "agent_execution"}}))
            manager = DeploymentManager(Machine(), Identity(), state_path=state,
                log_path=Path(directory) / "deploy.log")
            self.assertEqual(manager.status(99)["status"], "deployment_unknown")
            self.assertEqual(manager.job("job123")["stage"], "archon_restart")
            self.assertIn("outcome is unknown", manager.job("job123")["detail"])
            self.assertEqual(json.loads(jobs.read_text())["job123"]["status"], "failed")
            manager.jobs["job123"]["detail"] = "secret from remote output"
            manager._save_jobs()
            self.assertNotIn("secret from remote output", jobs.read_text())

    def test_waiting_node_exposes_elapsed_time_and_actionable_timeout(self):
        bridge = NodeBridge("127.0.0.1", 0)
        try:
            bridge.configure_auth_key("test-key")
            token = bridge.reserve()
            bridge.bind(token, 99)
            waiting = bridge.status(99)
            self.assertEqual(waiting["stage"], "awaiting_agent")
            self.assertGreaterEqual(waiting["elapsed_seconds"], 0)
            with self.assertRaises(NodeRegistrationError) as error:
                bridge.execute(99, "deploy", timeout=0)
            self.assertIn("/workspace/everspark-node.log", error.exception.detail)
            self.assertIn("/workspace/everspark-tailscale.log", error.exception.detail)
            bridge.register(token, 99)
            self.assertEqual(bridge.status(99), {"status": "online"})
        finally:
            bridge.close()

    def test_machine_list_reconciles_destroyed_node(self):
        with tempfile.TemporaryDirectory() as directory:
            Credentials.values = {}
            Credentials.fail_targets = set()
            bridge = NodeBridge("127.0.0.1", 0, state_path=Path(directory) / "nodes.json",
                                credential_factory=Credentials)
            bridge.configure_auth_key("test-key")
            token = bridge.reserve()
            bridge.bind(token, 99)

            class EmptyInventory(Machine):
                def list(self, _cursor):
                    return {"instances": [], "next_token": None, "total": 0}

                def one(self, _instance_id):
                    raise VastError("Vast instance was not found", 404)

            machines = EmptyInventory()
            manager = DeploymentManager(machines, Identity(), bridge=bridge,
                state_path=Path(directory) / "deployments.json",
                log_path=Path(directory) / "deploy.log")
            backend = ControlServer(("127.0.0.1", 0), machines, deployments=manager)
            worker = threading.Thread(target=backend.serve_forever)
            worker.start()
            try:
                with urlopen(f"http://127.0.0.1:{backend.server_port}/machines/vast/instances") as reply:
                    self.assertEqual(json.load(reply)["instances"], [])
                self.assertFalse(bridge.configured(99))
                self.assertNotIn("EverSpark Forge/Node 99/joining", Credentials.values)
            finally:
                backend.shutdown()
                backend.server_close()
                worker.join(3)
                bridge.close()

    def test_used_agent_key_does_not_silently_rent_in_ssh_mode(self):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.configure_auth_key("one-off-key")
        token = bridge.reserve()
        bridge.bind(token, 99)

        class Offers:
            def quote(self, _offer_id):
                return {"cuda_max_good": 12.8}

        class Machines:
            def create(self, *_args, **_kwargs):
                raise AssertionError("Should not rent an SSH Pod with an exhausted Agent key")

        backend = ControlServer(("127.0.0.1", 0), Machines(), Offers(),
                                type("Deployments", (), {"bridge": bridge})())
        worker = threading.Thread(target=backend.serve_forever)
        worker.start()
        try:
            url = f"http://127.0.0.1:{backend.server_port}/machines/vast/rent"
            request = Request(url, data=b'{"offer_id":71}',
                              headers={"Content-Type": "application/json"})
            with self.assertRaises(HTTPError) as exhausted:
                urlopen(request, timeout=3)
            self.assertEqual(exhausted.exception.code, 409)
            self.assertIn("new key", exhausted.exception.read().decode())
        finally:
            backend.shutdown()
            backend.server_close()
            worker.join(3)
            bridge.close()

    def test_complete_inventory_prunes_destroyed_node_and_retains_stopped_node(self):
        with tempfile.TemporaryDirectory() as directory:
            Credentials.values = {}
            Credentials.fail_targets = set()
            state = Path(directory) / "nodes.json"
            deployment_state = Path(directory) / "deployments.json"
            deployment_state.write_text(json.dumps({"99": {"status": "ready"}}))
            registry = {"state_path": state, "credential_factory": Credentials}
            bridge = NodeBridge("127.0.0.1", 0, **registry)
            try:
                bridge.configure_auth_key("used-key")
                token = bridge.reserve()
                bridge.bind(token, 99)
                session = bridge.register(token, 99)["session"]
                self.assertNotIn(token, state.read_text())
                self.assertNotIn(session, state.read_text())
            finally:
                bridge.close()

            restored = NodeBridge("127.0.0.1", 0, **registry)
            try:
                class Inventory(Machine):
                    fail = False
                    destroyed = False

                    def list(self, cursor):
                        if self.fail:
                            raise VastError("Temporary Vast outage")
                        return {"instances": [{"id": 99, "actual_status": "stopped"}],
                                "next_token": None}

                    def one(self, instance_id):
                        if self.destroyed:
                            raise VastError("Vast instance was not found", 404)
                        return super().one(instance_id)

                machines = Inventory()
                manager = DeploymentManager(machines, Identity(), bridge=restored,
                    state_path=deployment_state, log_path=Path(directory) / "deploy.log")
                first_page = {"instances": [{"id": 12}], "next_token": "next", "total": 2}
                self.assertTrue(manager.reconcile_instances(first_page))
                self.assertTrue(restored.configured(99))
                machines.fail = True
                self.assertFalse(manager.reconcile_instances(first_page))
                self.assertTrue(restored.configured(99))
                self.assertFalse(manager.reconcile_instances({"instances": [],
                                                               "next_token": None, "total": 2}))
                self.assertTrue(restored.configured(99))
                self.assertTrue(manager.reconcile_instances({"instances": [],
                                                              "next_token": None, "total": 0}))
                self.assertTrue(restored.configured(99))  # Single-instance check still finds it.

                machines.destroyed = True
                Credentials.fail_targets = {"EverSpark Forge/Node 99/online"}
                self.assertTrue(manager.reconcile_instances({"instances": [],
                                                              "next_token": None, "total": 0}))
                self.assertFalse(restored.configured(99))
                self.assertEqual(manager.status(99)["status"], "not_deployed")
                self.assertNotIn("99", json.loads(state.read_text())["nodes"])
                self.assertEqual(json.loads(state.read_text())["retired"], [99])
                self.assertNotIn("EverSpark Forge/Node 99/joining", Credentials.values)
            finally:
                Credentials.fail_targets = set()
                restored.close()
            empty = NodeBridge("127.0.0.1", 0, **registry)
            try:
                self.assertEqual(json.loads(state.read_text())["retired"], [])
                self.assertNotIn("EverSpark Forge/Node 99/online", Credentials.values)
                empty.configure_auth_key("used-key")
                self.assertIsNone(empty.auth_key)
                empty.configure_auth_key("fresh-key")
                self.assertTrue(empty.reserve())
            finally:
                empty.close()

    def test_agent_registers_again_when_archon_rejects_old_session(self):
        seen = []

        def request(_url, path, body):
            seen.append((path, body))
            if path == "/node/register":
                return {"session": "first" if len(seen) == 1 else "second"}
            if body["session"] == "first":
                raise BridgeError(403)
            raise KeyboardInterrupt  # Stop after confirming the second session is used.

        with patch.dict(os.environ, {"EVERSPARK_NODE_BRIDGE_URL": "http://100.1.2.3:8766",
                                  "EVERSPARK_NODE_BOOTSTRAP": "bootstrap",
                                  "CONTAINER_ID": "99"}), \
             patch("Legate.Envoy.node_agent.request", side_effect=request), \
             patch("Legate.Envoy.node_agent.time.sleep"):
            with self.assertRaises(KeyboardInterrupt):
                run_agent()
        self.assertEqual([path for path, _ in seen],
                         ["/node/register", "/node/next", "/node/register", "/node/next"])
        self.assertEqual(seen[2][1]["bootstrap"], "bootstrap")
        self.assertEqual(seen[-1][1]["session"], "second")

    def test_registration_can_finish_after_response_is_lost_during_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            Credentials.values = {}
            registry = {"state_path": Path(directory) / "nodes.json",
                        "credential_factory": Credentials}
            first = NodeBridge("127.0.0.1", 0, **registry)
            first.start()
            try:
                first.auth_key = "one-off-key"
                token = first.reserve()
                first.bind(token, 99)
                first_session = post(first.url, "/node/register", {
                    "instance_id": 99, "bootstrap": token})["session"]
                with self.assertRaises(HTTPError) as replay:
                    post(first.url, "/node/register", {"instance_id": 99,
                                                        "bootstrap": token})
                self.assertEqual(replay.exception.code, 403)
            finally:
                first.close()
            second = NodeBridge("127.0.0.1", 0, **registry)
            second.start()
            try:
                recovered_session = post(second.url, "/node/register", {
                    "instance_id": 99, "bootstrap": token})["session"]
                self.assertNotEqual(first_session, recovered_session)
                with self.assertRaises(HTTPError) as stale:
                    post(second.url, "/node/next", {"instance_id": 99,
                                                     "session": first_session})
                self.assertEqual(stale.exception.code, 403)
            finally:
                second.close()

    def test_running_agent_and_ready_forge_survive_archon_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            Credentials.values = {}
            state = Path(directory) / "nodes.json"
            deployment_state = Path(directory) / "deployments.json"
            deployment_state.write_text(json.dumps({"99": {"status": "ready", "revision": "abc123"}}))
            registry = {"state_path": state, "credential_factory": Credentials}
            first = NodeBridge("127.0.0.1", 0, **registry)
            first.auth_key = "one-off-key"
            first.start()
            try:
                token = first.reserve()
                first.bind(token, 99)
                self.assertNotIn(token, state.read_text())
            finally:
                first.close()

            joining = NodeBridge("127.0.0.1", 0, **registry)
            joining.start()
            try:
                self.assertEqual(joining.status(99)["status"], "joining")
                session = post(joining.url, "/node/register", {"instance_id": 99,
                                                                  "bootstrap": token})["session"]
                self.assertNotIn(session, state.read_text())
            finally:
                joining.close()

            restored = NodeBridge("127.0.0.1", 0, **registry)
            restored.start()
            try:
                manager = DeploymentManager(Machine(), Identity(), bridge=restored,
                    run=lambda *_args, **_kw: self.fail("SSH must not be called"),
                    state_path=deployment_state, log_path=Path(directory) / "deploy.log")
                self.assertEqual(manager.status(99)["status"], "ready")
                self.assertEqual(restored.status(99), {"status": "offline"})
                with self.assertRaises(HTTPError) as invalid:
                    post(restored.url, "/node/next", {"instance_id": 99,
                                                      "session": "invalid"})
                self.assertEqual(invalid.exception.code, 403)
                job = manager.start(99, "discuss", "你好")
                task = post(restored.url, "/node/next", {"instance_id": 99,
                                                          "session": session})
                self.assertEqual(task["action"], "discuss")
                self.assertEqual(restored.status(99), {"status": "online"})
                post(restored.url, "/node/result", {"instance_id": 99,
                    "session": session, "task_id": task["id"], "result": {
                        "status": "completed", "output": "回复成功", "exit_code": 0}})
                for _ in range(100):
                    result = manager.job(job["id"])
                    if result["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(result["reply"], "回复成功")
            finally:
                restored.close()

    def test_tailscale_ip_finds_windows_install_without_path(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Tailscale" / "tailscale.exe"
            executable.parent.mkdir()
            executable.touch()
            calls = []

            def run(command, **_kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, "100.77.3.5\n", "")

            with patch.dict(os.environ, {"ProgramFiles": directory}, clear=True), \
                 patch("Archon.Steward.NodeManager.bridge.shutil.which", return_value=None):
                self.assertEqual(tailscale_ip(run=run), "100.77.3.5")
            self.assertEqual(calls, [[str(executable), "ip", "-4"]])

    def test_tailscale_ip_reports_missing_executable(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("Archon.Steward.NodeManager.bridge.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Tailscale CLI not found"):
                tailscale_ip()

    def test_agent_rejects_unknown_action_without_shell(self):
        self.assertEqual(execute("shell", "rm -rf /"),
                         {"status": "failed", "output": "Unknown Node Agent task",
                          "exit_code": 2})

    def test_agent_registers_and_executes_deployment_without_ssh(self):
        bridge = NodeBridge("127.0.0.1", 0)
        bridge.auth_key = "one-off-test-key"
        bridge.start()
        try:
            bootstrap = bridge.reserve()
            bridge.bind(bootstrap, 99)
            self.assertIsNone(bridge.auth_key)
            with self.assertRaises(HTTPError) as wrong_id:
                post(bridge.url, "/node/register", {"instance_id": 100,
                                                     "bootstrap": bootstrap})
            self.assertEqual(wrong_id.exception.code, 403)
            session = post(bridge.url, "/node/register", {"instance_id": 99,
                                                           "bootstrap": bootstrap})["session"]
            with self.assertRaises(HTTPError) as replay:
                post(bridge.url, "/node/register", {"instance_id": 99,
                                                     "bootstrap": bootstrap})
            self.assertEqual(replay.exception.code, 403)
            with self.assertRaises(HTTPError) as wrong_session:
                post(bridge.url, "/node/next", {"instance_id": 99, "session": "bad"})
            self.assertEqual(wrong_session.exception.code, 403)

            with tempfile.TemporaryDirectory() as directory:
                manager = DeploymentManager(Machine(), Identity(), bridge=bridge,
                    run=lambda *_args, **_kw: self.fail("SSH must not be called"),
                    state_path=Path(directory) / "state.json",
                    log_path=Path(directory) / "deployment.log")
                job = manager.start(99, "deploy")
                seen = []

                def agent():
                    for _ in range(3):
                        task = post(bridge.url, "/node/next", {"instance_id": 99,
                                                                 "session": session})
                        seen.append(task["action"])
                        post(bridge.url, "/node/result", {"instance_id": 99,
                            "session": session, "task_id": task["id"], "result": {
                                "status": "completed", "output": "abc123" if
                                task["action"] == "revision" else "ready", "exit_code": 0}})

                worker = threading.Thread(target=agent)
                worker.start()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                for _ in range(100):
                    result = manager.job(job["id"])
                    if result["status"] != "running":
                        break
                    time.sleep(.01)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["revision"], "abc123")
                self.assertEqual(seen, ["deploy", "health", "revision"])
                self.assertEqual(manager.status(99)["status"], "ready")
                self.assertEqual(bridge.status(99), {"status": "online"})
                self.assertIn('"event": "agent_exit"',
                              (Path(directory) / "deployment.log").read_text())
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
