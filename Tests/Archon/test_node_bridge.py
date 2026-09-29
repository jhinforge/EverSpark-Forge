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
from Archon.Steward.NodeManager.bridge import NodeBridge, tailscale_ip
from Archon.Steward.vast_instances import VastError
from Legate.Envoy.node_agent import BridgeError, execute, run as run_agent


class Machine:
    def one(self, instance_id):
        return {"id": instance_id, "actual_status": "running", "ssh_host": None,
                "ssh_port": None}


class Identity:
    def public_key(self):
        raise AssertionError("Agent deployment must not attach an SSH key")


class Credentials:
    values = {}

    def __init__(self, target):
        self.target = target

    def get(self):
        return self.values.get(self.target)

    def set(self, secret):
        self.values[self.target] = secret

    def delete(self):
        self.values.pop(self.target, None)


def post(url, path, body):
    request = Request(url + path, data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


class NodeBridgeTests(unittest.TestCase):
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
                self.assertEqual(joining.status(99), {"status": "joining"})
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
                    for _ in range(2):
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
                self.assertEqual(seen, ["deploy", "revision"])
                self.assertEqual(manager.status(99)["status"], "ready")
                self.assertEqual(bridge.status(99), {"status": "online"})
                self.assertIn('"event": "agent_exit"',
                              (Path(directory) / "deployment.log").read_text())
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
