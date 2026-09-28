from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "Archon" / "Gate" / "CLI" / "archon.py"


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ArchonOnlyTests(unittest.TestCase):
    def test_control_mode_starts_without_pythonpath_or_forge_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            backend_port, portal_port = unused_port(), unused_port()
            while portal_port == backend_port:
                portal_port = unused_port()
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env.update({
                "EVERSPARK_WEBUI_PORT": str(portal_port),
                "EVERSPARK_ORCHESTRATOR_PORT": str(backend_port),
                "EVERSPARK_LOG_DIR": temporary,
                "EVERSPARK_WEBUI_LOG": str(Path(temporary) / "webui.log"),
                "EVERSPARK_WEBUI_HOST": "0.0.0.0",
                "EVERSPARK_ORCHESTRATOR_URL": "http://example.invalid:8765",
            })
            process = subprocess.Popen(
                [sys.executable, "-I", str(ENTRY), "start"], cwd=temporary,
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        stdout, stderr = process.communicate()
                        self.fail(f"Archon exited: {stdout!r} {stderr!r}")
                    try:
                        with urlopen(f"http://127.0.0.1:{portal_port}/api/runtime/status", timeout=1) as response:
                            status = json.load(response)
                        break
                    except URLError:
                        if time.monotonic() > deadline:
                            self.fail("Portal did not start")
                        time.sleep(0.05)
                self.assertEqual(status["mode"], "archon-only")
                self.assertTrue(status["ready"])
                self.assertTrue(status["services"]["archon_backend"]["online"])
                self.assertFalse(status["services"]["image_forge"]["online"])
                with urlopen(f"http://127.0.0.1:{portal_port}/") as response:
                    self.assertIn(b"EverSpark Forge", response.read())
                with urlopen(f"http://127.0.0.1:{backend_port}/health") as response:
                    self.assertEqual(json.load(response)["mode"], "archon-only")
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(f"http://127.0.0.1:{portal_port}/api/generate",
                                    data=b'{"message":"test"}',
                                    headers={"Content-Type": "application/json"}), timeout=2)
                self.assertEqual(caught.exception.code, 503)
                self.assertIn("No Legate", caught.exception.read().decode())
                self.assertTrue((Path(temporary) / "webui.log").exists())
                self.assertTrue((Path(temporary) / "archon/gate.log").exists())
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
