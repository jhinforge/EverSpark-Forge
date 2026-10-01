from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
from dataclasses import replace
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Legate" / "Crucible" / "Models"))

import model_manager  # noqa: E402


class ModelManagerTests(unittest.TestCase):
    def test_progress_counts_only_models_available_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            specs = [replace(spec, target=f"Data/Models/{index}.bin")
                     for index, spec in enumerate(model_manager.load_specs())]
            with patch.object(model_manager, "REPO_ROOT", root), patch.object(model_manager, "STATE_PATH", root/"state.json"), patch.dict(model_manager.os.environ, {"EVERSPARK_DEPLOY_PROGRESS": "1"}):
                specs[0].target_path.parent.mkdir(parents=True)
                specs[0].target_path.write_bytes(b"cached")
                output = io.StringIO()
                def download(spec):
                    spec.target_path.write_bytes(b"downloaded")
                    return str(spec.target_path)
                with redirect_stdout(output):
                    installed = model_manager.download_models(specs, downloader=download)
                self.assertTrue(all(item["installed"] for item in installed))
                self.assertEqual(output.getvalue().splitlines(), [
                    "[EverSpark:deploy] downloading_models 0/2",
                    "[EverSpark:deploy] downloading_models 1/2",
                    "[EverSpark:deploy] downloading_models 2/2"])
                specs[1].target_path.unlink()
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(model_manager.ModelManagerError):
                    model_manager.download_models(specs, downloader=lambda spec: root/"missing")
                self.assertNotIn("2/2", output.getvalue())

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
