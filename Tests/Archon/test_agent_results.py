"""Verbose installation diagnostics must not corrupt task outcomes."""
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from Legate.Envoy.executor.tasks import execute
from Legate.Envoy.executor.journal import execute_once


class AgentResultTests(unittest.TestCase):
    def command(self, action, output, code=0, error="", forge="image"):
        with patch("Legate.Envoy.executor.tasks.subprocess.run", return_value=
                   CompletedProcess([], code, output, error)):
            return execute(action, "{}", forge)

    def test_successful_verbose_image_deployment_remains_successful(self):
        output = "install progress\n" * 10000 + "Image Forge ready\n"
        result = self.command("deploy", output)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["output"].endswith("Image Forge ready\n"))
        self.assertLessEqual(len(result["output"].encode()), 60000)

    def test_failed_verbose_deployment_preserves_real_error_and_exit_code(self):
        result = self.command("deploy", "", 7, "error\n" * 15000 + "Download failed")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)
        self.assertTrue(result["output"].endswith("Download failed"))

    def test_image_json_is_not_truncated(self):
        payload = json.dumps({"resources": ["model" * 2000]})
        self.assertEqual(self.command("resources", payload)["output"], payload)

    def test_oversized_image_data_and_concept_chat_still_fail(self):
        for forge, action in (("image", "resources"), ("concept", "chat")):
            with self.subTest(forge=forge):
                result = self.command(action, "x" * 60001, forge=forge)
                # Concept chat command requires a valid message envelope.
                if forge == "concept":
                    with patch("Legate.Envoy.executor.tasks.subprocess.run", return_value=
                               CompletedProcess([], 0, "x" * 60001, "")):
                        result = execute("chat", json.dumps({"messages": [], "model": "test", "json_mode": False}), forge)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["output"], "Forge response exceeds node task limit")

    def test_multibyte_diagnostics_and_journal_replay_fit_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            task = {"id": "a" * 32, "forge": "image", "action": "deploy", "message": ""}
            output = "安装进度\n" * 20000 + "Image Forge ready"
            with patch("Legate.Envoy.executor.tasks.subprocess.run", return_value=
                       CompletedProcess([], 0, output, "")) as run:
                journal = Path(directory) / "tasks.json"
                first = execute_once(task, journal)
                self.assertEqual(execute_once(task, journal), first)
                run.assert_called_once()
            self.assertEqual(first["status"], "completed")
            self.assertLessEqual(len(first["output"].encode()), 60000)
