"""Download Image Model Manager only when its published version differs."""

import io
import re
import zipfile
from pathlib import PurePosixPath
from urllib.request import urlopen


REPOSITORY = "jhinforge/EverSpark-Forge-Plugins"
PANEL = "everspark_lora_panel"
VERSION_FILE = "VERSION"
VERSION_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/main/{PANEL}/{VERSION_FILE}"
ARCHIVE_URL = f"https://codeload.github.com/{REPOSITORY}/zip/refs/heads/main"
REQUIRED_FILES = (VERSION_FILE, "catalog.py", "thumbnail_names.py", "panel.js", "panel.css")
MAX_PACKAGE_SIZE = 8 * 1024 * 1024
MAX_VERSION_SIZE = 128


def read_version(data):
    version = data.decode("utf-8-sig").strip()
    if not re.fullmatch(r"[0-9][A-Za-z0-9._+-]{0,63}", version):
        raise ValueError("The Image Model Manager plugin version is invalid")
    return version


def fetch(url, limit):
    with urlopen(url, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("The Image Model Manager plugin download is too large")
    return data


def extract_panel(data, destination, version):
    total_size = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                parts = PurePosixPath(member.filename).parts
                if member.is_dir() or len(parts) < 3 or parts[1] != PANEL:
                    continue
                relative = parts[2:]
                if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part) for part in relative):
                    raise ValueError("The Image Model Manager plugin contains an invalid file path")
                total_size += member.file_size
                if total_size > MAX_PACKAGE_SIZE:
                    raise ValueError("The Image Model Manager plugin package is too large")
                path = destination.joinpath(*relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                content = archive.read(member)
                if path.suffix == ".py":
                    compile(content, str(path), "exec")
                with path.open("xb") as stream:
                    stream.write(content)
    except (FileExistsError, SyntaxError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError("The Image Model Manager plugin package is invalid") from exc

    if not all((destination / name).is_file() for name in REQUIRED_FILES):
        raise ValueError("The Image Model Manager plugin package is incomplete")
    if read_version((destination / VERSION_FILE).read_bytes()) != version:
        raise ValueError("The Image Model Manager plugin version changed during download. Try again.")


def download_update(local_version, destination):
    remote_version = read_version(fetch(VERSION_URL, MAX_VERSION_SIZE))
    if local_version == remote_version:
        return False
    extract_panel(fetch(ARCHIVE_URL, MAX_PACKAGE_SIZE), destination, remote_version)
    return True
