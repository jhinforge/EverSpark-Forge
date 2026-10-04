"""One background download test per Node, independent of Forge execution."""
import json
import math
import traceback
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from Legate.Crucible.Models.model_manager import load_specs

from .executor.storage import save

POLICY = 5
DURATION = 30


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


def download_source():
    """Reuse the managed Image Forge model source; never invoke model installation."""
    spec = next((spec for spec in load_specs() if spec.id == "image-default"), None)
    if spec is None:
        raise ValueError("Default Image Forge model source is unavailable")
    url = (f"https://huggingface.co/{quote(spec.repo_id, safe='/')}/resolve/"
           f"{quote(spec.revision, safe='')}/{quote(spec.filename, safe='/')}")
    return {"method": "default_model_http", "server_name": "Hugging Face",
            "server_url": url, "model_filename": spec.filename}


def measure(duration=DURATION, source=None):
    """Use the curl request verified on Pods, counting bytes without writing files."""
    source = source or download_source()
    started = time.monotonic()
    deadline = started + duration
    received = 0
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        process = subprocess.run([
            "curl", "--noproxy", "*", "-fL", "--silent", "--show-error",
            "--connect-timeout", "5", "--max-time", str(remaining),
            "-o", os.devnull, "-w", "%{http_code} %{time_total} %{size_download}",
            source["server_url"],
        ], stdin=subprocess.DEVNULL, capture_output=True, text=True,
           timeout=remaining + 5)
        try:
            status, transfer_time, size = process.stdout.strip().split()
            status, transfer_time, size = int(status), float(transfer_time), int(size)
        except (ValueError, TypeError) as exc:
            raise ValueError("curl did not return valid download statistics") from exc
        if status not in {200, 206}:
            raise ValueError(f"Default model download returned HTTP {status}")
        if (process.returncode not in {0, 28} or not math.isfinite(transfer_time)
                or transfer_time <= 0 or size <= 0):
            raise ValueError(f"Default model download failed (curl exit {process.returncode})")
        received += size
        if process.returncode == 28:
            # A timeout is expected only at the end of the sampling window;
            # connection / stalled partial downloads must never become a speed result.
            if time.monotonic() < deadline - .1:
                raise ValueError("Default model download timed out before the sample ended")
            break
        # A fast connection may finish the model; repeat to fill the same window.
    elapsed = time.monotonic() - started
    if received <= 0 or not duration * .9 <= elapsed <= duration + 5:
        raise ValueError("Default model download did not produce a sustained sample")
    speed = received / elapsed / 1_000_000
    if not math.isfinite(speed):
        raise ValueError("Invalid download measurement")
    return {**source, "status": "completed", "download_mb_s": speed,
            "bytes_received": received, "elapsed_seconds": elapsed,
            "threshold_mb_s": 50, "qualified": speed >= 50}


def run(directory, run_id):
    import fcntl
    directory = Path(directory)
    with (directory / "bandwidth.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = _read(directory)
        if value.get("run_id") != run_id:
            return
        try:
            time.sleep(secrets.randbelow(10))
            source = download_source()
            value.update(source, status="running", policy=POLICY)
            save(directory / "bandwidth.json", value)
            print(f"[bandwidth] started run_id={run_id} source=default_model duration={DURATION}s", flush=True)
            measured = measure(source=source)
            print(f"[bandwidth] completed speed={measured['download_mb_s']:.2f} MB/s bytes={measured['bytes_received']} elapsed={measured['elapsed_seconds']:.2f}s server={measured['server_name']}", flush=True)
        except Exception as exc:
            # Preserve the actual failure instead of silently replacing it with a
            # generic message. No credentials or IP lookup responses are logged.
            traceback.print_exc()
            measured = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}
        value.update(measured, finished_at=now())
        save(directory / "bandwidth.json", value)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    run(Path(sys.argv[1]), sys.argv[2])
