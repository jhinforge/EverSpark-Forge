from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class ManagedInstallContractTests(unittest.TestCase):
    def test_diffusers_installer_verifies_optional_lora_backend(self) -> None:
        installer = (REPO_ROOT / "Legate/Crucible/install_diffusers.sh").read_text(encoding="utf-8")
        self.assertIn("'peft>=0.17,<0.20'", installer)
        self.assertIn("if not USE_PEFT_BACKEND:", installer)
        self.assertIn("peft-ready", installer)

    def test_shared_runtime_utilities_are_part_of_setup(self) -> None:
        installer = (REPO_ROOT / "Legate/Crucible/install_runtime.sh").read_text(
            encoding="utf-8"
        )
        for package in {
            "wget",
            "aria2",
            "ffmpeg",
            "build-essential",
            "jq",
            "zip",
            "unzip",
            "lsof",
            "zstd",
        }:
            with self.subTest(package=package):
                self.assertRegex(installer, rf"(?m)^  {package}$")

    def test_pod_and_terminal_share_concept_install_steps(self) -> None:
        root = REPO_ROOT / "Legate"
        full_runtime = (root / "Crucible/install_runtime.sh").read_text(encoding="utf-8")
        full_setup = (root / "Crucible/setup.sh").read_text(encoding="utf-8")
        pod = (root / "Forge/ConceptForge/Scripts/deploy.sh").read_text(encoding="utf-8")
        concept_runtime = (root / "Forge/ConceptForge/Scripts/install_runtime.sh").read_text(encoding="utf-8")
        models = (root / "Crucible/install_models.sh").read_text(encoding="utf-8")
        self.assertIn('ConceptForge/Scripts/install_runtime.sh', full_runtime)
        self.assertIn('ConceptForge/Scripts/install_runtime.sh', pod)
        self.assertIn('Crucible/install_models.sh', full_setup)
        self.assertIn('Crucible/install_models.sh', pod)
        self.assertIn('python3-venv zstd', concept_runtime)
        self.assertIn('OLLAMA_VERSION="$OLLAMA_VERSION" sh', concept_runtime)
        self.assertIn('download --models "$SELECTION"', models)
        self.assertIn('import-concept', models)
        self.assertIn('--models concept --keep-concept-running', pod)


if __name__ == "__main__":
    unittest.main()
