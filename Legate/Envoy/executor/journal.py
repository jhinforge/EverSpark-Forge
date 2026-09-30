"""Preserved intent/result journal and conservative interrupted-task recovery."""
import hashlib
import json
from pathlib import Path
from ..settings import TASK_JOURNAL
from .tasks import execute
from . import progress
from .storage import save


def execute_once(task: dict, journal: Path = TASK_JOURNAL, executor=None) -> dict:
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
        result = {"status": "failed", "output": "Agent restarted during execution; outcome unknown. Task was not automatically repeated; verify Forge health before retrying.",
                  "exit_code": None}
        entries[task_id] = {"fingerprint": fingerprint, "state": "completed", "result": result}
        save(journal, entries)
        return result

    entries[task_id] = {"fingerprint": fingerprint, "state": "running"}
    save(journal, entries)  # Fail closed: never execute if the intent could not be recorded.
    progress.begin(task_id)
    try:
        result = (executor or execute)(task["action"], task.get("message", ""), task.get("forge", "concept"))
    finally:
        progress.finish()
    entries[task_id] = {"fingerprint": fingerprint, "state": "completed", "result": result}
    save(journal, entries)
    return result

