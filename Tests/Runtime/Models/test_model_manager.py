from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Models"))

import model_manager  # noqa: E402


class ModelManagerTests(unittest.TestCase):
    def test_default_catalog_contains_both_managed_models(self) -> None:
        specs = model_manager.load_specs()
        self.assertEqual(
            {spec.id for spec in specs}, {"concept-default", "image-default"}
        )
        self.assertEqual(
            model_manager.select_specs(specs, "concept")[0].runtime_name,
            "everspark-concept",
        )

    def test_target_cannot_escape_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "models.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "models": [
                            {
                                "id": "bad",
                                "component": "image_forge",
                                "source": "huggingface",
                                "repo_id": "owner/repo",
                                "filename": "model.safetensors",
                                "revision": "main",
                                "target": "../outside.safetensors",
                                "license": "test",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(model_manager.ModelManagerError):
                model_manager.load_specs(manifest)

    def test_download_and_concept_import_use_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = model_manager.ModelSpec(
                id="concept-default",
                component="concept_forge",
                source="huggingface",
                repo_id="Qwen/Qwen3-4B-GGUF",
                filename="Qwen3-4B-Q4_K_M.gguf",
                revision="main",
                target="Data/Models/ConceptForge/Qwen3-4B-Q4_K_M.gguf",
                license="Apache-2.0",
                runtime_name="everspark-concept",
                prompt_mode="no_think",
            )
            source = root / "download.gguf"
            source.write_bytes(b"fake-model")
            state = root / "Data/Runtime/Models/state.json"
            modelfile = root / "Data/Runtime/Models/ConceptForge.Modelfile"
            with (
                patch.object(model_manager, "REPO_ROOT", root),
                patch.object(model_manager, "STATE_PATH", state),
                patch.object(model_manager, "MODELFILE_PATH", modelfile),
            ):
                installed = model_manager.download_models(
                    [spec], downloader=lambda _spec: str(source)
                )
                self.assertTrue(installed[0]["installed"])
                completed = subprocess.CompletedProcess([], 0, "", "")
                with patch.object(model_manager.shutil, "which", return_value="/bin/ollama"):
                    result = model_manager.prepare_concept_runtime(
                        [spec], run=lambda *args, **kwargs: completed
                    )
            self.assertEqual(result["model"], "everspark-concept")
            self.assertIn("FROM ", modelfile.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
