"""Restart an unexpectedly terminated Agent; explicit supervisor stop stays stopped."""
import os
import json
from .settings import DATA_DIR
import signal
import subprocess
import sys
import threading


def run():
    stopping = threading.Event()
    child = None
    def stop(signum, frame):
        stopping.set()
        if child and child.poll() is None:
            child.terminate()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    while not stopping.is_set():
        child = subprocess.Popen([sys.executable, "-m", "Legate.Envoy.node_agent"], env=os.environ.copy())
        DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        status = DATA_DIR / "supervisor.json"
        temporary = status.with_name(status.name + ".tmp")
        temporary.write_text(json.dumps({"supervisor_pid": os.getpid(), "agent_pid": child.pid}))
        temporary.replace(status)
        child.wait()
        if stopping.is_set() or child.returncode == 0:
            return
        print(f"[EverSpark] Agent exited ({child.returncode}); restarting in 3 seconds", flush=True)
        if stopping.wait(3):
            return


if __name__ == "__main__":
    run()
