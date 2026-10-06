"""Local release metadata for the About page; no authenticity claim."""
import json
from pathlib import Path
import subprocess


def build_info(root: Path) -> dict[str, str]:
    def read(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    release = read(root / "release.json")
    config = read(root / "Archon/Client/Windows/tauri.conf.json")
    info = {key: value for key, value in release.items()
            if key in {"version", "revision", "built_at", "variant"} and isinstance(value, str)}
    info.setdefault("version", config.get("version", ""))
    info.setdefault("variant", "Source checkout")
    if not release and (root / ".git").exists():
        try:
            info["revision"] = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                text=True, timeout=2, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return info
