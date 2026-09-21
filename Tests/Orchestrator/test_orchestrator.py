from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
for module_directory in (
    "Orchestrator",
    "ConceptForge",
    "ImageForge",
    "Memory",
    "Runtime/Logging",
):
    sys.path.insert(0, str(REPO_ROOT / module_directory))

from concept_forge.providers.ollama import GenerationPlan  # noqa: E402
from image_forge.workflow.manager import WorkflowError, WorkflowManager  # noqa: E402
from orchestrator.config.config import load_config  # noqa: E402
from orchestrator.core.server import OrchestratorServer  # noqa: E402
from orchestrator.core.task_runner import TaskRunner  # noqa: E402
from orchestrator.core.text import normalize_unicode  # noqa: E402


class UnicodeTests(unittest.TestCase):
    def test_surrogate_pair_is_repaired(self) -> None:
        broken = "红头发\ud83d\ude00女孩"
        repaired = normalize_unicode(broken)
        self.assertEqual(repaired, "红头发😀女孩")
        repaired.encode("utf-8")


class ConfigurationTests(unittest.TestCase):
    def test_local_paths_and_environment_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EVERSPARK_ORCHESTRATOR_PORT": "9876",
                "OLLAMA_MODEL": "test-model",
            },
            clear=True,
        ):
            config = load_config()
        self.assertEqual(config["orchestrator"]["port"], 9876)
        self.assertEqual(
            config["concept_forge"]["providers"]["ollama"]["model"],
            "test-model",
        )
        self.assertEqual(
            Path(config["memory"]["database"]),
            REPO_ROOT / "Data" / "Memory" / "everspark.db",
        )


class WorkflowTests(unittest.TestCase):
    def test_prompts_and_seed_are_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "7": {"inputs": {"text": "old negative"}},
                        "12": {"inputs": {"text": "old positive"}},
                        "31": {"inputs": {"seed": 1}},
                    }
                ),
                encoding="utf-8",
            )
            manager = WorkflowManager(
                {
                    "template": str(path),
                    "positive_prompt_node": "12",
                    "negative_prompt_node": "7",
                    "seed_node": "31",
                }
            )
            workflow = manager.build("red hair", "bad quality", seed=12345)
            self.assertEqual(workflow["12"]["inputs"]["text"], "red hair")
            self.assertEqual(workflow["7"]["inputs"]["text"], "bad quality")
            self.assertEqual(workflow["31"]["inputs"]["seed"], 12345)

    def test_public_workflow_is_an_unconfigured_placeholder(self) -> None:
        config = load_config()
        manager = WorkflowManager(config["workflow"])
        with self.assertRaisesRegex(WorkflowError, "empty placeholder"):
            manager.build("positive", "negative", seed=1)


class BatchTests(unittest.TestCase):
    def test_batch_queues_unique_workflows_and_passes_history(self) -> None:
        class FakeConceptForge:
            received_history = None

            def generate_prompt(self, _text, history):
                self.received_history = history
                return GenerationPlan(
                    "illustrious", "positive", "negative", 3, "over"
                )

        class FakeWorkflow:
            def build(self, positive, negative, seed):
                return {"positive": positive, "negative": negative, "seed": seed}

        class FakeImageForge:
            def __init__(self):
                self.workflows = []

            def queue_prompt(self, workflow):
                self.workflows.append(workflow)
                return f"prompt-{len(self.workflows)}"

        runner = TaskRunner.__new__(TaskRunner)
        runner.concept = FakeConceptForge()
        runner.workflow = FakeWorkflow()
        runner.image = FakeImageForge()
        runner.supported_models = {"illustrious"}
        runner.max_model_retries = 3
        runner.max_batch_size = 20
        history = [{"role": "user", "content": "上一张是红头发"}]

        result = runner.run("改成蓝头发，再来三张", history=history)

        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(runner.concept.received_history, history)
        seeds = {item["seed"] for item in result["items"]}
        self.assertEqual(len(seeds), 3)


class APITests(unittest.TestCase):
    class FakeOrchestrator:
        def __init__(self):
            self.cleared = None

        def get_history(self, session_id):
            return [{"role": "user", "content": session_id}]

        def clear_memory(self, session_id):
            self.cleared = session_id

        def submit(self, text, session_id):
            return {"ok": True, "text": text, "session_id": session_id}

    def setUp(self) -> None:
        self.fake = self.FakeOrchestrator()
        self.server = OrchestratorServer(("127.0.0.1", 0), self.fake)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(self, path: str, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=data, headers=headers)
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())

    def test_memory_routes_use_the_new_boundary(self) -> None:
        query = urlencode({"session_id": "session-a"})
        status, history = self._request(f"/memory/history?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(history["messages"][0]["content"], "session-a")

        status, cleared = self._request(
            "/memory/clear", {"session_id": "session-a"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(cleared["session_id"], "session-a")
        self.assertEqual(self.fake.cleared, "session-a")

        with self.assertRaises(HTTPError) as caught:
            self._request(f"/context/history?{query}")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
