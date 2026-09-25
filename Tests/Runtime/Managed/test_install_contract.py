from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


class ManagedInstallContractTests(unittest.TestCase):
    def test_diffusers_installer_verifies_optional_lora_backend(self) -> None:
        installer = (REPO_ROOT / "Runtime/Managed/install_diffusers.sh").read_text(encoding="utf-8")
        self.assertIn("'peft>=0.17,<0.20'", installer)
        self.assertIn("if not USE_PEFT_BACKEND:", installer)
        self.assertIn("peft-ready", installer)

    def test_shared_runtime_utilities_are_part_of_setup(self) -> None:
        installer = (REPO_ROOT / "Runtime/Managed/install_runtime.sh").read_text(
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


if __name__ == "__main__":
    unittest.main()
