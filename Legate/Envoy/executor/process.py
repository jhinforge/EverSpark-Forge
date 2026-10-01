"""Stream deployment phase markers and bound diagnostics without altering JSON tasks."""
import os
import re
import signal
import sys
import subprocess
import threading
from . import progress
from .results import DIAGNOSTIC_TAIL


def run_deployment(args, cwd, timeout):
    environment = {**os.environ, "EVERSPARK_DEPLOY_PROGRESS": "1"}
    managed_args = [sys.executable, "-m", "Legate.Envoy.executor.process_child", str(os.getpid()), *args] if os.name == "posix" else args
    process = subprocess.Popen(managed_args, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", stdin=subprocess.DEVNULL,
                               start_new_session=(os.name == "posix"))
    chunks = []
    def read():
        # Fixed-size reads avoid unbounded memory on a single long installation line.
        pending = ""
        while True:
            chunk = process.stdout.readline(512)
            if not chunk:
                break
            chunks.append(chunk)
            while sum(map(len, chunks)) > DIAGNOSTIC_TAIL * 2:
                chunks.pop(0)
            pending = (pending + chunk)[-2048:]
            lines = pending.split("\n")
            pending = lines.pop()
            for line in lines:
                match = re.fullmatch(r"\[EverSpark:deploy\] ([a-z][a-z0-9_]{0,63})(?: ([0-9]{1,6})/([0-9]{1,6}))?", line.strip())
                if match:
                    completed, total = match.group(2), match.group(3)
                    if completed is None:
                        progress.stage(match.group(1))
                    elif match.group(1) == "downloading_models" and 0 <= int(completed) <= int(total) <= 100000 and int(total) > 0:
                        progress.stage(match.group(1), int(completed), int(total))
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except BaseException as exc:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()
        reader.join(2)
        if isinstance(exc, subprocess.TimeoutExpired):
            exc.output = "".join(chunks)[-DIAGNOSTIC_TAIL:]
        raise
    finally:
        reader.join(2)
        if not reader.is_alive():
            process.stdout.close()
    done = subprocess.CompletedProcess(args, process.returncode, "".join(chunks)[-DIAGNOSTIC_TAIL:], "")
    done.stage = (progress.snapshot() or {}).get("stage")
    return done
