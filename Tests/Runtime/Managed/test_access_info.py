from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Managed"))

import access_info  # noqa: E402


class AccessInfoTests(unittest.TestCase):
    def test_vast_environment_builds_complete_tunnel(self) -> None:
        info = access_info.build_access_info(
            {"PUBLIC_IPADDR": "203.0.113.10", "VAST_TCP_PORT_22": "40222"}
        )
        self.assertTrue(info["ready"])
        self.assertEqual(info["provider"], "vast")
        self.assertEqual(
            info["command"],
            "ssh -p 40222 -L 8080:127.0.0.1:8780 root@203.0.113.10",
        )
        self.assertEqual(info["local_url"], "http://127.0.0.1:8080")

    def test_explicit_overrides_are_supported(self) -> None:
        info = access_info.build_access_info(
            {
                "EVERSPARK_SSH_HOST": "pod.example.com",
                "EVERSPARK_SSH_PORT": "22022",
                "EVERSPARK_SSH_USER": "ubuntu",
                "EVERSPARK_WEBUI_PORT": "9000",
                "EVERSPARK_LOCAL_WEBUI_PORT": "9001",
            }
        )
        self.assertEqual(
            info["command"],
            "ssh -p 22022 -L 9001:127.0.0.1:9000 ubuntu@pod.example.com",
        )

    def test_missing_platform_values_are_not_guessed(self) -> None:
        info = access_info.build_access_info({})
        self.assertFalse(info["ready"])
        self.assertIsNone(info["command"])
        rendered = access_info.render_access_info(info)
        self.assertIn("missing SSH host and SSH port", rendered)
        self.assertNotIn("<pod", rendered)

    def test_invalid_port_is_rejected(self) -> None:
        with self.assertRaisesRegex(access_info.AccessInfoError, "between 1 and 65535"):
            access_info.build_access_info(
                {"PUBLIC_IPADDR": "203.0.113.10", "VAST_TCP_PORT_22": "70000"}
            )

    def test_process_environment_overrides_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system_env = root / "system"
            repo_env = root / "repo"
            system_env.write_text("PUBLIC_IPADDR=10.0.0.1\n", encoding="utf-8")
            repo_env.write_text("PUBLIC_IPADDR=10.0.0.2\n", encoding="utf-8")
            values = access_info.discovery_environment(
                {"PUBLIC_IPADDR": "10.0.0.3"}, repo_env, system_env
            )
            self.assertEqual(values["PUBLIC_IPADDR"], "10.0.0.3")

    def test_json_cli_is_machine_readable(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "Runtime" / "Managed" / "access_info.py"),
                "--json",
            ],
            env={
                "PATH": str(Path(sys.executable).parent),
                "PUBLIC_IPADDR": "203.0.113.10",
                "VAST_TCP_PORT_22": "40222",
            },
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["ready"])


if __name__ == "__main__":
    unittest.main()
