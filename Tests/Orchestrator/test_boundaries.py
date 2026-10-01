"""Ownership and cross-module regressions for the existing generation pipeline."""
import ast
import inspect
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
from concept_forge.workspace import ConceptWorkspace
from concept_forge.subjects import new_subject
from concept_forge.providers.ollama import GenerationPlan
from forge_errors import BusyError


class OwnershipTests(unittest.TestCase):
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

    def test_storage_maintenance_and_concept_generation_share_exclusion_without_orchestrator_state(self):
        storage = StorageService.__new__(StorageService)
        storage._task_lock = self.concept._task_lock
        storage._persistence_lock = self.concept.memory._subject_lock
        storage.data_archive = Mock()
        with self.concept.prepare_generation("portrait", "session", {}, lambda _: None):
            with self.assertRaises(BusyError):
                storage.export_data_archive()
        storage.data_archive.export.return_value = ("archive-id", None)
        self.assertEqual(storage.export_data_archive(), "archive-id")
        self.assertFalse(self.concept._task_lock.locked())
