from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from access_info import DEFAULT_WEBUI_PORT, discovery_environment


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "Data/Runtime/Services"
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com\b", re.I)
_owned_process: subprocess.Popen[bytes] | None = None


class QuickTunnelError(RuntimeError):
    pass


def _start_ticks(pid: int) -> str:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat[stat.rfind(") ") + 2 :].split()
        return fields[19] if fields[0] != "Z" else ""
    except (OSError, IndexError):
        return ""


def _state_path() -> Path:
    return STATE_DIR / "quick-tunnel.json"


def status() -> dict[str, object] | None:
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        pid = int(state["pid"])
        ticks = str(state["start_ticks"])
        if pid <= 1 or not ticks or _start_ticks(pid) != ticks:
            return None
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if not command or not any(
            Path(os.fsdecode(arg)).name.startswith("cloudflared") for arg in command[:2] if arg
        ):
            return None
        if b"tunnel" not in command or b"--url" not in command:
            return None
        url = str(state["url"])
        if not URL_PATTERN.fullmatch(url):
            return None
        return {"url": url, "pid": pid, "port": int(state["port"])}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


@contextmanager
def _locked():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "quick-tunnel.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _port() -> int:
    values = discovery_environment()
    try:
        port = int(values.get("EVERSPARK_WEBUI_PORT", DEFAULT_WEBUI_PORT))
    except ValueError as exc:
        raise QuickTunnelError("EVERSPARK_WEBUI_PORT must be a valid port") from exc
    if not 1 <= port <= 65535:
        raise QuickTunnelError("EVERSPARK_WEBUI_PORT must be between 1 and 65535")
    return port


def _log_path() -> Path:
    values = discovery_environment()
    path = Path(values.get("EVERSPARK_LOG_DIR", "Data/Logs")).expanduser()
    return (path if path.is_absolute() else REPO_ROOT / path) / "tunnel/quick-tunnel.log"


def _local_ready(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return response.status == 200
    except (OSError, URLError, HTTPError, TimeoutError):
        return False


def start() -> dict[str, object]:
    global _owned_process
    with _locked():
        active = status()
        if active:
            return active
        port = _port()
        if not _local_ready(port):
            raise QuickTunnelError("WebUI is not ready; run ./everspark start first")
        binary = shutil.which("cloudflared")
        if not binary:
            installer = REPO_ROOT / "Infrastructure/Network/cloudflared.sh"
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; core_cloudflared_install', "installer", str(installer)],
                check=False,
            )
            if result.returncode:
                raise QuickTunnelError("Could not install cloudflared; install it and retry")
            binary = shutil.which("cloudflared")
        if not binary:
            raise QuickTunnelError("cloudflared was installed but is not on PATH")
        if any((Path.home() / ".cloudflared" / name).exists() for name in ("config.yaml", "config.yml")):
            raise QuickTunnelError("Quick Tunnel cannot run with ~/.cloudflared/config.yaml or config.yml; move it aside temporarily")

        log = _log_path()
        log.parent.mkdir(parents=True, exist_ok=True)
        log.touch()
        log.chmod(0o600)
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [binary, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _owned_process = process
        ticks = _start_ticks(process.pid)
        try:
            if not ticks:
                raise QuickTunnelError(f"Cloudflare process exited immediately; check {log}")
            for _ in range(60):
                if process.poll() is not None:
                    break
                match = URL_PATTERN.search(log.read_text(encoding="utf-8", errors="replace"))
                if match:
                    state = {"pid": process.pid, "start_ticks": ticks, "url": match.group(), "port": port}
                    _state_path().write_text(json.dumps(state) + "\n", encoding="utf-8")
                    _state_path().chmod(0o600)
                    return {"url": state["url"], "pid": process.pid, "port": port}
                time.sleep(0.5)
            raise QuickTunnelError(f"Cloudflare did not provide a link; check {log}")
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            _owned_process = None
            raise


def stop() -> bool:
    global _owned_process
    with _locked():
        active = status()
        if not active:
            _state_path().unlink(missing_ok=True)
            return False
        pid = int(active["pid"])
        ticks = _start_ticks(pid)
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if _start_ticks(pid) != ticks:
                break
            time.sleep(0.1)
        else:
            raise QuickTunnelError("Quick Tunnel did not stop; inspect its process before retrying")
        if _owned_process is not None and _owned_process.pid == pid:
            _owned_process.wait(timeout=5)
            _owned_process = None
        _state_path().unlink(missing_ok=True)
        return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage an optional temporary Cloudflare WebUI link")
    parser.add_argument("action", nargs="?", choices=("start", "status", "stop"), default="start")
    args = parser.parse_args()
    try:
        if args.action == "start":
            info = start()
            print(f"Temporary WebUI link: {info['url']}")
            print("Public link: anyone with this URL can use this WebUI. Stop it with ./everspark share stop.")
        elif args.action == "stop":
            print("Temporary link stopped" if stop() else "No temporary link is running")
        else:
            info = status()
            print(f"Temporary WebUI link: {info['url']}" if info else "No temporary link is running")
    except (OSError, QuickTunnelError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
