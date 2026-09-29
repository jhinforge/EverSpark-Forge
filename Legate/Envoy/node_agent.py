"""Pod-side Agent: register and pull allowlisted Forge tasks over a private proxy."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import time
from pathlib import Path


REPO = Path("/workspace/EverSpark-Forge")
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 1055


def request(url: str, path: str, body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    connection = http.client.HTTPConnection(PROXY_HOST, PROXY_PORT, timeout=25)
    try:
        connection.request("POST", url + path, body=payload,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read(8192))
        if response.status != 200:
            raise BridgeError(response.status)
        return data
    finally:
        connection.close()


def execute(action: str, message: str) -> dict:
    if action == "deploy":
        args, timeout = ["bash", str(REPO / "Legate/Forge/ConceptForge/Scripts/deploy.sh")], 1800
    elif action == "update":
        args, timeout = ["bash", str(REPO / "Legate/Envoy/update_source.sh")], 1800
    elif action == "revision":
        args, timeout = ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], 30
    elif action == "discuss" and isinstance(message, str) and 1 <= len(message.strip()) <= 500:
        args, timeout = ["python3", str(REPO / "Legate/Forge/ConceptForge/verify.py"),
                         message.strip()], 240
    else:
        return {"status": "failed", "output": "Unknown Node Agent task", "exit_code": 2}
    try:
        done = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL)
        output = done.stdout if done.returncode == 0 else (done.stderr or done.stdout)
        return {"status": "completed" if done.returncode == 0 else "failed",
                "output": output[-4000:], "exit_code": done.returncode}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "output": "Forge task timed out", "exit_code": 124}
    except OSError as exc:
        return {"status": "failed", "output": type(exc).__name__, "exit_code": 1}


def run():
    url = os.environ["EVERSPARK_NODE_BRIDGE_URL"].rstrip("/")
    instance_id = int(os.environ["CONTAINER_ID"])
    bootstrap = os.environ.pop("EVERSPARK_NODE_BOOTSTRAP")
    while True:
        try:
            session = request(url, "/node/register", {"instance_id": instance_id,
                                                        "bootstrap": bootstrap})["session"]
            break
        except (OSError, ValueError, KeyError, RuntimeError):
            time.sleep(3)
    bootstrap = ""
    while True:
        try:
            task = request(url, "/node/next", {"instance_id": instance_id,
                                                "session": session})
            if not task:
                continue
            result = execute(task["action"], task.get("message", ""))
            # Retry a result submission without executing the Forge task twice.
            while True:
                try:
                    request(url, "/node/result", {"instance_id": instance_id,
                            "session": session, "task_id": task["id"], "result": result})
                    break
                except BridgeError as exc:
                    if exc.status == 409:  # The host already timed out this task.
                        break
                    time.sleep(3)
                except (OSError, ValueError, RuntimeError):
                    time.sleep(3)
        except (OSError, ValueError, KeyError, RuntimeError):
            time.sleep(3)


class BridgeError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"Node bridge returned HTTP {status}")
        self.status = status


if __name__ == "__main__":
    run()
