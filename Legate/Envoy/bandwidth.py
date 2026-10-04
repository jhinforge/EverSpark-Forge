"""One optional background network test per Node, independent of Forge execution."""
import json
import math
import platform
import shutil
import tarfile
import tempfile
import threading
import traceback
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .executor.storage import save

POLICY = 6
VERSION = "1.2.0"
TEST_TIMEOUT = 90
COOLDOWN = 20


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
        return time.time() - value.get("created", 0) < 360
    except (OSError, TypeError):
        return False


def snapshot(directory):
    value = _read(directory)
    if value.get("status") in {"pending", "running"} and not _alive(value):
        value = {"status": "failed", "error": "Download test interrupted; retry", "finished_at": now()}
    return {key: item for key, item in value.items() if key not in {"pid", "created", "run_id"}}


def terms_accepted(directory):
    try:
        record = json.loads((Path(directory) / "ookla-consent.json").read_text())
        return isinstance(record, dict) and record.get("version") == VERSION and record.get("accepted") is True
    except (OSError, ValueError):
        return False


def start(directory, force=False, accept_terms=False):
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
            if accept_terms is True:
                save(directory / "ookla-consent.json", {"version": VERSION, "accepted": True, "accepted_at": now()})
            value = _read(directory)
            if value and (_alive(value) or (not force and value.get("policy") == POLICY)):
                return snapshot(directory)
            if force and value.get("status") == "completed":
                try:
                    finished = datetime.fromisoformat(value["finished_at"]).timestamp()
                    if 0 <= time.time() - finished < COOLDOWN:
                        return snapshot(directory)
                except (KeyError, TypeError, ValueError):
                    pass
            run_id = secrets.token_hex(16)
            with (directory / "bandwidth.log").open("ab") as log:
                # The child only needs its private directory, never join/API credentials.
                env = {key: item for key, item in os.environ.items()
                       if not key.startswith("EVERSPARK_")}
                process = subprocess.Popen([sys.executable, "-m", "Legate.Envoy.bandwidth", str(directory), run_id],
                    cwd=Path(__file__).resolve().parents[2], env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=log, start_new_session=True)
                # Reap completed workers without blocking the Agent request loop.
                threading.Thread(target=process.wait, daemon=True).start()
            save(directory / "bandwidth.json", {"status": "pending", "pid": process.pid,
                 "run_id": run_id, "created": time.time(), "started_at": now(), "policy": POLICY, "method": "ookla_cli"})
        return snapshot(directory)
    except OSError:
        return {"status": "failed", "error": "Could not start download test"}


class TermsRequired(ValueError):
    pass


def cli(directory):
    """Use an official CLI or install a private copy from Ookla, never pip speedtest-cli."""
    architecture = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
    if architecture is None:
        raise ValueError("Unsupported architecture for Ookla CLI")
    directory = Path(directory)
    target = directory / f"ookla-speedtest-{VERSION}-{architecture}" / "speedtest"
    for candidate in [target, Path("/tmp/everspark-ookla-test/speedtest"), shutil.which("speedtest")]:
        if candidate and Path(candidate).is_file():
            try:
                version = subprocess.run([str(candidate), "--version"], stdin=subprocess.DEVNULL,
                                         capture_output=True, text=True, timeout=5)
                if version.returncode == 0 and "Ookla" in version.stdout and VERSION in version.stdout:
                    return Path(candidate)
            except (OSError, subprocess.TimeoutExpired):
                pass
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        archive = Path(temporary) / "speedtest.tgz"
        url = f"https://install.speedtest.net/app/cli/ookla-speedtest-{VERSION}-linux-{architecture}.tgz"
        process = subprocess.run(["curl", "-q", "--noproxy", "*", "-fL", "--silent", "--show-error",
                                  "--connect-timeout", "10", "--max-time", "60", "--max-filesize", "16777216",
                                  "-o", str(archive), url], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=65)
        if process.returncode != 0:
            raise ValueError(f"Could not download official Ookla CLI (curl exit {process.returncode})")
        with tarfile.open(archive, "r:gz") as package:
            # Extract only known regular files, without archive paths or symlinks.
            for name in ["speedtest", "speedtest.md", "speedtest.5"]:
                member = package.getmember(name)
                if not member.isfile() or not 0 < member.size <= 16 * 1024 * 1024:
                    raise ValueError("Invalid official Ookla CLI archive")
                content = package.extractfile(member)
                if content is None:
                    raise ValueError("Invalid official Ookla CLI archive")
                with content:
                    (Path(temporary) / name).write_bytes(content.read())
            executable = Path(temporary) / "speedtest"
            executable.chmod(0o700)
            for name in ["speedtest.md", "speedtest.5", "speedtest"]:
                os.replace(Path(temporary) / name, target.parent / name)
    return target


def finite(value, positive=False):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def parse_result(payload):
    """Keep only measurement fields: never persist IP, MAC, ISP or the raw result."""
    if not isinstance(payload, dict) or payload.get("type") != "result":
        raise ValueError("Ookla CLI returned no completed result")
    download, upload, ping, server = [payload.get(key) for key in ["download", "upload", "ping", "server"]]
    if not all(isinstance(item, dict) for item in [download, upload, ping, server]):
        raise ValueError("Ookla CLI result is incomplete")
    for transfer in [download, upload]:
        if (not finite(transfer.get("bandwidth")) or not finite(transfer.get("elapsed"), positive=True)
                or not isinstance(transfer.get("bytes"), int) or isinstance(transfer.get("bytes"), bool)
                or transfer["bytes"] <= 0):
            raise ValueError("Ookla CLI returned invalid transfer measurements")
    if not finite(ping.get("latency")):
        raise ValueError("Ookla CLI returned invalid latency")
    result = {"status": "completed", "method": "ookla_cli",
              "download_mb_s": download["bandwidth"] / 1_000_000,
              "upload_mb_s": upload["bandwidth"] / 1_000_000,
              "bytes_received": download["bytes"], "elapsed_seconds": download["elapsed"] / 1000,
              "latency_ms": ping["latency"], "threshold_mb_s": 50,
              "qualified": download["bandwidth"] >= 50_000_000}
    for source, destination in [("id", "server_id"), ("name", "server_name"),
                                ("location", "server_location"), ("country", "server_country")]:
        value = server.get(source)
        if source == "id":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("Ookla CLI returned an invalid server ID")
            result[destination] = value
        elif not isinstance(value, str) or not value or len(value) > 300:
            raise ValueError("Ookla CLI returned invalid server metadata")
        else:
            result[destination] = value
    for value, key in [(ping.get("jitter"), "jitter_ms"), (payload.get("packetLoss"), "packet_loss_percent")]:
        if value is not None:
            if not finite(value) or (key == "packet_loss_percent" and value > 100):
                raise ValueError("Ookla CLI returned invalid network measurements")
            result[key] = value
    return result


def measure(binary, accept_terms=False):
    """Let Ookla choose the server and test durations; retry once on execution failure."""
    for attempt in range(2):
        try:
            args = [str(binary), "--format=json", "--progress=no"]
            if accept_terms is True:
                args.extend(["--accept-license", "--accept-gdpr"])
            process = subprocess.run(args,
                                     stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                     timeout=TEST_TIMEOUT)
            # Acceptance flags are allowed only after explicit per-Pod confirmation.
            if process.returncode != 0 or not process.stdout.lstrip().startswith("{"):
                message = (process.stderr + " " + process.stdout).lower()
                if any(word in message for word in ["license", "gdpr", "eula", "privacy", "terms"]):
                    raise TermsRequired("Confirm Ookla CLI terms in WebUI before testing")
                try:
                    error = json.loads(process.stdout).get("message", "")
                except (ValueError, AttributeError):
                    error = ""
                raise ValueError(f"Ookla CLI failed (exit {process.returncode})" + (f": {str(error)[:160]}" if error else ""))
            result = parse_result(json.loads(process.stdout))
            print(f"[bandwidth] attempt={attempt+1} completed server={result['server_id']}", flush=True)
            return result
        except TermsRequired:
            raise
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"[bandwidth] attempt={attempt+1} {type(exc).__name__}: {exc}", flush=True)
            if attempt:
                raise
            time.sleep(2)


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
            value.update(status="running", policy=POLICY, method="ookla_cli")
            save(directory / "bandwidth.json", value)
            print(f"[bandwidth] started run_id={run_id} source=Ookla timeout={TEST_TIMEOUT}s attempts=2", flush=True)
            measured = measure(cli(directory), accept_terms=terms_accepted(directory))
            print(f"[bandwidth] completed speed={measured['download_mb_s']:.2f} MB/s bytes={measured['bytes_received']} elapsed={measured['elapsed_seconds']:.2f}s server={measured['server_name']}", flush=True)
        except Exception as exc:
            # Preserve the actual failure instead of silently replacing it with a
            # generic message. No credentials or IP lookup responses are logged.
            traceback.print_exc()
            measured = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
                        **({"error_code": "terms_required"} if isinstance(exc, TermsRequired) else {})}
        value.update(measured, finished_at=now())
        save(directory / "bandwidth.json", value)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(2)
    run(Path(sys.argv[1]), sys.argv[2])
