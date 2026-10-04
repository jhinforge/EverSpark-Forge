"""One background download test per Node, independent of Forge execution."""
import json
import math
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from .executor.storage import save

POLICY = 4
DOWNLOAD_URL = "https://speed.cloudflare.com/__down"
DURATION = 30
CONCURRENT = 3
REQUEST_BYTES = 10_000_000
READ_BYTES = 256 * 1024
TIMEOUT = 5


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


def measure(duration=DURATION, workers=CONCURRENT):
    """Count streamed payload bytes within one shared wall-clock window."""
    started = time.monotonic()
    deadline = started + duration
    lock = threading.Lock()
    received = 0
    colos = set()
    errors = []

    def download(worker):
        nonlocal received
        # Bypass the Agent's Tailscale proxy: measure the Pod's public egress.
        opener = build_opener(ProxyHandler({}))
        failures = 0
        while time.monotonic() < deadline:
            try:
                # Keep each request at the 10 MB size verified on worker Pods;
                # larger requests and urllib's default User-Agent can return 403.
                # Repeat downloads for the shared window, without extra URL parameters.
                request = Request(f"{DOWNLOAD_URL}?bytes={REQUEST_BYTES}",
                                  headers={"User-Agent": "curl/8.5.0",
                                           "Accept-Encoding": "identity", "Cache-Control": "no-cache"})
                with opener.open(request, timeout=max(.1, min(TIMEOUT, deadline-time.monotonic()))) as response:
                    if response.status != 200:
                        raise ValueError(f"Unexpected HTTP status {response.status}")
                    if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
                        raise ValueError("Compressed test response cannot measure payload bandwidth")
                    content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
                    if content_type != "application/octet-stream":
                        raise ValueError(f"Unexpected download content type {content_type}")
                    colo = response.headers.get("CF-Ray", "").rsplit("-", 1)[-1]
                    if re.fullmatch(r"[A-Z]{3}", colo):
                        with lock:
                            colos.add(colo)
                    request_received = 0
                    while time.monotonic() < deadline:
                        # read1 avoids waiting for a full buffer on a slow link.
                        chunk = response.read1(READ_BYTES)
                        if not chunk:
                            break
                        if time.monotonic() >= deadline:
                            break
                        with lock:
                            received += len(chunk)
                        request_received += len(chunk)
                    if not request_received and time.monotonic() < deadline:
                        raise ValueError("Download endpoint returned no payload")
                    failures = 0
            except (OSError, ValueError) as exc:
                if time.monotonic() >= deadline:
                    break
                error = f"{type(exc).__name__}: {exc}"
                print(f"[bandwidth] worker={worker} {error}", flush=True)
                with lock:
                    errors.append(error)
                failures += 1
                if failures >= 3:
                    break

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(download, range(workers)))
    elapsed = min(duration, time.monotonic()-started)
    if received <= 0 or elapsed < duration * .9:
        detail = errors[-1] if errors else "No sustained download sample"
        raise ValueError(f"Cloudflare download test unavailable: {detail}")
    speed = received / elapsed / 1_000_000
    if not math.isfinite(speed):
        raise ValueError("Invalid download measurement")
    edge = ", ".join(sorted(colos))
    result = {"status": "completed", "method": "cloudflare_http", "download_mb_s": speed,
              "bytes_received": received, "elapsed_seconds": elapsed,
              "threshold_mb_s": 50, "qualified": speed >= 50,
              "server_name": "Cloudflare" + (f" ({edge})" if edge else ""), "server_url": DOWNLOAD_URL}
    if edge:
        result["server_colo"] = edge
    return result


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
            value.update(status="running", policy=POLICY, method="cloudflare_http",
                         server_name="Cloudflare", server_url=DOWNLOAD_URL)
            save(directory / "bandwidth.json", value)
            print(f"[bandwidth] started run_id={run_id} source=Cloudflare duration={DURATION}s connections={CONCURRENT}", flush=True)
            measured = measure()
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
