"""Persistent user mappings and bounded discovery of real rclone source paths."""

from __future__ import annotations

import configparser
import json
import os
import re
import shlex
from typing import Any

from r2_manager import IMAGE_KINDS, StorageError, StorageSettings


def safe_remote(value: str) -> str:
    value = str(value).strip().rstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*:[^\x00-\x1f]*", value):
        raise StorageError("Use a valid rclone remote:path without control characters")
    path = value.split(":", 1)[1]
    if path.startswith("/") or any(part in {".", ".."} for part in path.split("/")):
        raise StorageError("Unsafe remote directory")
    return value


def safe_relative(name: str) -> bool:
    return bool(name) and not name.startswith("/") and all(
        part not in {"", ".", ".."} and "\\" not in part and "\x00" not in part
        for part in name.split("/")
    )


class RemotePathMap:
    def __init__(self, settings: StorageSettings):
        self.settings = settings
        self.path = (settings.config_file.with_name("model_paths.json") if settings.config_file
                     else None)

    def read(self) -> dict[str, Any]:
        if self.path and self.path.is_file():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        return {}

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {"image_manual", "concept_manual", "image_upload", "concept_upload", "backup_remote"}:
            raise StorageError("Invalid remote mapping")
        images = value.get("image_manual", {})
        uploads = value.get("image_upload", {})
        concept = value.get("concept_manual", [])
        if (not isinstance(images, dict) or not isinstance(uploads, dict)
                or set(images) - set(IMAGE_KINDS) or set(uploads) - set(IMAGE_KINDS)
                or not isinstance(concept, list)):
            raise StorageError("Invalid model directory mapping")
        normalized = {"image_manual": {}, "concept_manual": [], "image_upload": {}}
        for kind, roots in images.items():
            if not isinstance(roots, list) or len(roots) > 10:
                raise StorageError("Specify up to 10 paths per model type")
            normalized["image_manual"][kind] = [safe_remote(root) for root in roots]
        if len(concept) > 10:
            raise StorageError("Specify up to 10 Ollama paths")
        normalized["concept_manual"] = [safe_remote(root) for root in concept]
        for kind, remote in uploads.items():
            normalized["image_upload"][kind] = self.writable(safe_remote(remote))
        for key in ("concept_upload", "backup_remote"):
            raw = value.get(key, "")
            normalized[key] = self.writable(safe_remote(raw)) if raw else ""
        if not self.path:
            raise StorageError("RCLONE_CONFIG is needed to save model mappings")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stage = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        stage.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.chmod(0o600)
        stage.replace(self.path)
        return normalized

    def _sections(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        if self.settings.config_file and self.settings.config_file.is_file():
            parser.read(self.settings.config_file, encoding="utf-8")
        return parser

    def writable(self, remote: str) -> str:
        remote = safe_remote(remote)
        if self._sections().get(remote.split(":", 1)[0], "type", fallback="") == "union":
            raise StorageError("Select a writable rclone source, not a union remote, for uploads")
        return remote

    def sources(self, configured: str) -> list[str]:
        configured = safe_remote(configured)
        name, suffix = configured.split(":", 1)
        section = self._sections()
        if section.get(name, "type", fallback="") != "union":
            return [configured]
        upstreams = shlex.split(section.get(name, "upstreams", fallback=""))
        if not upstreams:
            raise StorageError(f"Union remote {name} has no upstreams")
        return [safe_remote(f"{raw.removesuffix(':ro').removesuffix(':nc').rstrip('/')}/{suffix}".rstrip("/"))
                for raw in upstreams]

    def backup_root(self) -> str:
        manual = self.read().get("backup_remote")
        configured = manual or ""
        if not configured:
            # An explicit environment value keeps priority over the default.
            configured = getattr(self.settings, "backup_remote", "")
        if configured:
            return self.writable(configured)
        source = self.sources(self.settings.image_remote)[0]
        remote, path = source.split(":", 1)
        bucket = path.split("/", 1)[0]
        if not bucket:
            raise StorageError("Set a backup directory inside a writable bucket")
        return self.writable(f"{remote}:{bucket}/everspark-backups")

    def concept_upload_root(self) -> str:
        manual = self.read().get("concept_upload")
        if manual:
            return self.writable(manual)
        remote, path = self.backup_root().split(":", 1)
        return f"{remote}:{path.split('/', 1)[0]}/everspark-gguf"

    def image_roots(self, client) -> dict[str, list[str]]:
        roots: dict[str, list[str]] = {kind: [] for kind in IMAGE_KINDS}
        sources = self.sources(self.settings.image_remote)
        for source in sources:
            # One bounded listing per source; never traverse the entire bucket.
            paths = client.list_files(source, recursive=True, max_depth=7)
            if len(paths) > 20000:
                raise StorageError("Remote model scan exceeded 20000 files; specify directories manually")
            for path in paths:
                if not safe_relative(path):
                    continue
                parts = path.split("/")
                for index, segment in enumerate(parts[:-1]):
                    for kind, directory in IMAGE_KINDS.items():
                        if segment.casefold() == directory:
                            root = f"{source}/{'/'.join(parts[:index + 1])}"
                            if root not in roots[kind]:
                                roots[kind].append(root)
        for kind, values in self.read().get("image_manual", {}).items():
            for root in values:
                if root not in roots[kind]:
                    roots[kind].append(root)
        # Retain the old direct-category layout for empty directories. A path
        # seen in the listing or supplied manually wins over guessed paths.
        for kind, directory in IMAGE_KINDS.items():
            if not roots[kind]:
                roots[kind].extend(f"{source}/{directory}" for source in sources)
        return roots

    def concept_roots(self, client) -> tuple[list[str], list[str]]:
        native, gguf = [], []
        sources = [*self.sources(self.settings.concept_remote), *self.read().get("concept_manual", [])]
        for source in sources:
            if source in native:
                continue
            paths = client.list_files(source, recursive=True, max_depth=6, exclude_blobs=True)
            for path in paths:
                if not safe_relative(path):
                    continue
                parts = path.split("/")
                if "manifests" in parts[:-1]:
                    root = f"{source}/{'/'.join(parts[:parts.index('manifests')])}".rstrip("/")
                    if root not in native:
                        native.append(root)
                if path.lower().endswith(".gguf"):
                    root = f"{source}/{'/'.join(parts[:-1])}".rstrip("/")
                    if root not in gguf:
                        gguf.append(root)
            if source in self.sources(self.settings.concept_remote) and source not in native:
                native.append(source)
            if source not in gguf:
                gguf.append(source)
        if self.concept_upload_root() not in gguf:
            gguf.append(self.concept_upload_root())
        return native, gguf
