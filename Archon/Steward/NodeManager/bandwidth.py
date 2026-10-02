"""Bounded optional download measurements; never change Node admission."""
import math


def validate(value):
    if not isinstance(value, dict) or value.get("status") not in {"pending", "running", "completed", "failed"}:
        return None
    result = {"status": value["status"]}
    for key in ("started_at", "finished_at", "server_name", "server_url", "error"):
        if key in value:
            if not isinstance(value[key], str) or len(value[key]) > 300:
                return None
            result[key] = value[key]
    if value["status"] == "completed":
        speed = value.get("download_mb_s")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or speed < 0:
            return None
        result.update(download_mb_s=speed, threshold_mb_s=50, qualified=speed >= 50)
    return result
