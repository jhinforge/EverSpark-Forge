"""Ownership and cross-module regressions for the existing generation pipeline."""
import ast
import inspect
import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
for relative in ("", "Archon/Orchestrator", "Legate/Forge", "Legate/Forge/ConceptForge",
                 "Legate/Forge/ConceptForge/Memory", "Legate/Forge/ImageForge"):
    sys.path.insert(0, str(ROOT / relative))
from orchestrator.core.orchestrator import Orchestrator
from orchestrator.core.task_runner import TaskRunner
from Archon.Vault.runtime_config import load_config
from Archon.Vault.concept_configuration import ConceptConfigurationVault
from Archon.Ledger.store import SQLiteLedgerStore
from Aegis.Storage.service import StorageService
from local_data_archive import LocalDataArchive
from concept_forge.workspace import ConceptWorkspace
from concept_forge.subjects import new_subject
from concept_forge.providers.ollama import GenerationPlan
from forge_errors import BusyError
from concept_forge.planning import ConceptPlanning
from Aegis.Shared.errors import TaskError


class OwnershipTests(unittest.TestCase):
    def test_batch_limit_configuration_is_owned_by_concept_with_legacy_file_compatibility(self):
        default = json.loads((ROOT / "Archon/Vault/default_config.json").read_text())
        self.assertNotIn("max_batch_size", default["orchestrator"])
        self.assertEqual(default["concept_forge"]["max_batch_size"], 20)
        for legacy, current, expected in ((None, None, 20), (4, None, 4),
                                          (4, 7, 7), (None, 3, 3)):
            with self.subTest(legacy=legacy, current=current), tempfile.TemporaryDirectory() as directory:
                data = json.loads(json.dumps(default))
                data["concept_forge"].pop("max_batch_size")
                if legacy is not None:
                    data["orchestrator"]["max_batch_size"] = legacy
                if current is not None:
                    data["concept_forge"]["max_batch_size"] = current
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(data))
                loaded = load_config(path)
                self.assertNotIn("max_batch_size", loaded["orchestrator"])
                self.assertEqual(loaded["concept_forge"]["max_batch_size"], expected)
                self.assertEqual(ConceptPlanning(loaded["concept_forge"], Mock()).max_batch_size,
                                 expected)
        source = inspect.getsource(ConceptWorkspace)
        self.assertNotIn('config["orchestrator"]', source)
        for path in (ROOT / "Archon/Orchestrator").rglob("*.py"):
            self.assertNotIn("max_batch_size", path.read_text(encoding="utf-8"), str(path))

    def test_concept_batch_validation_preserves_count_and_rejects_out_of_range(self):
        for config, maximum in (({}, 20), ({"max_batch_size": "4"}, 4)):
            model = Mock()
            planning = ConceptPlanning(config, model)
            for count in (1, maximum):
                model.generate_prompt.return_value = GenerationPlan(
                    "illustrious", "portrait", "bad", count, "over")
                instruction, _ = planning.plan("portrait")
                self.assertEqual(instruction["count"], count)
            for count in (0, maximum + 1):
                model.generate_prompt.return_value = GenerationPlan(
                    "illustrious", "portrait", "bad", count, "over")
                with self.assertRaisesRegex(TaskError, f"between 1 and {maximum}"):
                    planning.plan("portrait")

    def test_orchestrator_exposes_only_task_api_and_imports_no_business_owners(self):
        public = {name for name, value in vars(Orchestrator).items()
                  if callable(value) and not name.startswith("_")}
        self.assertEqual(public, {"submit", "start_task", "task_job"})
        for module in (inspect.getmodule(Orchestrator), inspect.getmodule(TaskRunner)):
            tree = ast.parse(inspect.getsource(module))
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertFalse(any(any(owner in item for owner in
                ("Storage", "Ledger", "Vault", "concept_forge", "image_forge", "everspark_memory"))
                for item in imports), imports)
            strings = {node.value for node in ast.walk(tree)
                       if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            self.assertFalse(strings & {"engine", "workflow", "checkpoint", "vae", "loras", "llm",
                                        "concept_provider", "api_key", "subject_id", "positive_prompt"})

    def test_task_runner_transfers_an_opaque_instruction_and_invokes_concept_completion(self):
        trace, instruction, options = [], object(), {"legacy_options": object()}
        prepared = SimpleNamespace(instruction=instruction)
        def complete(result):
            trace.append(("complete", result))
            return {"aggregate": result}
        prepared.complete = complete
        @contextmanager
        def prepare(text, session, selected, notify):
            self.assertIs(selected, options)
            trace.append("concept")
            yield prepared
            trace.append("release")
        def generate(message, selected, notify):
            self.assertIs(message, instruction)
            self.assertIs(selected, options)
            trace.append("image")
            return {"reference": "image-task"}
        runner = TaskRunner(SimpleNamespace(prepare_generation=prepare),
                            SimpleNamespace(generate=generate))
        result = runner.run("request", "session", options)
        self.assertEqual(result, {"aggregate": {"reference": "image-task"}})
        self.assertEqual(trace, ["concept", "image", ("complete", {"reference": "image-task"}), "release"])

    def test_task_failure_releases_admission_and_keeps_business_objects_out_of_orchestrator(self):
        runner = Mock()
        runner.run.side_effect = RuntimeError("remote failed")
        orchestrator = Orchestrator(runner)
        with self.assertRaisesRegex(RuntimeError, "remote failed"):
            orchestrator.submit("request", "session")
        self.assertFalse(orchestrator._task_lock.locked())
        self.assertFalse(set(vars(orchestrator)) & {"memory", "storage", "downloads", "backups",
            "data_archive", "_connection_test_jobs", "concept_connections", "gateway"})
        runner.run.side_effect = None
        runner.run.return_value = {"items": [{"prompt_id": "recovered"}]}
        self.assertEqual(orchestrator.submit("request", "session")["result"]["items"][0]["prompt_id"], "recovered")

    def test_ledger_does_not_import_or_interpret_concept_business(self):
        source = inspect.getsource(inspect.getmodule(SQLiteLedgerStore))
        self.assertNotIn("concept_forge", source)
        self.assertNotIn("prompt_contract", source)
        self.assertNotIn("display_name", source)
        self.assertNotIn("generate_subject", source)
        self.assertNotIn("record_success", vars(SQLiteLedgerStore))

    def test_private_configuration_is_written_and_read_by_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = ConceptConfigurationVault(Path(directory) / "connections.json")
            data = {"default": "custom", "connections": [{"api_key": "private", "id": "custom"}]}
            vault.write(data)
            self.assertEqual(vault.read(), data)
            self.assertEqual(vault.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(vault.path.parent.glob("*.tmp")), [])


class ConceptTransactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        config = load_config()
        config["memory"]["database"] = str(Path(self.directory.name) / "memory.db")
        class Model:
            model = "local-test"
            def generate_subject(self, text, subject_id, existing, **kwargs):
                return new_subject(subject_id, "Character")
            def generate_prompt(self, text, history, **kwargs):
                return GenerationPlan("illustrious", "portrait", "bad", 1, "over")
        self.concept = ConceptWorkspace(config, Model(), Mock())

    def test_workspace_uses_concept_limit_without_orchestrator_configuration(self):
        config = load_config()
        config.pop("orchestrator")
        config["concept_forge"]["max_batch_size"] = 2
        config["memory"]["database"] = str(self.concept.memory.database)
        workspace = ConceptWorkspace(config, self.concept.service, Mock())
        image = Mock()
        runner = TaskRunner(workspace, image)
        with patch.object(workspace.service, "generate_prompt", return_value=
                          GenerationPlan("illustrious", "portrait", "bad", 3, "over")):
            with self.assertRaisesRegex(TaskError, "between 1 and 2"):
                runner.run("portrait", "session")
        image.generate.assert_not_called()
        self.assertFalse(workspace.busy())
        image.generate.return_value = {"model": "illustrious", "positive_prompt": "portrait",
            "negative_prompt": "bad", "count": 2, "selection": {},
            "items": [{"prompt_id": "first"}, {"prompt_id": "second"}]}
        with patch.object(workspace.service, "generate_prompt", return_value=
                          GenerationPlan("illustrious", "portrait", "bad", 2, "over")):
            result = runner.run("portrait", "session")
        self.assertEqual(image.generate.call_args.args[0]["count"], 2)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(len(workspace.get_history("session")), 2)

    def test_image_failure_does_not_commit_subject_prompts_or_history_and_retry_is_possible(self):
        image = Mock()
        image.generate.side_effect = RuntimeError("image offline")
        runner = TaskRunner(self.concept, image)
        with self.assertRaisesRegex(RuntimeError, "image offline"):
            runner.run("portrait", "session")
        self.assertEqual(self.concept.get_history("session"), [])
        self.assertIsNone(self.concept.get_session_subject("session"))
        self.assertFalse(self.concept._task_lock.locked())
        image.generate.side_effect = None
        image.generate.return_value = {"model": "illustrious", "positive_prompt": "portrait",
            "negative_prompt": "bad", "count": 1, "selection": {},
            "items": [{"prompt_id": "image-reference"}]}
        result = runner.run("portrait", "session")
        self.assertEqual(len(self.concept.get_history("session")), 2)
        document = self.concept.get_session_subject("session")
        self.assertEqual(document["subject_id"], result["subject"]["subject_id"])
        self.assertEqual(self.concept.memory.get_subject_prompt(document["subject_id"])["negative_prompt"], "bad")

    def test_invalid_conversation_options_do_not_leave_concept_locked(self):
        with self.assertRaisesRegex(ValueError, "JSON object"):
            self.concept.discuss("hello", "session", [])
        self.assertFalse(self.concept._task_lock.locked())

    def test_storage_resolves_ledger_independently_of_concept_private_state(self):
        config = load_config()
        config["memory"]["database"] = str(self.concept.memory.database)
        storage = StorageService(config)
        self.assertIs(storage.data_archive.coordination, self.concept.memory.coordination)
        self.assertIs(storage.backups.coordination, self.concept.memory.coordination)
        self.assertFalse(hasattr(storage, "_task_lock"))
        self.assertFalse(hasattr(storage, "_persistence_lock"))
        with self.concept._task_lock:
            # Busy execution alone does not prevent persistence maintenance.
            storage.data_archive = LocalDataArchive(self.concept.memory.database,
                self.concept.memory.subject_root, Path(self.directory.name))
            archive_id = storage.export_data_archive()
            self.assertTrue(storage.data_archive.archive_path(archive_id).is_file())
        source = inspect.getsource(StorageService)
        self.assertNotIn("self.concept", source)
        self.assertNotIn("_subject_lock", source)
