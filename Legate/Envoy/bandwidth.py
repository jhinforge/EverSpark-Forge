"""One background download test per Node, independent of Forge execution."""
import hashlib
import io
import json
import math
import os
import platform
import secrets
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from .executor.storage import save
from .bandwidth_regions import discovery, RegionError

POLICY = 2

VERSION = "1.0.14"
CHECKSUMS = {
    "amd64": "89800767ac14085c78a20847ebea23340f6c14a78de0a15c2ac7db8b565c961f",
    "arm64": "75e51a2494d03cb35a92ddbf862b40571a25a1526f3cf3dfa8b1d5d7bc622bd9",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def _read(directory):
    try:
        value = json.loads((Path(directory) / "bandwidth.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _alive(value):
    if value.get("status") not in {"pending", "running"}:
        return False
    try:
        pid = value.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists() and stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            return False
        return time.time() - value.get("created", 0) < 240
    except (OSError, TypeError):
        return False


def snapshot(directory):
    value = _read(directory)
    if value.get("status") in {"pending", "running"} and not _alive(value):
        value = {"status": "failed", "error": "Download test interrupted; retry", "finished_at": now()}
    return {key: item for key, item in value.items() if key not in {"pid", "created", "run_id"}}


def start(directory, force=False):
    # Automatic tests are for Linux worker Nodes; Windows remains the controller.
    if sys.platform != "linux" or os.environ.get("EVERSPARK_NODE_BANDWIDTH") == "0":
        return {}
    import fcntl
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with (directory / "bandwidth.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return snapshot(directory)
            value = _read(directory)
            if value and (_alive(value) or (not force and value.get("policy") == POLICY)):
                return snapshot(directory)
            run_id = secrets.token_hex(16)
            with (directory / "bandwidth.log").open("ab") as log:
                # The child only needs its private directory, never join/API credentials.
                env = {key: item for key, item in os.environ.items()
                       if not key.startswith("EVERSPARK_")}
                process = subprocess.Popen([sys.executable, "-m", "Legate.Envoy.bandwidth", str(directory), run_id],
                    cwd=Path(__file__).resolve().parents[2], env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True)
            save(directory / "bandwidth.json", {"status": "pending", "pid": process.pid,
                 "run_id": run_id, "created": time.time(), "started_at": now(), "policy": POLICY})
        return snapshot(directory)
    except OSError:
        return {"status": "failed", "error": "Could not start download test"}


def install(directory):
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if not architecture:
        raise ValueError("Unsupported download test architecture")
    binary = Path(directory) / ("librespeed-cli-" + VERSION)
    # A verified binary plus its local hash avoids trusting an unversioned PATH tool.
    marker = binary.with_suffix(".sha256")
    if binary.is_file() and marker.is_file() and hashlib.sha256(binary.read_bytes()).hexdigest() == marker.read_text():
        return binary
    url = (f"https://github.com/librespeed/speedtest-cli/releases/download/v{VERSION}/"
           f"librespeed-cli_{VERSION}_linux_{architecture}.tar.gz")
    with build_opener(ProxyHandler({})).open(Request(url), timeout=20) as response:
        archive = response.read(12 * 1024 * 1024 + 1)
    if len(archive) > 12 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != CHECKSUMS[architecture]:
        raise ValueError("Download tool checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        member = next((item for item in source.getmembers()
                       if item.isfile() and Path(item.name).name == "librespeed-cli"), None)
        if not member or member.size > 30 * 1024 * 1024:
            raise ValueError("Download tool archive invalid")
        data = source.extractfile(member).read()
    temporary = binary.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.chmod(0o700)
    temporary.replace(binary)
    marker.write_text(hashlib.sha256(data).hexdigest())
    return binary


def parse_result(output):
    values = json.loads(output)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError("No download result")
    result = values[0]
    speed, received = result.get("download"), result.get("bytes_received")
    # LibreSpeed v1.0.14 JSON uses decimal Mbps, NOT bits/s or MB/s.
    if (isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or speed < 0
            or isinstance(received, bool) or not isinstance(received, int) or received <= 0):
        raise ValueError("Invalid download measurement")
    server = result.get("server")
    if not isinstance(server, dict) or not isinstance(server.get("name"), str) or not isinstance(server.get("url"), str):
        raise ValueError("Missing download test server")
    return {"status": "completed", "download_mb_s": speed / 8,
            "threshold_mb_s": 50, "qualified": speed >= 400,
            "server_name": server["name"][:300], "server_url": server["url"][:300]}


def run(directory, run_id):
    import fcntl
    directory = Path(directory)
    with (directory / "bandwidth.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = _read(directory)
        if value.get("run_id") != run_id:
            return
        try:
            # Stagger automatic workers instead of starting all new Pods together.
            time.sleep(secrets.randbelow(10))
            binary = install(directory)
            location, servers = discovery()
            value.update(location, status="running")
            local_servers = directory / "bandwidth-servers.json"
            save(local_servers, servers)
            save(directory / "bandwidth.json", value)
            done = subprocess.run([str(binary), "--no-upload", "--no-icmp", "--duration", "30",
                "--concurrent", "3", "--timeout", "5", "--secure", "--json",
                "--telemetry-level", "disabled", "--local-json", str(local_servers)], capture_output=True, text=True,
                stdin=subprocess.DEVNULL, timeout=90, check=True)
            measured = parse_result(done.stdout)
            chosen = next((server for server in servers
                           if server.get("server", "").rstrip("/") == measured["server_url"].rstrip("/")), None)
            if not chosen:
                raise RegionError("Speed test server region could not be verified")
            measured.update(location, server_region=location["region"])
        except RegionError as exc:
            measured = {"status": "failed", "error": str(exc)}
        except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError, StopIteration):
            measured = {"status": "failed", "error": "Download test unavailable or interrupted; retry"}
        (directory / "bandwidth-servers.json").unlink(missing_ok=True)
        value.update(measured, finished_at=now())
        save(directory / "bandwidth.json", value)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    run(Path(sys.argv[1]), sys.argv[2])
