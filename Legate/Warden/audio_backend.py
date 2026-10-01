"""Bounded, isolated Audio worker lifecycle, using the managed Python runtime."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def python_executable():
    return ROOT / "Data/Runtime/audio-venv/bin/python"


def run(action, payload, config):
    python = python_executable()
    if not python.is_file():
        raise RuntimeError("Deploy Audio Forge before using its runtime")
    # An existing config path keeps worker configuration owned by Vault.
    import os
    environment = dict(os.environ)
    environment["EVERSPARK_ORCHESTRATOR_CONFIG"] = config["_config_path"]
    done = subprocess.run([str(python), str(ROOT / "Legate/Forge/AudioForge/remote_task.py"),
        action, json.dumps(payload, ensure_ascii=False)], env=environment,
        cwd=ROOT, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if done.returncode:
        raise RuntimeError("Audio Forge worker failed: " + done.stderr[-2000:])
    try:
        value = json.loads(done.stdout)
        if not isinstance(value, dict):
            raise ValueError("Expected worker object")
        return value
    except ValueError as exc:
        raise RuntimeError("Audio Forge worker returned invalid output") from exc
