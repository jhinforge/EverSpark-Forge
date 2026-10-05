"""Exercise ownership and readiness with an actual control backend process."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "Archon/Client/Windows/backend.py"


class DesktopBackendTests(unittest.TestCase):
    def launch(self, directory, **extra):
        ready = Path(directory) / "准备 ready.json"
        env = {**os.environ, "EVERSPARK_WEBUI_PORT": "0", "EVERSPARK_ORCHESTRATOR_PORT": "0",
               "EVERSPARK_REMOTE_ORCHESTRATOR_PORT": "0", "EVERSPARK_NODE_HOST": "127.0.0.1",
               "EVERSPARK_NODE_PORT": "0", "EVERSPARK_NODE_STATE": str(Path(directory)/"nodes.json"),
               "EVERSPARK_LOG_DIR": str(Path(directory)/"logs"), **extra}
        process = subprocess.Popen([sys.executable, "-I", "-u", str(ENTRY),
            "--ready-file", str(ready), "--nonce", "test-owner"], env=env, cwd=directory,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.cleanup_process, process)
        return process, ready

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def wait_ready(self, process, path):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail(f"Backend exited: {process.communicate()}")
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
            time.sleep(0.05)
        self.fail("Backend readiness timed out")

    def test_ready_identity_and_graceful_owned_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="EverSpark 中文 path ") as directory:
            process, ready = self.launch(directory)
            time.sleep(0.15)
            self.assertFalse(ready.exists(), "Backend must wait for Job ownership handshake")
            process.stdin.write(b"start\n"); process.stdin.flush()
            state = self.wait_ready(process, ready)
            self.assertEqual(state["pid"], process.pid)
            self.assertEqual(state["nonce"], "test-owner")
            with urlopen(state["url"] + "/api/runtime/status", timeout=3) as response:
                status = json.load(response)
            self.assertTrue(status["services"]["archon_backend"]["online"])
            with urlopen(state["url"] + "/", timeout=3) as response:
                self.assertIn(b"EverSpark Forge", response.read())
            process.stdin.write(b"stop\n"); process.stdin.flush()
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertFalse(ready.exists())
            with self.assertRaises(OSError):
                urlopen(state["url"] + "/", timeout=1)

    def test_parent_pipe_eof_stops_the_owned_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            process, ready = self.launch(directory)
            process.stdin.write(b"start\n"); process.stdin.flush()
            self.wait_ready(process, ready)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertFalse(ready.exists())

    def test_port_conflict_exits_without_stopping_another_listener(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            process, ready = self.launch(directory, EVERSPARK_NODE_PORT=str(listener.getsockname()[1]))
            process.stdin.write(b"start\n"); process.stdin.flush()
            self.assertEqual(process.wait(timeout=10), 1)
            self.assertFalse(ready.exists())
            with socket.create_connection(listener.getsockname(), timeout=1):
                pass

    def test_eof_before_ownership_handshake_never_starts_services(self):
        with tempfile.TemporaryDirectory() as directory:
            process, ready = self.launch(directory)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 1)
            self.assertFalse(ready.exists())


if __name__ == "__main__":
    unittest.main()
