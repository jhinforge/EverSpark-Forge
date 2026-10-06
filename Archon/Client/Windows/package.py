"""Create both portable ZIPs from a tracked checkout and one compiled EXE."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

CLIENT = Path(__file__).resolve().parent
ROOT = CLIENT.parents[2]
MANIFEST = json.loads((CLIENT / "runtime-manifest.json").read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(kind: str, cache: Path) -> Path:
    record = MANIFEST[kind]
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / record["url"].rsplit("/", 1)[-1]
    if path.is_file() and digest(path) == record["sha256"]:
        return path
    temporary = path.with_suffix(".part")
    try:
        with urlopen(record["url"], timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(temporary) != record["sha256"]:
            raise ValueError(f"{kind} runtime checksum mismatch")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def source_files(root: Path) -> list[Path]:
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
    files = []
    for name in raw.decode("utf-8").split("\0"):
        if not name:
            continue
        path = PurePosixPath(name)
        if path.parts[0] in {"Data", "Tests", "Docs", "docs", "Runtime", ".github", ".codex"}:
            continue
        if path.parts[0].startswith(".") or path.suffix.lower() == ".md":
            continue
        if name.startswith("Archon/Vault/Import/") or name.startswith("Archon/Vault/user."):
            continue
        if any(part in {"__pycache__", "target", "node_modules", ".cache"} for part in path.parts):
            continue
        candidate = root / name
        if candidate.is_file() and not candidate.is_symlink():
            files.append(candidate)
    return files


def prepare_python(archive: Path, destination: Path) -> None:
    if digest(archive) != MANIFEST["python"]["sha256"]:
        raise ValueError("Python runtime checksum mismatch")
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            part = PurePosixPath(name)
            if part.is_absolute() or ".." in part.parts or "\\" in name:
                raise ValueError("Unsafe Python runtime member")
        source.extractall(destination)
    (destination / "Lib/site-packages").mkdir(parents=True)
    (destination / "python311._pth").write_text(
        "python311.zip\n.\nLib/site-packages\n../..\nimport site\n", encoding="utf-8")
    requirements = CLIENT / "requirements.txt"
    if any(line.strip() and not line.lstrip().startswith("#") for line in requirements.read_text().splitlines()):
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.11",
                        "--implementation", "cp", "--abi", "cp311", "--target",
                        str(destination / "Lib/site-packages"), "-r", str(requirements)], check=True)


def prepare_webview(archive: Path, destination: Path) -> None:
    if digest(archive) != MANIFEST["webview2"]["sha256"]:
        raise ValueError("WebView2 runtime checksum mismatch")
    if os.name != "nt":
        raise RuntimeError("Extract the Microsoft CAB on the Windows build runner")
    with tempfile.TemporaryDirectory(prefix="everspark-webview-") as temp:
        subprocess.run(["expand.exe", str(archive.resolve()), "-F:*", temp], check=True,
                       stdout=subprocess.DEVNULL)
        candidates = list(Path(temp).rglob("msedgewebview2.exe"))
        if len(candidates) != 1:
            raise ValueError("Invalid fixed WebView2 runtime structure")
        shutil.copytree(candidates[0].parent, destination)


def make_packages(executable: Path, output: Path, *, python_archive: Path,
                  webview_archive: Path | None = None, root: Path = ROOT) -> list[Path]:
    if executable.read_bytes()[:2] != b"MZ":
        raise ValueError("Client executable must be a Windows PE file")
    version = json.loads((CLIENT / "tauri.conf.json").read_text())["version"]
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output.mkdir(parents=True, exist_ok=True)
    # Build in a fresh stage so no local credentials or accumulated Data enter it.
    with tempfile.TemporaryDirectory(prefix="everspark-package-") as temporary:
        stage = Path(temporary) / "EverSpark-Forge"
        stage.mkdir()
        for source in source_files(root):
            target = stage / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copy2(executable, stage / "EverSpark.exe")
        prepare_python(python_archive, stage / "Runtime/Python")
        if os.name == "nt":
            subprocess.run([str(stage / "Runtime/Python/python.exe"), "-I", "-X", "utf8", "-c",
                "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd())); "
                "assert sys.version_info[:3] == (3,11,9); "
                "from Archon.Gate.CLI.archon import _load_local_settings; "
                "from Archon.Portal.app import WebUIServer; "
                "from Archon.Gate.remote_runtime import create_runtime; "
                "from pathlib import Path; "
                "[sys.path.insert(0, str(Path.cwd()/p)) for p in "
                "('Archon/Orchestrator','Legate/Forge','Legate/Forge/ConceptForge',"
                "'Legate/Forge/ImageForge','Legate/Forge/ConceptForge/Memory','Aegis/Logging')]; "
                "from Archon.Gate.application import GateApplication"], check=True, cwd=stage,
                env={**os.environ, "PYTHONUTF8": "1"})
        paths = []
        variants = ["standard", "full"] if webview_archive else ["standard"]
        for variant in variants:
            if variant == "full":
                prepare_webview(webview_archive, stage / "Runtime/WebView2")
            (stage / "release.json").write_text(json.dumps({"version": version, "revision": revision,
                "variant": variant, "built_at": built_at, "architecture": "x64", "python": MANIFEST["python"]["version"],
                "webview2": MANIFEST["webview2"]["version"] if variant == "full" else "system"}, indent=2), encoding="utf-8")
            name = output / f"EverSpark-Forge-{version}-windows-x64-{variant}.zip"
            temporary_zip = name.with_suffix(".zip.part")
            try:
                with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for source in sorted(stage.rglob("*")):
                        if source.is_file() and "__pycache__" not in source.parts:
                            archive.write(source, source.relative_to(stage.parent))
                temporary_zip.replace(name)
            finally:
                temporary_zip.unlink(missing_ok=True)
            name.with_suffix(".zip.sha256").write_text(f"{digest(name)}  {name.name}\n", encoding="ascii")
            paths.append(name)
        return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--standard-only", action="store_true")
    args = parser.parse_args()
    cache = CLIENT / ".cache"
    python = download("python", cache)
    webview = None if args.standard_only else download("webview2", cache)
    for path in make_packages(args.exe.resolve(), args.output.resolve(),
                              python_archive=python, webview_archive=webview):
        print(path)


if __name__ == "__main__":
    main()
