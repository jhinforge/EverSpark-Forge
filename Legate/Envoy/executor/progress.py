"""Thread-safe snapshot consumed by the independent heartbeat thread."""
import threading
import time

_lock = threading.Lock()
_current = None


def begin(task_id):
    global _current
    with _lock:
        _current = {"task_id": task_id, "stage": "executing", "started": time.monotonic()}


def stage(value):
    with _lock:
        if _current:
            _current.update(stage=value, started=time.monotonic())


def finish():
    global _current
    with _lock:
        _current = None


def snapshot():
    with _lock:
        if not _current:
            return None
        return {"task_id": _current["task_id"], "stage": _current["stage"],
                "elapsed_seconds": round(time.monotonic()-_current["started"], 1)}
