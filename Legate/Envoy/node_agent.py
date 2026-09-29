"""Pod-side Agent: register and pull allowlisted Forge tasks over a private proxy."""

from __future__ import annotations

import http.client
import hashlib
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from .forge_tasks import command


REPO = Path("/workspace/EverSpark-Forge")
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 1055
TASK_JOURNAL = Path("/workspace/everspark-agent-tasks.json")
STARTUP_STATUS = Path("/workspace/everspark-startup.status")


def startup_status(stage: str) -> None:
    try:
        STARTUP_STATUS.write_text(stage + "\n", encoding="utf-8")
    except OSError:
        pass  # Registration must still proceed when startup diagnostics are unavailable.


def request(url: str, path: str, body: dict) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    connection = http.client.HTTPConnection(PROXY_HOST, PROXY_PORT, timeout=25)
    try:
        connection.request("POST", url + path, body=payload,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(131073)
        if len(raw) > 131072:
            raise BridgeError(413)
        data = json.loads(raw)
        if response.status != 200:
            raise BridgeError(response.status)
        return data
    finally:
        connection.close()


def execute(action: str, message: str, forge: str = "concept") -> dict:
    if forge not in {"concept", "image"}:
        return {"status": "failed", "output": "Unknown Forge identity", "exit_code": 2}
    if action == "recover":
        if not isinstance(message, str) or len(message) != 32 or any(
            char not in "0123456789abcdef" for char in message
        ):
            return {"status": "failed", "output": "Invalid recovery task ID", "exit_code": 2}
        try:
            entry = json.loads(TASK_JOURNAL.read_text(encoding="utf-8")).get(message)
        except FileNotFoundError:
            entry = None
        except (OSError, ValueError, AttributeError):
            return {"status": "failed", "output": "Agent task journal unavailable", "exit_code": 1}
        result = entry.get("result", {}) if isinstance(entry, dict) else {}
        summary = {"state": (entry.get("state") if isinstance(entry, dict) else "not_seen"),
                   "status": result.get("status"), "output": str(result.get("output", ""))[-3000:],
                   "exit_code": result.get("exit_code")}
        return {"status": "completed", "output": json.dumps(summary), "exit_code": 0}
    selected = command(forge, action, message)
    if selected is None:
        return {"status": "failed", "output": "Unknown Node Agent task", "exit_code": 2}
    args, timeout = selected
    try:
        done = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL)
        output = done.stdout if done.returncode == 0 else (done.stderr or done.stdout)
        if len(output.encode("utf-8")) > 60000 and (action == "chat" or forge == "image"):
            return {"status": "failed", "output": "Forge response exceeds node task limit",
                    "exit_code": 1}
        return {"status": "completed" if done.returncode == 0 else "failed",
                "output": output if action == "chat" or forge == "image" else output[-4000:],
                "exit_code": done.returncode}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "output": "Forge task timed out", "exit_code": 124}
    except OSError as exc:
        return {"status": "failed", "output": type(exc).__name__, "exit_code": 1}


def execute_once(task: dict, journal: Path = TASK_JOURNAL) -> dict:
    """Never execute a fetched task twice, even after an Agent restart."""
    task_id = task["id"]
    if not isinstance(task_id, str) or len(task_id) != 32 or any(
        char not in "0123456789abcdef" for char in task_id
    ):
        raise ValueError("Invalid task identity")
    fingerprint = hashlib.sha256(json.dumps(
        [task.get("forge", "concept"), task["action"], task.get("message", "")], ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    try:
        entries = json.loads(journal.read_text(encoding="utf-8"))
    except FileNotFoundError:
        entries = {}
    if not isinstance(entries, dict):
        raise ValueError("Invalid Agent task journal")
    previous = entries.get(task_id)
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise ValueError("Task identity collision")
        if previous["state"] == "completed":
            return previous["result"]
        return {"status": "failed", "output": "Agent restarted during execution; outcome unknown",
                "exit_code": None}

    def save():
        journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = journal.with_name(journal.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(entries, handle, ensure_ascii=False)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(journal)

    entries[task_id] = {"fingerprint": fingerprint, "state": "running"}
    save()  # Fail closed: never execute if the intent could not be recorded.
    result = execute(task["action"], task.get("message", ""), task.get("forge", "concept"))
    entries[task_id] = {"fingerprint": fingerprint, "state": "completed", "result": result}
    save()
    return result


def run():
    url = os.environ["EVERSPARK_NODE_BRIDGE_URL"].rstrip("/")
    instance_id = int(os.environ["CONTAINER_ID"])
    bootstrap = os.environ.pop("EVERSPARK_NODE_BOOTSTRAP")
    runtime_id = secrets.token_hex(16)
    session = None
    registration_attempts = 0
    while True:
        if session is None:
            try:
                session = request(url, "/node/register", {"instance_id": instance_id,
                                                            "bootstrap": bootstrap,
                                                            "runtime_id": runtime_id})["session"]
                registration_attempts = 0
                startup_status("registered")
                print("[EverSpark] agent registered", flush=True)
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                registration_attempts += 1
                if registration_attempts == 1 or registration_attempts % 10 == 0:
                    reason = (f"HTTP {exc.status}" if isinstance(exc, BridgeError)
                              else type(exc).__name__)
                    startup_status("registration_failed:" + (f"http_{exc.status}" if isinstance(exc, BridgeError)
                                   else type(exc).__name__))
                    print(f"[EverSpark] registration attempt {registration_attempts} failed: {reason}",
                          flush=True)
                time.sleep(3)
                continue
        try:
            task = request(url, "/node/next", {"instance_id": instance_id,
                                                "session": session})
            if not task:
                continue
            try:
                result = execute_once(task)
            except (OSError, ValueError, KeyError) as exc:
                result = {"status": "failed", "output": f"Agent task journal error: {type(exc).__name__}",
                          "exit_code": None}
            # Retry a result submission without executing the Forge task twice.
            while True:
                try:
                    request(url, "/node/result", {"instance_id": instance_id,
                            "session": session, "task_id": task["id"], "result": result})
                    break
                except BridgeError as exc:
                    if exc.status == 409:  # The host already timed out this task.
                        break
                    if exc.status == 403:  # Archon lost or rotated this session.
                        session = None
                        break
                    time.sleep(3)
                except (OSError, ValueError, RuntimeError):
                    time.sleep(3)
        except BridgeError as exc:
            if exc.status == 403:
                session = None
            time.sleep(3)
        except (OSError, ValueError, KeyError, RuntimeError):
            time.sleep(3)


class BridgeError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"Node bridge returned HTTP {status}")
        self.status = status


if __name__ == "__main__":
    run()
