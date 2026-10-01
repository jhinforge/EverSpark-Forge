"""Run the Audio installer against isolated command doubles, without downloads."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class AudioInstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for path in ("Legate/Crucible/System", "Legate/Forge/AudioForge", "Legate/Warden/Hardware", "Aegis/Shared/Shell", "bin"):
            (self.root / path).mkdir(parents=True)
        shutil.copyfile(ROOT / "Legate/Crucible/install_audio.sh", self.root / "Legate/Crucible/install_audio.sh")
        shutil.copyfile(ROOT / "Legate/Forge/AudioForge/requirements.txt", self.root / "Legate/Forge/AudioForge/requirements.txt")
        shutil.copyfile(ROOT / "Aegis/Shared/Shell/common.sh", self.root / "Aegis/Shared/Shell/common.sh")
        (self.root / "Legate/Crucible/System/apt.sh").write_text("core_apt_install_missing() { :; }\n")
        (self.root / "Legate/Warden/Hardware/torch_profile.sh").write_text(
            'core_torch_profile_detect() { echo "${TEST_TORCH_PROFILE:-cu128}"; }\n'
            'core_torch_profile_index() { echo "https://download.pytorch.org/whl/$1"; }\n')
        self.trace = self.root / "trace"
        worker = self.root / "worker"
        worker.write_text('''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$INSTALL_TRACE"
if [[ "$*" == *"pip install --upgrade pip"* ]]; then
  if [[ "${FAIL_BOOTSTRAP:-0}" == 1 ]]; then exit 1; fi
  touch "$BOOTSTRAP_MARKER"
elif [[ "$*" == *"pip install"* ]] && [[ ! -f "$BOOTSTRAP_MARKER" ]]; then
  echo 'Old pip resolver used before bootstrap' >&2
  exit 2
fi
if [[ "$*" == *"pip install --upgrade --constraint"* ]]; then
  [[ -f "$6" && -f "$8" ]]
  grep -q '^torchaudio==2.9.1+cu12' "$6"
  grep -q '^voxcpm @ git+https://github.com/OpenBMB/VoxCPM.git@f0c787f0937dc1c9a8f4f64d9a332d9c5da2e629$' "$8"
fi
if [[ "$*" == *"validate_runtime"* && "${FAIL_RUNTIME_IMPORT:-0}" == 1 ]]; then
  echo 'OSError: libcudart.so.13 missing' >&2
  exit 1
fi
''')
        worker.chmod(0o755)
        python = self.root / "bin/python3"
        python.write_text('''#!/usr/bin/env bash
set -eu
if [[ "$1" == -m && "$2" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$FAKE_WORKER" "$3/bin/python"
fi
''')
        python.chmod(0o755)
        self.environment = {**os.environ, "PATH": str(self.root / "bin") + os.pathsep + os.environ["PATH"],
            "FAKE_WORKER": str(worker), "INSTALL_TRACE": str(self.trace),
            "BOOTSTRAP_MARKER": str(self.root / "bootstrapped"), "EVERSPARK_DEPLOY_PROGRESS": "1"}

    def install(self, **environment):
        return subprocess.run(["bash", str(self.root / "Legate/Crucible/install_audio.sh")],
            env={**self.environment, **environment}, capture_output=True, text=True, timeout=10)

    def test_bootstrap_precedes_dependency_resolution_on_initial_install_and_retry(self):
        image = self.root / "Data/Runtime/Diffusers/venv/image-sentinel"
        image.parent.mkdir(parents=True)
        image.write_text("existing image environment")
        for _ in range(2):
            done = self.install()
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("[EverSpark:deploy] installing_python_dependencies", done.stdout)
        calls = self.trace.read_text().splitlines()
        self.assertEqual(len(calls), 12)
        for start in (0, 6):
            self.assertIn("pip install --upgrade pip>=24,<26 setuptools>=70,<81 wheel>=0.43,<1", calls[start])
            self.assertIn("--index-url https://download.pytorch.org/whl/cu128", calls[start + 1])
            self.assertIn("torch==2.9.1+cu128 torchaudio==2.9.1+cu128", calls[start + 1])
            self.assertIn("--constraint", calls[start + 2])
            self.assertIn("--upgrade --constraint", calls[start + 2])
            self.assertIn("--requirement", calls[start + 2])
            self.assertIn("Legate/Forge/AudioForge/requirements.txt", calls[start + 2])
            self.assertIn("pip check", calls[start + 3])
            self.assertIn("validate_runtime()", calls[start + 4])
            self.assertIn("Aegis/Storage/model_snapshot.py", calls[start + 5])
        self.assertEqual(image.read_text(), "existing image environment")

    def test_cu126_uses_matching_packages_and_constraints(self):
        done = self.install(TEST_TORCH_PROFILE="cu126")
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.trace.read_text().splitlines()
        self.assertIn("--index-url https://download.pytorch.org/whl/cu126", calls[1])
        self.assertIn("torch==2.9.1+cu126 torchaudio==2.9.1+cu126", calls[1])
        self.assertEqual((self.root / "Data/Runtime/audio-venv/torch-constraints.txt").read_text(),
                         "torch==2.9.1+cu126\ntorchaudio==2.9.1+cu126\n")

    def test_failed_native_import_stops_deployment_before_model_download(self):
        done = self.install(FAIL_RUNTIME_IMPORT="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("libcudart.so.13", done.stderr)
        self.assertNotIn("model_snapshot.py", self.trace.read_text())

    def test_failed_bootstrap_stops_before_torch_models_or_voxcpm_installation(self):
        done = self.install(FAIL_BOOTSTRAP="1")
        self.assertNotEqual(done.returncode, 0)
        calls = self.trace.read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn("--upgrade", calls[0])
