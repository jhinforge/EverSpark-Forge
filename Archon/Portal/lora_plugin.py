"""Local installation and configuration for the downloadable LoRA catalog."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path
from urllib.request import urlopen

from Archon.Vault.windows_credentials import WindowsCredentialStore


REPOSITORY = "https://raw.githubusercontent.com/jhinforge/EverSpark-Forge-Plugins"
REVISION = "3b87523233778e360216632eb1a9bc76ee518b87"
FILES = {
    "catalog.py": "59b2789749560fd12462e8c0c1d8351ffb2e4143998c0b70f94e2ba6ee514bc9",
    "panel.css": "a070a8fa903662efa78c0cd7b62bdcba9ca69c9c4cb4bbee8beb1917ae00759a",
    "panel.js": "8070b37be0fea8752ca9e9e4ed0d11ffec25cd18701f9b418b707d274af1cb00",
    "thumbnail_names.py": "91bc8b5bd5503fcb9c5dfb1466919c6df54041aeed139592f11986e45050a059",
}
DIRECTORIES = ("notes_dir", "previews_dir", "thumbnails_dir", "temp_dir")
ASSETS = {"panel.js": "text/javascript; charset=utf-8", "panel.css": "text/css; charset=utf-8"}
CREDENTIAL_TARGET = "EverSpark Forge/Civitai API Key"
MAX_PLUGIN_FILE = 256 * 1024


class LoRAPlugin:
    def __init__(self, root: Path):
        self.install_dir = root / "Data" / "Plugins" / "lora" / REVISION
        self.config_file = root / "Data" / "Configuration" / "LoRA" / "lora-config.json"
        self._lock = threading.RLock()
        self._module = None

    @staticmethod
    def _verify(name, content):
        if len(content) > MAX_PLUGIN_FILE or hashlib.sha256(content).hexdigest() != FILES[name]:
            raise ValueError("LoRA plugin file verification failed")
        return content

    def status(self):
        with self._lock:
            installed = True
            try:
                for name in FILES:
                    with (self.install_dir / name).open("rb") as stream:
                        self._verify(name, stream.read(MAX_PLUGIN_FILE + 1))
            except (OSError, ValueError):
                installed = False
        return {"installed": installed, "version": REVISION[:7]}

    def install(self):
        with self._lock:
            if self.status()["installed"]:
                return self.status()
            self.install_dir.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.install_dir.parent) as staging:
                candidate = Path(staging) / "panel"
                candidate.mkdir()
                for name in FILES:
                    url = f"{REPOSITORY}/{REVISION}/everspark_lora_panel/{name}"
                    with urlopen(url, timeout=20) as response:
                        content = self._verify(name, response.read(MAX_PLUGIN_FILE + 1))
                    (candidate / name).write_bytes(content)
                previous = Path(staging) / "previous"
                if self.install_dir.exists():
                    self.install_dir.rename(previous)
                try:
                    candidate.rename(self.install_dir)
                except OSError:
                    if previous.exists():
                        previous.rename(self.install_dir)
                    raise
            self._module = None
            return self.status()

    def asset(self, name):
        if name not in ASSETS or not self.status()["installed"]:
            raise FileNotFoundError(name)
        return self._verify(name, (self.install_dir / name).read_bytes()), ASSETS[name]

    def _catalog_module(self):
        with self._lock:
            if self._module is not None:
                return self._module
            if not self.status()["installed"]:
                raise FileNotFoundError("Install LoRA Catalog first")
            namespace = f"_everspark_lora_{id(self):x}"
            package = types.ModuleType(namespace)
            package.__path__ = []
            sys.modules[namespace] = package
            loaded = []
            try:
                for name in ("thumbnail_names.py", "catalog.py"):
                    path = self.install_dir / name
                    source = self._verify(name, path.read_bytes())
                    qualified = f"{namespace}.{path.stem}"
                    spec = importlib.util.spec_from_file_location(qualified, path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[qualified] = module
                    loaded.append(qualified)
                    exec(compile(source, str(path), "exec"), module.__dict__)
            except Exception:
                for qualified in loaded:
                    sys.modules.pop(qualified, None)
                sys.modules.pop(namespace, None)
                raise
            self._module = module
            return module

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
        paths = {key: self._path(payload.get(key)) for key in DIRECTORIES}
        if len(set(paths.values())) != len(DIRECTORIES):
            raise ValueError("Use a different directory for each purpose")
        source = (paths["temp_dir"] / "previews").resolve()
        assets = paths["previews_dir"]
        if source.is_relative_to(assets) or assets.is_relative_to(source):
            raise ValueError("Temporary previews and archived previews cannot overlap")
        vault = payload.get("vault_root", "")
        if vault:
            paths["vault_root"] = self._path(vault)
            if not paths["vault_root"].is_dir():
                raise ValueError("The Obsidian Vault directory does not exist")
        for key in DIRECTORIES:
            paths[key].mkdir(parents=True, exist_ok=True)
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

    def _catalog_config(self):
        config = self.config()
        if not all(config.get(key) for key in DIRECTORIES):
            raise ValueError("Configure the LoRA directories first")
        return {key: Path(value).resolve() for key, value in config.items() if key in (*DIRECTORIES, "vault_root")}

    def catalog(self):
        return list(self._catalog_module().rows(self._catalog_config()))

    def media(self, note_id, kind):
        result = self._catalog_module().media(self._catalog_config(), note_id, kind)
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
$dialog.Description = 'EverSpark Forge - LoRA Catalog'
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
