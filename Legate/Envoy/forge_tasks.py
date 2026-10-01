"""Allowlisted commands for each Forge on a remote node."""

from __future__ import annotations

from pathlib import Path
import json


from .settings import REPO


def command(forge: str, action: str, message: str) -> tuple[list[str], int] | None:
    if not isinstance(forge, str) or forge not in {"concept", "image", "audio"}:
        return None
    if action == "update":
        return ["bash", str(REPO / "Legate/Envoy/update_source.sh")], 1800
    if action == "revision":
        return ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], 30
    if forge in {"concept", "image"} and action in {
            "models_download_start", "models_download_job", "models_download_cancel",
            "models_download_retry", "models_pull_start", "models_pull_job", "models_installed"}:
        try:
            if isinstance(message, str) and len(message.encode()) <= 60000 and isinstance(json.loads(message), dict):
                return ["python3", str(REPO / "Legate/Warden/model_storage.py"), forge, action, message], 120
        except ValueError:
            pass
        return None
    if forge == "concept":
        if action == "models":
            return ["python3", str(REPO / "Legate/Forge/ConceptForge/remote_chat.py"), "--models"], 30
        if action == "chat" and isinstance(message, str) and len(message.encode("utf-8")) <= 60000:
            try:
                payload = json.loads(message)
            except ValueError:
                return None
            if (isinstance(payload, dict) and isinstance(payload.get("messages"), list)
                    and isinstance(payload.get("model"), str)
                    and isinstance(payload.get("json_mode"), bool)):
                return ["python3", str(REPO / "Legate/Forge/ConceptForge/remote_chat.py"), message], 240
            return None
        if action == "deploy":
            return ["bash", str(REPO / "Legate/Forge/ConceptForge/Scripts/deploy.sh")], 1800
        if action == "health":
            return ["python3", str(REPO / "Legate/Forge/ConceptForge/verify.py"), "请回复：就绪。"], 240
        if action == "discuss" and isinstance(message, str) and 1 <= len(message.strip()) <= 500:
            return ["python3", str(REPO / "Legate/Forge/ConceptForge/verify.py"), message.strip()], 240
    if forge == "image":
        if action in {"resources", "plugins", "default_negative", "submit", "poll", "history", "fetch"} and isinstance(message, str) and len(message.encode("utf-8")) <= 60000:
            try:
                if isinstance(json.loads(message), dict):
                    return ["python3", str(REPO / "Legate/Forge/ImageForge/remote_task.py"),
                            action, message], 300
            except ValueError:
                pass
            return None
        if action == "deploy":
            return ["bash", str(REPO / "Legate/Forge/ImageForge/Scripts/deploy.sh")], 3600
        if action == "health":
            return ["python3", str(REPO / "Legate/Forge/ImageForge/verify.py")], 30
    if forge == "audio":
        if action == "deploy":
            return ["bash", str(REPO / "Legate/Forge/AudioForge/Scripts/deploy.sh")], 3600
        if action in {"health", "synthesize", "fetch", "history"} and isinstance(message, str) and len(message.encode("utf-8")) <= 60000:
            try:
                if isinstance(json.loads(message or "{}"), dict):
                    return [str(REPO / "Data/Runtime/audio-venv/bin/python"),
                        str(REPO / "Legate/Forge/AudioForge/remote_task.py"),
                        action, message or "{}"], 600
            except ValueError:
                pass
    return None
