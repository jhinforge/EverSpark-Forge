"""Existing allowlisted Forge execution; independent of registration."""
import json
import subprocess
from ..forge_tasks import command
from ..settings import REPO, TASK_JOURNAL
from .results import command_result
from .process import run_deployment


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
        if action == "deploy":
            return command_result(run_deployment(args, REPO, timeout), action)
        done = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL)
        return command_result(done, action)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "output": "Forge task timed out", "exit_code": 124}
    except OSError as exc:
        return {"status": "failed", "output": type(exc).__name__, "exit_code": 1}
