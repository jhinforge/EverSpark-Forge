from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
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
from image_forge.workflow.manager import WorkflowManager, WorkflowError  # noqa: E402
from image_forge.adapters.comfyui import ComfyUIAdapter  # noqa: E402
from image_forge.adapters.diffusers import DiffusersAdapter  # noqa: E402
from image_forge.models.resolver import (  # noqa: E402
    CheckpointResolutionError,
    resolve_checkpoint,
)
from orchestrator.config.config import load_config  # noqa: E402
from orchestrator.core.orchestrator import Orchestrator  # noqa: E402
from orchestrator.core.server import OrchestratorServer  # noqa: E402
from orchestrator.core.task_runner import TaskRunner  # noqa: E402


class FakeGateway:
    """Capture normalized image requests without starting a model runtime."""

    def __init__(self, runner):
        self.runner = runner
        self.requests = []

    def select(self, name=""):
        return type("SelectedEngine", (), {"name": name or "comfyui", "health": lambda self: True})()

    def submit(self, request, notify=None, engine=""):
        self.requests.append(request)
        workflow = self.runner.workflow.build(
            request.positive_prompt, request.negative_prompt,
            seed=request.seed, workflow_id=request.workflow)
        checkpoint = self.runner.workflow.bind_checkpoint(
            workflow, self.runner.image.list_checkpoints(), notify,
            requested=request.checkpoint)
        loras = (self.runner.workflow.inject_loras(
            workflow, request.loras, self.runner.image.list_loras(),
            workflow_id=request.workflow) if request.loras else [])
        identifier = self.runner.image.queue_prompt(workflow)
        return identifier, {"workflow": request.workflow or "test-workflow",
                            "checkpoint": checkpoint, "vae": "", "loras": loras}
from orchestrator.core.text import normalize_unicode  # noqa: E402


class UnicodeTests(unittest.TestCase):
    def test_surrogate_pair_is_repaired(self) -> None:
        broken = "红头发\ud83d\ude00女孩"
        repaired = normalize_unicode(broken)
        self.assertEqual(repaired, "红头发😀女孩")
        repaired.encode("utf-8")


class ConfigurationTests(unittest.TestCase):
    def test_existing_config_can_select_diffusers_without_new_adapter_section(self) -> None:
        config_path = REPO_ROOT / "Orchestrator/orchestrator/config/default_config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["image_forge"]["adapters"].pop("diffusers")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch.dict(os.environ, {"EVERSPARK_IMAGE_BACKEND": "diffusers"}):
                config = load_config(path)
        self.assertEqual(config["image_forge"]["adapter"], "diffusers")
        self.assertIn("diffusers", config["image_forge"]["adapters"])

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
    def test_selected_vae_replaces_checkpoint_decode_link_only(self) -> None:
        config = load_config()
        manager = WorkflowManager(config["workflow"])
        workflow = manager.build("portrait", "bad", workflow_id=manager.default_workflow_id)
        self.assertEqual(workflow["8"]["inputs"]["vae"], ["4", 2])
        self.assertEqual(manager.bind_vae(workflow, "Custom.safetensors", ["custom.safetensors"]), "custom.safetensors")
        vae_link = workflow["8"]["inputs"]["vae"]
        self.assertEqual(workflow[vae_link[0]]["class_type"], "VAELoader")
        self.assertEqual(workflow[vae_link[0]]["inputs"]["vae_name"], "custom.safetensors")
        self.assertEqual(workflow["31"]["inputs"]["model"], ["4", 0])
        self.assertEqual(workflow["34"]["inputs"]["clip"], ["4", 1])
        with self.assertRaisesRegex(WorkflowError, "unavailable"):
            manager.bind_vae(workflow, "missing.safetensors", ["custom.safetensors"])

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
        self.assertIn("bad anatomy", manager.default_negative_prompt("base-illustrious"))
        self.assertIn("lowres", ComfyUIAdapter({"base_url": "http://127.0.0.1:8188"}, manager)
                      .default_negative_prompt("base-illustrious"))
        self.assertIn("bad anatomy", DiffusersAdapter({}).default_negative_prompt())
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
    def test_selected_diffusers_engine_seeds_first_negative_prompt(self) -> None:
        class Concept:
            model = "test-llm"

            def generate_prompt(self, _text, _history):
                return GenerationPlan("illustrious", "portrait", "bad anatomy, blurred", 1, "over")

        class Gateway:
            def __init__(self):
                self.requests = []

            def select(self, name=""):
                return DiffusersAdapter({}) if name == "diffusers" else None

            def submit(self, request, notify=None, engine=""):
                self.requests.append((engine, request))
                return "job", {"workflow": "diffusers-sdxl", "checkpoint": "test.safetensors",
                               "vae": "", "loras": []}

        runner = TaskRunner.__new__(TaskRunner)
        runner.concept = Concept()
        runner.gateway = Gateway()
        runner.supported_models = {"illustrious"}
        runner.max_model_retries = 0
        runner.max_batch_size = 4
        result = runner.run("portrait", selection={"engine": "diffusers",
                                                  "workflow": "diffusers-sdxl"})
        self.assertEqual(result["negative_prompt"].count("bad anatomy"), 1)
        self.assertIn("watermark", result["negative_prompt"])
        self.assertTrue(result["negative_prompt"].endswith("blurred"))
        self.assertEqual(runner.gateway.requests[0][0], "diffusers")
        self.assertEqual(runner.gateway.requests[0][1].negative_prompt, result["negative_prompt"])

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
        runner.gateway = FakeGateway(runner)
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
        runner.gateway = FakeGateway(runner)
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
    def test_selected_existing_character_is_used_by_generation_and_persists(self) -> None:
        class Concept:
            def generate_subject(self, _text, subject_id, existing=None, **_kwargs):
                self.assert_existing = existing is not None
                document = json.loads(json.dumps(existing))
                document["revision"] += 1
                return document

            def generate_prompt(self, _text, _history):
                return GenerationPlan("illustrious", "rooftop", "bad quality", 1, "over")

        class Workflow:
            def selected_workflow_id(self, _id=""):
                return "test"

            def build(self, positive, negative, **_kwargs):
                return {"positive": positive, "negative": negative}

            def bind_checkpoint(self, *_args, **_kwargs):
                return "test.safetensors"

        class Image:
            def list_checkpoints(self):
                return ["test.safetensors"]

            def queue_prompt(self, _workflow):
                return "queued"

        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "memory.db")
            orchestrator = Orchestrator(config)
            subject = new_subject("old-character", "Old Character")
            subject["appearance"]["hair"]["color"] = "silver"
            orchestrator.save_subject(subject)
            orchestrator.save_subject(new_subject("other-character", "Other Character"))
            orchestrator.select_session_subject("old-session", "old-character")
            orchestrator.memory.record_conversation("new-session", "hello", "hi")
            orchestrator.select_session_subject("new-session", "old-character")
            self.assertEqual(orchestrator.get_history("new-session")[0]["content"], "hello")
            self.assertEqual(orchestrator.get_session_subject("old-session")["subject_id"], "old-character")
            self.assertEqual(orchestrator.get_session_subject("new-session")["subject_id"], "old-character")
            with self.assertRaisesRegex(ValueError, "session_id"):
                orchestrator.select_session_subject("", "old-character")
            with self.assertRaisesRegex(Exception, "Subject not found"):
                orchestrator.select_session_subject("new-session", "missing")
            self.assertEqual(orchestrator.get_session_subject("new-session")["subject_id"], "old-character")

            concept = Concept()
            orchestrator.runner.concept = concept
            orchestrator.runner.workflow = Workflow()
            orchestrator.runner.image = Image()
            orchestrator.runner.gateway = FakeGateway(orchestrator.runner)
            result = orchestrator.submit("Place her on a rooftop", "new-session")["result"]
            self.assertTrue(concept.assert_existing)
            self.assertEqual(result["subject"]["subject_id"], "old-character")
            self.assertIn("silver", result["positive_prompt"])
            self.assertEqual(orchestrator.get_session_subject("old-session")["subject_id"], "old-character")
            orchestrator.select_session_subject("new-session", "other-character")
            self.assertEqual(orchestrator.get_session_subject("new-session")["subject_id"], "other-character")

    def test_group_revisions_target_one_document_without_switching_session(self) -> None:
        class FakeConcept:
            def revise_subject_section(self, _text, group, existing):
                result = json.loads(json.dumps(existing))
                result["revision"] += 1
                if group == "metadata":
                    result["metadata"]["notes"] = "new note"
                return result

            def revise_prompt(self, _text, field, _current):
                return "revised " + field

        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "memory.db")
            orchestrator = Orchestrator(config)
            orchestrator.runner.concept = FakeConcept()
            initial = new_subject("subject-a", "Subject A")
            orchestrator.save_subject(initial)
            metadata = orchestrator.revise_subject_group("subject-a", "metadata", "add a note")
            self.assertEqual(metadata["metadata"]["notes"], "new note")
            self.assertEqual(metadata["subject"]["appearance"]["hair"]["color"], "")
            changed = orchestrator.revise_subject_group("subject-a", "positive_prompt", "improve quality")
            self.assertEqual(changed["positive_prompt"]["positive_prompt"], "revised positive_prompt")
            self.assertEqual(changed["negative_prompt"]["negative_prompt"], "")
            self.assertEqual(orchestrator.get_subject("subject-a")["revision"], 2)

    def test_negative_prompt_stays_at_first_generation_until_explicit_change(self) -> None:
        class Concept:
            def __init__(self):
                self.index = 0
                self.histories = []

            def generate_subject(self, _text, subject_id, existing=None, **_kwargs):
                document = new_subject(subject_id, "Character") if existing is None else existing.copy()
                if existing is not None:
                    document["revision"] += 1
                return document

            def generate_prompt(self, _text, _history):
                self.index += 1
                self.histories.append(_history)
                return GenerationPlan("illustrious", "portrait", f"bad anatomy, negative-{self.index}", 1, "over")

        class Workflow:
            def selected_workflow_id(self, _id=""):
                return "test"

            def default_negative_prompt(self, _id=""):
                return "lowres, bad anatomy, lowres"

            def build(self, positive, negative, **_kwargs):
                return {"positive": positive, "negative": negative}

            def bind_checkpoint(self, *_args, **_kwargs):
                return "test.safetensors"

        class Image:
            def list_checkpoints(self):
                return ["test.safetensors"]

            def queue_prompt(self, _workflow):
                return "queued"

        with tempfile.TemporaryDirectory() as directory:
            config = load_config()
            config["memory"]["database"] = str(Path(directory) / "memory.db")
            orchestrator = Orchestrator(config)
            orchestrator.runner.concept = Concept()
            orchestrator.runner.workflow = Workflow()
            orchestrator.runner.image = Image()
            class DefaultGateway(FakeGateway):
                def select(self, name=""):
                    engine = super().select(name)
                    engine.default_negative_prompt = orchestrator.runner.workflow.default_negative_prompt
                    return engine

            orchestrator.runner.gateway = DefaultGateway(orchestrator.runner)
            first = orchestrator.submit("画一个角色", "session")["result"]
            second = orchestrator.submit("改变背景", "session")["result"]
            third = orchestrator.submit("修改负面提示词", "session")["result"]
            self.assertEqual(first["negative_prompt"], "lowres, bad anatomy, negative-1")
            self.assertEqual(second["negative_prompt"], "lowres, bad anatomy, negative-1")
            self.assertEqual(third["negative_prompt"], "bad anatomy, negative-3")
            explicit_first = orchestrator.submit("修改负面提示词", "new-session")["result"]
            self.assertEqual(explicit_first["negative_prompt"], "bad anatomy, negative-4")
            self.assertIn("portrait", orchestrator.runner.concept.histories[1][-1]["content"])
            self.assertEqual(orchestrator.memory.get_subject_prompt(
                orchestrator.get_session_subject("session")["subject_id"]
            )["negative_prompt"], "bad anatomy, negative-3")

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
            orchestrator.runner.gateway = FakeGateway(orchestrator.runner)

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
            self._task_jobs_lock = threading.Lock()
            self._task_jobs = {}
            self.task_gate = None
            self.submit_calls = 0
            self._connection_test_lock = threading.Lock()
            self._connection_test_jobs = {}
            self.connection_gate = None

        start_task = Orchestrator.start_task
        task_job = Orchestrator.task_job
        _execute_task = Orchestrator._execute_task
        start_concept_connection_test = Orchestrator.start_concept_connection_test
        _run_concept_connection_test = Orchestrator._run_concept_connection_test
        concept_connection_test_job = Orchestrator.concept_connection_test_job

        def get_history(self, session_id):
            return [{"role": "user", "content": session_id}]

        def clear_memory(self, session_id):
            self.cleared = session_id

        def concept_connections(self):
            return {"default": "ollama", "connections": [{"id": "ollama", "model": "local"}]}

        def save_concept_connection(self, payload):
            self.saved_connection = payload
            return {"default": "ollama", "connections": [{"id": "api_test", "model": payload["model"]}]}

        def test_concept_connection(self, payload):
            if self.connection_gate is not None:
                self.connection_gate.wait(2)
            return {"model": payload["model"], "connected": True}

        def remove_concept_connection(self, identifier):
            return {"default": "ollama", "connections": [], "removed": identifier}

        def default_concept_connection(self, identifier):
            return {"default": identifier, "connections": []}

        def discuss(self, text, session_id, selection=None):
            return {
                "ok": True,
                "reply": f"reply:{text}",
                "session_id": session_id,
                "subject": self.document,
            }

        def get_session_subject(self, _session_id):
            return self.document

        def select_session_subject(self, session_id, subject_id):
            self.selected = (session_id, subject_id)
            return self.document

        def submit(self, text, session_id, selection=None):
            self.submit_calls += 1
            if self.task_gate is not None:
                self.task_gate.wait(2)
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

        def storage_scan(self):
            return {"status": "completed", "error": "", "result": self.storage_resources()}

        def start_storage_scan(self):
            return {"status": "running", "error": "", "result": None}

        def start_storage_pull(self, kind, name):
            return {"job_id": "job-1", "kind": kind, "name": name, "status": "queued"}

        def storage_job(self, job_id=""):
            return {"job_id": job_id or "job-1", "status": "completed"}

        def backup_resources(self):
            return {"enabled": True, "files": [{"name": "outputs/a.png", "bytes": 3}], "memory": True}

        def start_backup(self, names, memory=False, targets=None, outputs=False):
            return {"job_id": "backup-1", "names": names, "memory": memory,
                    "outputs": outputs, "targets": targets, "status": "queued"}

        def save_storage_paths(self, mapping):
            return mapping

        def restore_points(self):
            return [{"id": "a" * 32, "files": 5, "subjects": 1}]

        def start_restore(self, batch_id):
            return {"job_id": "restore-1", "id": batch_id, "status": "queued"}

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

        def subject_bundle(self, subject_id):
            return {"subject_id": subject_id, "subject": self.document,
                    "metadata": self.document["metadata"],
                    "positive_prompt": {"positive_prompt": "portrait"},
                    "negative_prompt": {"negative_prompt": "bad anatomy"}}

        def revise_subject_group(self, subject_id, group, instruction):
            result = self.subject_bundle(subject_id)
            result[group] = {"positive_prompt": instruction}
            return result

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

    def test_generation_returns_job_before_work_finishes_and_retries_are_idempotent(self) -> None:
        self.fake.task_gate = threading.Event()
        request = {"text": "red dress", "session_id": "session-a",
                   "request_id": "a" * 32, "selection": {"engine": "diffusers"}}
        start = time.monotonic()
        status, accepted = self._request("/tasks/start", request)
        self.assertEqual(status, 202)
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(accepted["job"]["id"], request["request_id"])
        _, repeated = self._request("/tasks/start", request)
        self.assertEqual(repeated["job"]["id"], accepted["job"]["id"])
        _, pending = self._request("/tasks/jobs?job_id=" + request["request_id"])
        self.assertIn(pending["job"]["status"], ("queued", "running"))
        self.fake.task_gate.set()
        for _ in range(100):
            _, completed = self._request("/tasks/jobs?job_id=" + request["request_id"])
            if completed["job"]["status"] == "completed":
                break
            time.sleep(.01)
        self.assertEqual(completed["job"]["response"]["text"], "red dress")
        self.assertEqual(self.fake.submit_calls, 1)

    def test_concept_connection_routes_hide_the_key(self) -> None:
        status, listed = self._request("/concept/connections")
        self.assertEqual(status, 200)
        self.assertEqual(listed["default"], "ollama")
        payload = {"name": "Test", "base_url": "https://example.test/v1",
                   "api_key": "secret-key", "model": "actual-id"}
        status, tested = self._request("/concept/connections/test", payload)
        self.assertEqual(status, 202)
        job_id = tested["job"]["id"]
        for _ in range(100):
            _, test_job = self._request("/concept/connections/test/jobs?job_id=" + job_id)
            if test_job["job"]["status"] == "completed":
                break
            time.sleep(.01)
        self.assertTrue(test_job["job"]["result"]["connected"])
        self.assertNotIn("secret-key", json.dumps(test_job))
        _, saved = self._request("/concept/connections/save", payload)
        self.assertEqual(saved["connections"][0]["model"], "actual-id")
        self.assertNotIn("secret-key", json.dumps(saved))
        self.assertEqual(self.fake.saved_connection["api_key"], "secret-key")
        _, activated = self._request("/concept/connections/default", {"id": "api_test"})
        self.assertEqual(activated["default"], "api_test")
        _, removed = self._request("/concept/connections/remove", {"id": "api_test"})
        self.assertEqual(removed["removed"], "api_test")

    def test_slow_connection_test_returns_a_job_without_exposing_credentials(self) -> None:
        self.fake.connection_gate = threading.Event()
        payload = {"name": "Slow", "base_url": "https://example.test/v1",
                   "api_key": "private-key", "model": "slow-model"}
        started_at = time.monotonic()
        status, started = self._request("/concept/connections/test", payload)
        self.assertEqual(status, 202)
        self.assertLess(time.monotonic() - started_at, 1)
        self.assertNotIn("private-key", json.dumps(started))
        job_id = started["job"]["id"]
        _, pending = self._request("/concept/connections/test/jobs?job_id=" + job_id)
        self.assertEqual(pending["job"]["status"], "running")
        self.fake.connection_gate.set()
        for _ in range(100):
            _, completed = self._request("/concept/connections/test/jobs?job_id=" + job_id)
            if completed["job"]["status"] == "completed":
                break
            time.sleep(.01)
        self.assertTrue(completed["job"]["result"]["connected"])
        self.assertNotIn("private-key", json.dumps(completed))

    def test_storage_routes_use_the_infrastructure_boundary(self) -> None:
        status, scan = self._request("/storage/scan")
        self.assertEqual(status, 200)
        self.assertEqual(scan["status"], "completed")
        status, queued = self._request("/storage/scan", {})
        self.assertEqual(status, 202)
        self.assertEqual(queued["status"], "running")
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

    def test_subject_bundle_and_model_revision_routes(self) -> None:
        status, selected = self._request("/subjects/select", {
            "session_id": "new-session", "subject_id": "subject-a",
        })
        self.assertEqual(status, 200)
        self.assertEqual(selected["document"]["subject_id"], "subject-a")
        self.assertEqual(self.fake.selected, ("new-session", "subject-a"))
        status, bundle = self._request("/subjects/bundle?subject_id=subject-a")
        self.assertEqual(status, 200)
        self.assertEqual(bundle["bundle"]["negative_prompt"]["negative_prompt"], "bad anatomy")
        status, updated = self._request("/subjects/revise", {
            "subject_id": "subject-a", "group": "positive_prompt", "instruction": "add lighting",
        })
        self.assertEqual(status, 200)
        self.assertEqual(updated["bundle"]["positive_prompt"]["positive_prompt"], "add lighting")

    def test_backup_routes_use_the_infrastructure_boundary(self) -> None:
        status, resources = self._request("/backup/resources")
        self.assertEqual(status, 200)
        self.assertEqual(resources["files"][0]["name"], "outputs/a.png")
        status, started = self._request(
            "/backup/upload", {"names": ["outputs/a.png"], "memory": True}
        )
        self.assertEqual(status, 202)
        self.assertTrue(started["job"]["memory"])
        _, output_job = self._request("/backup/upload", {"names": [], "outputs": True})
        self.assertTrue(output_job["job"]["outputs"])
        status, job = self._request("/backup/jobs?job_id=backup-1")
        self.assertEqual(status, 200)
        self.assertEqual(job["job"]["status"], "completed")
        status, paths = self._request("/storage/paths", {"paths": {"concept_manual": ["r:models"]}})
        self.assertEqual(status, 200)
        self.assertEqual(paths["paths"]["concept_manual"], ["r:models"])
        status, points = self._request("/backup/restore-points")
        self.assertEqual(status, 200)
        self.assertEqual(points["points"][0]["subjects"], 1)
        status, restore = self._request("/backup/restore", {"id": "a" * 32})
        self.assertEqual(status, 202)
        self.assertEqual(restore["job"]["status"], "queued")

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
