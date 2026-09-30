"""Preserved intent/result journal and conservative interrupted-task recovery."""
import hashlib
import json
import os
from pathlib import Path
from ..settings import TASK_JOURNAL
from .tasks import execute


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
        return {"status": "failed", "output": "Agent restarted during execution; outcome unknown",
                "exit_code": None}

    def save():
        journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = journal.with_name(journal.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), 0o600)
                handle.flush()
                os.fsync(handle.fileno())
                json.dump(entries, handle, ensure_ascii=False)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        temporary.replace(journal)

    entries[task_id] = {"fingerprint": fingerprint, "state": "running"}
    save()  # Fail closed: never execute if the intent could not be recorded.
    result = (executor or execute)(task["action"], task.get("message", ""), task.get("forge", "concept"))
    entries[task_id] = {"fingerprint": fingerprint, "state": "completed", "result": result}
    save()
    return result

