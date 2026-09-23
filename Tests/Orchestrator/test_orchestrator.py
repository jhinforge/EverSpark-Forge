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
from concept_forge.subjects import CompiledSubject, new_subject  # noqa: E402
from image_forge.workflow.manager import WorkflowManager  # noqa: E402
from image_forge.models.resolver import (  # noqa: E402
    CheckpointResolutionError,
    resolve_checkpoint,
)
from orchestrator.config.config import load_config  # noqa: E402
from orchestrator.core.orchestrator import Orchestrator  # noqa: E402
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

    def test_checkpoint_binding_prefers_managed_default_and_warns(self) -> None:
        manager = WorkflowManager(
            {
                "template": "unused.json",
                "managed_default_checkpoint": "Illustrious-XL-v1.0.safetensors",
            }
        )
        workflow = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "private-model.safetensors"},
            }
        }
        notices = []
        manager.bind_checkpoint(
            workflow,
            ["z-last.ckpt", "Illustrious-XL-v1.0.safetensors"],
            notices.append,
        )
        self.assertEqual(
            workflow["4"]["inputs"]["ckpt_name"],
            "Illustrious-XL-v1.0.safetensors",
        )
        self.assertIn("managed default", notices[0])

    def test_checkpoint_resolution_uses_sorted_first_available(self) -> None:
        resolution = resolve_checkpoint(
            "missing.safetensors", ["Z.ckpt", "a.safetensors", "ignore.txt"]
        )
        self.assertEqual(resolution.name, "a.safetensors")
        self.assertEqual(resolution.source, "first_available")
        with self.assertRaises(CheckpointResolutionError):
            resolve_checkpoint("missing.safetensors", ["readme.txt"])

    def test_public_workflow_builds_with_managed_default_checkpoint(self) -> None:
        config = load_config()
        manager = WorkflowManager(config["workflow"])
        workflow = manager.build("positive", "negative", seed=1)
        self.assertEqual(workflow["34"]["inputs"]["text"], "positive")
        self.assertEqual(workflow["7"]["inputs"]["text"], "negative")
        self.assertEqual(workflow["31"]["inputs"]["seed"], 1)
        self.assertEqual(
            workflow["4"]["inputs"]["ckpt_name"],
            "Illustrious-XL-v1.0.safetensors",
        )

    def test_registry_and_standard_lora_injection_are_task_local(self) -> None:
        config = load_config()
        manager = WorkflowManager(config["workflow"])
        registered = manager.list_workflows()
        self.assertEqual(registered[0]["id"], "base-illustrious")
        self.assertTrue(registered[0]["supports"]["lora_injection"])

        workflow = manager.build(
            "positive", "negative", seed=9, workflow_id="base-illustrious"
        )
        selected = manager.inject_loras(
            workflow,
            [
                {
                    "name": "Characters/Hero.safetensors",
                    "strength_model": 0.8,
                    "strength_clip": 0.6,
                },
                {"name": "Style.safetensors"},
            ],
            ["characters/hero.safetensors", "Style.safetensors"],
            workflow_id="base-illustrious",
        )

        self.assertEqual(selected[0]["name"], "characters/hero.safetensors")
        self.assertEqual(workflow["35"]["inputs"]["model"], ["4", 0])
        self.assertEqual(workflow["36"]["inputs"]["model"], ["35", 0])
        self.assertEqual(workflow["31"]["inputs"]["model"], ["36", 0])
        self.assertEqual(workflow["34"]["inputs"]["clip"], ["36", 1])
        self.assertEqual(workflow["7"]["inputs"]["clip"], ["36", 1])
        self.assertEqual(workflow["8"]["inputs"]["vae"], ["4", 2])

        clean = manager.build(
            "next", "next negative", seed=10, workflow_id="base-illustrious"
        )
        self.assertNotIn("35", clean)
        self.assertEqual(clean["31"]["inputs"]["model"], ["4", 0])


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
            def selected_workflow_id(self, workflow_id=""):
                return workflow_id or "test-workflow"

            def build(self, positive, negative, seed, workflow_id=""):
                return {"positive": positive, "negative": negative, "seed": seed}

            def bind_checkpoint(
                self, _workflow, _available, _notify, requested=""
            ):
                return requested or "test.safetensors"

        class FakeImageForge:
            def __init__(self):
                self.workflows = []

            def list_checkpoints(self):
                return ["test.safetensors"]

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

        subject = CompiledSubject(
            "subject-a", 2, "silver hair, amber eyes", "different eye color"
        )
        result_with_subject = runner.run("森林场景", subject=subject)
        self.assertTrue(
            result_with_subject["positive_prompt"].startswith(
                "silver hair, amber eyes"
            )
        )
        self.assertTrue(
            result_with_subject["negative_prompt"].endswith("different eye color")
        )
        self.assertEqual(
            result_with_subject["subject"],
            {"subject_id": "subject-a", "revision": 2},
        )

    def test_manual_resource_selection_reaches_the_queued_workflow(self) -> None:
        class FakeConceptForge:
            model = "default-llm"
            selected_model = ""

            def list_models(self):
                return ["default-llm", "manual-llm"]

            def generate_prompt(self, _text, _history, model=""):
                self.selected_model = model
                return GenerationPlan(
                    "illustrious", "positive", "negative", 1, "over"
                )

        class FakeImageForge:
            workflow = None

            def list_checkpoints(self):
                return ["default.safetensors", "manual.safetensors"]

            def list_loras(self):
                return ["style.safetensors"]

            def queue_prompt(self, workflow):
                self.workflow = workflow
                return "prompt-selected"

        config = load_config()
        runner = TaskRunner.__new__(TaskRunner)
        runner.concept = FakeConceptForge()
        runner.workflow = WorkflowManager(config["workflow"])
        runner.image = FakeImageForge()
        runner.supported_models = {"illustrious"}
        runner.max_model_retries = 0
        runner.max_batch_size = 20

        result = runner.run(
            "portrait",
            selection={
                "workflow": "base-illustrious",
                "checkpoint": "manual.safetensors",
                "llm": "manual-llm",
                "loras": [
                    {
                        "name": "style.safetensors",
                        "strength_model": 0.75,
                        "strength_clip": 0.5,
                    }
                ],
            },
        )

        self.assertEqual(runner.concept.selected_model, "manual-llm")
        self.assertEqual(
            runner.image.workflow["4"]["inputs"]["ckpt_name"],
            "manual.safetensors",
        )
        self.assertEqual(runner.image.workflow["35"]["inputs"]["lora_name"], "style.safetensors")
        self.assertEqual(result["selection"]["workflow"], "base-illustrious")
        self.assertEqual(result["selection"]["checkpoint"], "manual.safetensors")


class SubjectIntegrationTests(unittest.TestCase):
    def test_generation_extracts_and_uses_the_session_subject_without_an_id(self) -> None:
        class FakeConceptForge:
            def generate_subject(
                self, _text, subject_id, existing=None, history=None, assistant_reply=""
            ):
                document = new_subject(subject_id, "Auto Character")
                document["appearance"]["hair"]["color"] = "silver"
                return document

            def generate_prompt(self, _text, _history):
                return GenerationPlan("illustrious", "rooftop", "low quality", 1, "over")

        class FakeWorkflow:
            def selected_workflow_id(self, workflow_id=""):
                return workflow_id or "test-workflow"

            def build(self, positive, negative, seed, workflow_id=""):
                return {"positive": positive, "negative": negative, "seed": seed}

            def bind_checkpoint(
                self, _workflow, _available, _notify, requested=""
            ):
                return requested or "test.safetensors"

        class FakeImageForge:
            def list_checkpoints(self):
                return ["test.safetensors"]

            def queue_prompt(self, _workflow):
                return "prompt-1"

        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "memory.db")
            orchestrator = Orchestrator(config)
            orchestrator.runner.concept = FakeConceptForge()
            orchestrator.runner.workflow = FakeWorkflow()
            orchestrator.runner.image = FakeImageForge()

            response = orchestrator.submit("Put her on a rooftop", "session-a")
            result = response["result"]
            current = orchestrator.get_session_subject("session-a")

            self.assertEqual(result["subject"]["subject_id"], current["subject_id"])
            self.assertIn("silver", result["positive_prompt"])

    def test_discussion_automatically_maintains_one_subject_per_session(self) -> None:
        class FakeConceptForge:
            histories = []

            def discuss(self, text, history):
                self.histories.append(history)
                return f"Understood: {text}"

            def generate_subject(
                self, text, subject_id, existing=None, history=None, assistant_reply=""
            ):
                document = (
                    json.loads(json.dumps(existing))
                    if existing is not None
                    else new_subject(subject_id, "Current Character")
                )
                if existing is not None:
                    document["revision"] += 1
                if "silver" in text:
                    document["appearance"]["hair"]["color"] = "silver"
                return document

        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "memory.db")
            orchestrator = Orchestrator(config)
            concept = FakeConceptForge()
            orchestrator.runner.concept = concept

            first = orchestrator.discuss("She has silver hair", "session-a")
            second = orchestrator.discuss("Keep that design", "session-a")

            self.assertEqual(
                first["subject"]["subject_id"], second["subject"]["subject_id"]
            )
            self.assertEqual(second["subject"]["revision"], 1)
            self.assertEqual(second["subject"]["appearance"]["hair"]["color"], "silver")
            self.assertEqual(len(concept.histories[1]), 2)
            self.assertEqual(
                orchestrator.get_session_subject("session-a")["subject_id"],
                first["subject"]["subject_id"],
            )

    def test_orchestrator_persists_updates_and_compiles_subjects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "memory.db")
            orchestrator = Orchestrator(config)
            document = new_subject("subject-a", "Subject A")
            document["appearance"]["hair"] = {
                "color": "silver",
                "length": "long",
                "style": "straight hair",
            }
            orchestrator.save_subject(document)
            updated = orchestrator.update_subject(
                "subject-a", {"appearance": {"face": {"eye_color": "amber"}}}
            )
            self.assertEqual(updated["revision"], 2)
            compiled = orchestrator.compile_subject("subject-a")
            self.assertIn("silver", compiled["positive_prompt"])
            self.assertIn("amber", compiled["positive_prompt"])
            self.assertEqual(
                [item["revision"] for item in orchestrator.get_subject_revisions("subject-a")],
                [2, 1],
            )
            self.assertEqual(
                [
                    item["revision"]
                    for item in orchestrator.get_subject_revisions("  subject-a  ")
                ],
                [2, 1],
            )


class APITests(unittest.TestCase):
    class FakeOrchestrator:
        def __init__(self):
            self.cleared = None
            self.document = new_subject("subject-a", "Subject A")

        def get_history(self, session_id):
            return [{"role": "user", "content": session_id}]

        def clear_memory(self, session_id):
            self.cleared = session_id

        def discuss(self, text, session_id, selection=None):
            return {
                "ok": True,
                "reply": f"reply:{text}",
                "session_id": session_id,
                "subject": self.document,
            }

        def get_session_subject(self, _session_id):
            return self.document

        def submit(self, text, session_id, selection=None):
            return {
                "ok": True,
                "text": text,
                "session_id": session_id,
                "selection": selection,
            }

        def resources(self):
            return {
                "workflows": [],
                "checkpoints": [],
                "loras": [],
                "llms": [],
                "defaults": {},
            }

        def storage_resources(self):
            return {
                "enabled": True,
                "backend": "rclone",
                "image": {"checkpoint": [], "diffusion_model": [], "lora": []},
                "concept": {"models": []},
            }

        def start_storage_pull(self, kind, name):
            return {"job_id": "job-1", "kind": kind, "name": name, "status": "queued"}

        def storage_job(self, job_id=""):
            return {"job_id": job_id or "job-1", "status": "completed"}

        def backup_resources(self):
            return {"enabled": True, "files": [{"name": "outputs/a.png", "bytes": 3}], "memory": True}

        def start_backup(self, names, memory=False):
            return {"job_id": "backup-1", "names": names, "memory": memory, "status": "queued"}

        def backup_job(self, job_id=""):
            return {"job_id": job_id or "backup-1", "status": "completed"}

        def start_download(self, kind, url, filename="", runtime_name=""):
            return {
                "job_id": "download-1",
                "kind": kind,
                "source": url,
                "name": filename,
                "runtime_name": runtime_name,
                "status": "queued",
            }

        def download_job(self, job_id=""):
            return {"job_id": job_id or "download-1", "status": "completed"}

        def cancel_download(self, job_id):
            return {"job_id": job_id, "status": "downloading"}

        def retry_download(self, _job_id):
            return {"job_id": "download-2", "status": "queued"}

        def save_subject(self, document):
            self.document = document
            return document

        def generate_subject(self, subject_id, _text):
            self.document = new_subject(subject_id, "Generated Subject")
            return self.document

        def update_subject(self, _subject_id, changes):
            self.document["identity"].update(changes.get("identity", {}))
            self.document["revision"] += 1
            return self.document

        def compile_subject(self, subject_id):
            return {
                "subject_id": subject_id,
                "revision": self.document["revision"],
                "positive_prompt": "subject prompt",
                "negative_prompt": "subject negative",
            }

        def get_subject(self, _subject_id):
            return self.document

        def list_subjects(self):
            return [{"subject_id": self.document["subject_id"]}]

        def get_subject_revisions(self, _subject_id):
            return [{"revision": self.document["revision"]}]

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

        status, discussed = self._request(
            "/conversation", {"session_id": "session-a", "text": "hello"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(discussed["reply"], "reply:hello")

        status, current = self._request(
            f"/subjects/current?{urlencode({'session_id': 'session-a'})}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(current["document"]["subject_id"], "subject-a")

    def test_storage_routes_use_the_infrastructure_boundary(self) -> None:
        status, resources = self._request("/storage/resources")
        self.assertEqual(status, 200)
        self.assertTrue(resources["enabled"])
        status, started = self._request(
            "/storage/pull", {"kind": "lora", "name": "style.safetensors"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(started["job"]["kind"], "lora")
        status, job = self._request("/storage/jobs?job_id=job-1")
        self.assertEqual(status, 200)
        self.assertEqual(job["job"]["status"], "completed")

    def test_backup_routes_use_the_infrastructure_boundary(self) -> None:
        status, resources = self._request("/backup/resources")
        self.assertEqual(status, 200)
        self.assertEqual(resources["files"][0]["name"], "outputs/a.png")
        status, started = self._request(
            "/backup/upload", {"names": ["outputs/a.png"], "memory": True}
        )
        self.assertEqual(status, 202)
        self.assertTrue(started["job"]["memory"])
        status, job = self._request("/backup/jobs?job_id=backup-1")
        self.assertEqual(status, 200)
        self.assertEqual(job["job"]["status"], "completed")

    def test_direct_download_routes_use_the_infrastructure_boundary(self) -> None:
        status, started = self._request(
            "/downloads",
            {
                "kind": "concept_model",
                "url": "https://models.example/model.gguf",
                "filename": "model.gguf",
                "runtime_name": "model-a",
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(started["job"]["runtime_name"], "model-a")
        status, job = self._request("/downloads/jobs?job_id=download-1")
        self.assertEqual(status, 200)
        self.assertEqual(job["job"]["status"], "completed")
        status, cancelled = self._request(
            "/downloads/cancel", {"job_id": "download-1"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(cancelled["job"]["job_id"], "download-1")
        status, retried = self._request(
            "/downloads/retry", {"job_id": "download-1"}
        )
        self.assertEqual(status, 202)
        self.assertEqual(retried["job"]["job_id"], "download-2")

    def test_subject_create_update_compile_and_read_routes(self) -> None:
        document = new_subject("subject-a", "Subject A")
        status, created = self._request("/subjects", {"document": document})
        self.assertEqual(status, 201)
        self.assertEqual(created["document"]["subject_id"], "subject-a")

        status, listed = self._request("/subjects")
        self.assertEqual(status, 200)
        self.assertEqual(listed["subjects"][0]["subject_id"], "subject-a")

        query = urlencode({"subject_id": "subject-a"})
        status, fetched = self._request(f"/subjects?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["document"]["identity"]["display_name"], "Subject A")

        status, updated = self._request(
            "/subjects/update",
            {
                "subject_id": "subject-a",
                "changes": {"identity": {"display_name": "Updated Subject"}},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["document"]["revision"], 2)

        status, compiled = self._request(
            "/subjects/compile", {"subject_id": "subject-a"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(compiled["positive_prompt"], "subject prompt")

        status, generated = self._request(
            "/subjects/generate",
            {"subject_id": "generated-a", "text": "Create a character"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(generated["document"]["subject_id"], "generated-a")


if __name__ == "__main__":
    unittest.main()
