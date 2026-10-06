"""Read-only service probes use a separate Agent lane, never the task journal."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


def probe(forge):
    if forge == "audio":
        # Reuse Audio Forge's actual runtime/GPU/model checks without waiting for synthesis.
        result = subprocess.run([str(ROOT / "Data/Runtime/audio-venv/bin/python"),
            str(ROOT / "Legate/Forge/AudioForge/remote_task.py"), "health", "{}"],
            cwd=ROOT, capture_output=True, text=True, timeout=7)
        return json.loads(result.stdout) if result.returncode == 0 else {"ok": False}
    if forge == "concept":
        url = "http://127.0.0.1:11434/api/tags"
    elif forge == "image":
        backend = os.environ.get("EVERSPARK_IMAGE_BACKEND", "comfyui").lower()
        if backend == "comfyui":
            url = os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/") + "/system_stats"
        elif backend == "diffusers":
            url = os.environ.get("EVERSPARK_DIFFUSERS_URL", "http://127.0.0.1:8190").rstrip("/") + "/health"
        else:
            return {"ok": False}
    else:
        raise ValueError("Unknown Forge")
    with urlopen(url, timeout=3) as response:
        value = json.load(response)
        return {"ok": response.status == 200 and isinstance(value, dict)}


class ProbeChannel:
    def __init__(self, registration):
        self.registration = registration
        self.stop = threading.Event()
        self.slots = threading.BoundedSemaphore(3)
        self.thread = threading.Thread(target=self.run, daemon=True, name="forge-probes")

    def run(self):
        from .transport import BridgeError
        while not self.stop.is_set():
            authentication = self.registration.authentication()
            if not authentication:
                self.stop.wait(1)
                continue
            if not self.slots.acquire(timeout=1):
                continue
            dispatched = False
            try:
                task = self.registration.transport.request("/node/probe/next", authentication)
                if not task:
                    continue
                # This lane may never execute deployments, synthesis, or mutations.
                if task.get("action") != "probe":
                    continue
                worker = threading.Thread(target=self.finish, args=(authentication, task), daemon=True)
                worker.start()
                dispatched = True
            except BridgeError as exc:
                if exc.status == 403:
                    self.registration.invalidate(authentication)
                self.stop.wait(1)
            except (OSError, ValueError, KeyError, RuntimeError):
                self.stop.wait(1)
            finally:
                if not dispatched:
                    self.slots.release()

    def finish(self, authentication, task):
        from .executor.tasks import execute
        try:
            result = execute("probe", task.get("message", ""), task["forge"])
            self.registration.transport.request("/node/result", {**authentication,
                "task_id": task["id"], "result": result})
        except (OSError, ValueError, KeyError, RuntimeError):
            pass  # The host reports an unverified probe rather than successful health.
        finally:
            self.slots.release()

    def close(self):
        self.stop.set()
        if self.thread.ident:
            self.thread.join(30)


if __name__ == "__main__":
    try:
        print(json.dumps(probe(sys.argv[1])))
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}))
