"""Thread-safe snapshot consumed by the independent heartbeat thread."""
import threading
import time

_lock = threading.Lock()
_current = None


def begin(task_id):
    global _current
    with _lock:
        _current = {"task_id": task_id, "stage": "executing", "started": time.monotonic()}


def stage(value, completed=None, total=None):
    with _lock:
        if _current:
            if _current["stage"] != value:
                _current.update(stage=value, started=time.monotonic())
            _current.pop("completed", None)
            _current.pop("total", None)
            if completed is not None and total is not None:
                _current.update(completed=completed, total=total)


def finish():
    global _current
    with _lock:
        _current = None


def snapshot():
    with _lock:
        if not _current:
            return None
        return {"task_id": _current["task_id"], "stage": _current["stage"],
                "elapsed_seconds": round(time.monotonic()-_current["started"], 1),
                **{key: _current[key] for key in ("completed", "total") if key in _current}}
