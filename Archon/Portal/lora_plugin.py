"""Local installation and configuration for the downloadable Image Model Manager."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

from Archon.Portal.lora_update import REQUIRED_FILES, VERSION_FILE, download_update, read_version
from Archon.Vault.windows_credentials import WindowsCredentialStore


DIRECTORIES = ("notes_dir", "previews_dir", "thumbnails_dir", "temp_dir")
CHECKPOINT_DIRS = tuple("checkpoint_" + key for key in DIRECTORIES)
ASSETS = {"panel.js": "text/javascript; charset=utf-8", "panel.css": "text/css; charset=utf-8"}
CREDENTIAL_TARGET = "EverSpark Forge/Civitai API Key"


class LoRAPlugin:
    def __init__(self, root: Path):
        self.plugin_dir = root / "Data" / "Plugins" / "lora"
        self.install_dir = self.plugin_dir / "current"
        self.config_file = root / "Data" / "Configuration" / "LoRA" / "lora-config.json"
        self._lock = threading.RLock()
        self._module = None
        self._namespace = None

    def _active_dir(self):
        def usable(path):
            return all((path / name).is_file() for name in REQUIRED_FILES if name != VERSION_FILE)

        if usable(self.install_dir):
            return self.install_dir
        if self.plugin_dir.is_dir():
            # Existing installs used a 40-character revision directory.
            prior = [path for path in self.plugin_dir.iterdir() if path.is_dir()
                     and len(path.name) == 40 and usable(path)]
            if prior:
                return max(prior, key=lambda path: path.stat().st_mtime)
        return None

    def status(self):
        with self._lock:
            directory = self._active_dir()
            if directory is None:
                return {"installed": False, "version": None}
            try:
                version = read_version((directory / VERSION_FILE).read_bytes())
            except (OSError, ValueError):
                version = "legacy"
            return {"installed": True, "version": version}

    def install(self):
        with self._lock:
            local = self.status()
            self.plugin_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.plugin_dir) as staging:
                candidate = Path(staging) / "panel"
                candidate.mkdir()
                if not download_update(local["version"], candidate):
                    return {**local, "changed": False}
                previous = Path(staging) / "previous"
                if self.install_dir.exists():
                    self.install_dir.rename(previous)
                try:
                    candidate.rename(self.install_dir)
                except OSError:
                    if previous.exists():
                        previous.rename(self.install_dir)
                    raise
            self._unload_catalog()
            importlib.invalidate_caches()
            return {**self.status(), "changed": True}

    def asset(self, name):
        with self._lock:
            directory = self._active_dir()
            if directory is None or name not in ASSETS:
                raise FileNotFoundError(name)
            return (directory / name).read_bytes(), ASSETS[name]

    def _unload_catalog(self):
        if self._namespace is not None:
            for name in list(sys.modules):
                if name == self._namespace or name.startswith(self._namespace + "."):
                    sys.modules.pop(name, None)
        self._namespace = None
        self._module = None

    def _catalog_module(self):
        with self._lock:
            if self._module is not None:
                return self._module
            directory = self._active_dir()
            if directory is None:
                raise FileNotFoundError("Install Image Model Manager first")
            namespace = f"_everspark_lora_{id(self):x}"
            package = types.ModuleType(namespace)
            package.__path__ = [str(directory)]
            sys.modules[namespace] = package
            self._namespace = namespace
            try:
                self._module = importlib.import_module(f"{namespace}.catalog")
            except Exception:
                self._unload_catalog()
                raise
            return self._module

    def config(self):
        try:
            return json.loads(self.config_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    @staticmethod
    def _path(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError("Enter a directory path")
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("Use an absolute directory path")
        return path.resolve()

    def save_config(self, payload):
        paths = {}
        for keys in (DIRECTORIES, CHECKPOINT_DIRS):
            if any(payload.get(key) for key in keys):
                paths.update({key: self._path(payload.get(key)) for key in keys})
        if not paths:
            raise ValueError("Configure all four directories for at least one library")
        if len(set(paths.values())) != len(paths):
            raise ValueError("Use a different directory for each purpose")
        for prefix in ("", "checkpoint_"):
            if prefix + "temp_dir" not in paths:
                continue
            source = (paths[prefix + "temp_dir"] / "previews").resolve()
            assets = paths[prefix + "previews_dir"]
            if source.is_relative_to(assets) or assets.is_relative_to(source):
                raise ValueError("Temporary previews and archived previews cannot overlap")
        vault = payload.get("vault_root", "")
        if vault:
            paths["vault_root"] = self._path(vault)
            if not paths["vault_root"].is_dir():
                raise ValueError("The Obsidian Vault directory does not exist")
        for directory in paths.values():
            directory.mkdir(parents=True, exist_ok=True)
        config = {key: str(path) for key, path in paths.items()}
        with self._lock:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.config_file.parent, delete=False) as stream:
                temp = Path(stream.name)
                json.dump(config, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            try:
                temp.replace(self.config_file)
            finally:
                temp.unlink(missing_ok=True)
        return config

    @staticmethod
    def _directory_keys(library):
        if library == "lora":
            return DIRECTORIES
        if library == "checkpoints":
            return CHECKPOINT_DIRS
        raise ValueError("Unknown model library")

    def _catalog_config(self, library="lora"):
        config = self.config()
        keys = self._directory_keys(library)
        if not all(config.get(key) for key in keys):
            raise ValueError(f"Configure the {library} directories first")
        paths = {name: Path(config[key]).resolve() for name, key in zip(DIRECTORIES, keys)}
        if config.get("vault_root"):
            paths["vault_root"] = Path(config["vault_root"]).resolve()
        return {**paths, "library": library}

    def catalog(self, library="lora"):
        keys = self._directory_keys(library)
        config = self.config()
        if not all(config.get(key) for key in keys):
            return []
        if library == "checkpoints" and not self.library_features()["checkpoints"]:
            raise FileNotFoundError("Checkpoints library is unavailable")
        return list(self._catalog_module().rows(self._catalog_config(library)))

    def library_features(self):
        with self._lock:
            directory = self._active_dir()
            supported = bool(directory and (directory / "thumbnail_rebuild.py").is_file())
            config = self.config()
            return {
                "checkpoints": supported,
                "can_rebuild": supported,
                "lora_configured": all(config.get(key) for key in DIRECTORIES),
                "checkpoints_configured": all(config.get(key) for key in CHECKPOINT_DIRS),
            }

    def rebuild_thumbnails(self, library):
        with self._lock:
            if not self.library_features()["can_rebuild"]:
                raise FileNotFoundError("Thumbnail rebuild is unavailable")
            package = self._catalog_module().__package__
            module = importlib.import_module(f"{package}.thumbnail_rebuild")
            return module.rebuild(self._catalog_config(library))

    def import_available(self):
        with self._lock:
            directory = self._active_dir()
            return bool(directory and (directory / "importer.py").is_file())

    def import_lora(self, action, payload):
        with self._lock:
            if not self.import_available():
                raise FileNotFoundError("LoRA import plugin is unavailable")
            package = self._catalog_module().__package__
            importer = importlib.import_module(f"{package}.importer")
            if action == "commit":
                return importer.commit(self._catalog_config(), payload)
            if action == "schema":
                return {"categories": importer.CATEGORIES}
            url = payload.get("url")
            if not isinstance(url, str) or len(url) > 2000:
                raise ValueError("Enter a Civitai model URL")
            key = WindowsCredentialStore(CREDENTIAL_TARGET).get() if sys.platform == "win32" else None
            return importer.fetch_fields(url, key or "")

    def deletion_available(self):
        with self._lock:
            directory = self._active_dir()
            return bool(directory and (directory / "delete_entry.py").is_file())

    def delete_lora(self, payload, *, confirm=False):
        with self._lock:
            if not self.deletion_available():
                raise FileNotFoundError("LoRA deletion is unavailable")
            package = self._catalog_module().__package__
            deletion = importlib.import_module(f"{package}.delete_entry")
            config = self._catalog_config()
            if confirm:
                return deletion.commit(config, payload.get("id"), payload.get("token"))
            return deletion.preview(config, payload.get("id"))

    def media(self, note_id, kind, library="lora"):
        if library == "checkpoints" and not self.library_features()["checkpoints"]:
            raise FileNotFoundError("Checkpoints library is unavailable")
        result = self._catalog_module().media(self._catalog_config(library), note_id, kind)
        if result is None:
            raise FileNotFoundError("LoRA image not found")
        path, mime = result
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("LoRA preview image is too large")
        return path.read_bytes(), mime

    def credentials(self, action="status", key=None):
        if sys.platform != "win32":
            return {"available": False, "configured": False}
        store = WindowsCredentialStore(CREDENTIAL_TARGET)
        if action == "save":
            if not isinstance(key, str) or not key.strip() or len(key.encode("utf-8")) > 2048:
                raise ValueError("Enter a Civitai API Key")
            store.set(key.strip())
        elif action == "remove":
            store.delete()
        return {"available": True, "configured": bool(store.get())}

    @staticmethod
    def pick_directory():
        if sys.platform != "win32":
            return ""
        # Portable Python does not bundle Tk. Use the installed Windows folder dialog.
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        script = """
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'EverSpark Forge - Image Model Manager'
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.Opacity = 0
$owner.ShowInTaskbar = $false
try {
  $owner.Show()
  if ($dialog.ShowDialog($owner) -eq 'OK') { [Console]::WriteLine($dialog.SelectedPath) }
} finally { $dialog.Dispose(); $owner.Dispose() }
"""
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NoLogo", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, timeout=180, check=True, encoding="utf-8",
            errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.stdout.strip()
