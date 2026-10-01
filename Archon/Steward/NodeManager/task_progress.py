"""Small, generic execution progress; no commands or credentials in heartbeats."""
import math
import re
from .errors import NodeError


def validate_progress(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NodeError("Invalid task progress", 400)
    task_id, stage, elapsed = value.get("task_id"), value.get("stage"), value.get("elapsed_seconds")
    if (not isinstance(task_id, str) or not re.fullmatch(r"[0-9a-f]{32}", task_id)
            or not isinstance(stage, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", stage)
            or isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed) or elapsed < 0):
        raise NodeError("Invalid task progress", 400)
    counts = {}
    if "completed" in value or "total" in value:
        completed, total = value.get("completed"), value.get("total")
        if (stage != "downloading_models" or type(completed) is not int or type(total) is not int
                or not 0 <= completed <= total <= 100000 or total < 1):
            raise NodeError("Invalid model download progress", 400)
        counts = {"completed": completed, "total": total}
    return {"task_id": task_id, "stage": stage, "elapsed_seconds": elapsed, **counts}
