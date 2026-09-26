from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Managed"))

import runtime_manager  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RuntimeManagerTests(unittest.TestCase):
    def test_diffusers_is_an_optional_separate_service(self) -> None:
        with patch.dict(os.environ, {"EVERSPARK_IMAGE_BACKEND": "diffusers",
                                  "EVERSPARK_DIFFUSERS_URL": "http://127.0.0.1:8191"}):
            services = runtime_manager.service_definitions()
        self.assertEqual(services["image"].health_url, "http://127.0.0.1:8188/system_stats")
        self.assertEqual(services["diffusers"].health_url, "http://127.0.0.1:8191/health")
        self.assertEqual(services["diffusers"].log_file, "image/diffusers.log")

    def test_config_file_selects_diffusers_worker_without_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "forge.json"
            config_file.write_text('{"image_forge": {"adapter": "diffusers", "adapters": '
                                   '{"diffusers": {"base_url": "http://127.0.0.1:8195"}}}}')
            with patch.dict(os.environ, {
                "EVERSPARK_ORCHESTRATOR_CONFIG": str(config_file),
                "EVERSPARK_IMAGE_BACKEND": "", "EVERSPARK_DIFFUSERS_URL": "",
            }):
                services = runtime_manager.service_definitions()
        self.assertEqual(services["image"].health_url, "http://127.0.0.1:8188/system_stats")
        self.assertEqual(services["diffusers"].health_url, "http://127.0.0.1:8195/health")

    def test_existing_managed_comfy_config_gains_vae_without_losing_custom_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "Data/Runtime/ComfyUI/source/extra_model_paths.yaml"
            config.parent.mkdir(parents=True)
            config.write_text(
                f"everspark:\n  base_path: {root}/Data/Models/ImageForge\n"
                "  checkpoints: checkpoints\n  loras: loras\nother:\n  vae: external\n",
                encoding="utf-8",
            )
            with patch.object(runtime_manager, "REPO_ROOT", root):
                runtime_manager._ensure_managed_vae_path()
                runtime_manager._ensure_managed_vae_path()
            content = config.read_text(encoding="utf-8")
            self.assertIn("  loras: loras\n  vae: vae\nother:", content)
            self.assertIn("other:\n  vae: external", content)
            self.assertEqual(content.count("  vae: vae"), 1)

    def test_configured_log_directory_is_resolved_from_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "EVERSPARK_LOG_DIR=./private/logs\n", encoding="utf-8"
            )
            with (
                patch.object(runtime_manager, "REPO_ROOT", root),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(
                    runtime_manager._configured_log_dir(), root / "private" / "logs"
                )

    def test_external_healthy_process_is_never_claimed_or_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port = free_port()
            process = subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            definition = runtime_manager.ServiceDefinition(
                "external",
                ("bash", str(root / "unused.sh")),
                f"http://127.0.0.1:{port}/",
                "external.log",
                10,
            )
            try:
                for _ in range(50):
                    if runtime_manager._healthy(definition.health_url):
                        break
                    time.sleep(0.05)
                with (
                    patch.object(runtime_manager, "STATE_DIR", root / "state"),
                    patch.object(runtime_manager, "LOG_DIR", root / "logs"),
                ):
                    started = runtime_manager.start_service(definition)
                    self.assertEqual(started["state"], "external")
                    stopped = runtime_manager.stop_service(definition)
                    self.assertEqual(stopped["state"], "not-managed")
                    self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_managed_process_start_status_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "server.sh"
            port = free_port()
            script.write_text(
                "#!/usr/bin/env bash\n"
                f'exec "{sys.executable}" -m http.server {port} --bind 127.0.0.1\n',
                encoding="utf-8",
            )
            script.chmod(0o755)
            definition = runtime_manager.ServiceDefinition(
                "test", ("bash", str(script)), f"http://127.0.0.1:{port}/", "test.log", 10
            )
            with (
                patch.object(runtime_manager, "STATE_DIR", root / "state"),
                patch.object(runtime_manager, "LOG_DIR", root / "logs"),
            ):
                started = runtime_manager.start_service(definition)
                self.assertEqual(started["state"], "started")
                status = runtime_manager.service_status(definition)
                self.assertTrue(status["managed"])
                self.assertTrue(status["healthy"])
                stopped = runtime_manager.stop_service(definition)
                self.assertEqual(stopped["state"], "stopped")
                self.assertFalse(runtime_manager.service_status(definition)["managed"])

    def test_stale_pid_state_is_not_treated_as_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "state"
            state_dir.mkdir()
            with patch.object(runtime_manager, "STATE_DIR", state_dir):
                (state_dir / "test.json").write_text(
                    '{"service":"test","pid":999999,"start_ticks":"1","command":[]}\n',
                    encoding="utf-8",
                )
                state = runtime_manager._read_state("test")
                self.assertFalse(runtime_manager._state_is_live(state))


if __name__ == "__main__":
    unittest.main()
