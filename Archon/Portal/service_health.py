"""Keep probe uncertainty separate from confirmed service unavailability."""
import time


def record_health(history, key, result, now=None):
    now = time.time() if now is None else now
    previous = history.get(key, {})
    if result.get("reason") == "health_unverified" and result.get("source") == "unavailable":
        return result  # Unconfigured services have no meaningful failure count.
    successful = result.get("online") is True
    failures = 0 if successful else previous.get("consecutive_failures", 0) + 1
    last_success = now if successful else previous.get("last_success")
    value = {**result, "consecutive_failures": failures, "last_success": last_success}
    if not successful and failures < 2:
        value.update(online=False, status="checking", reason="probe_pending")
    history[key] = value
    # Avoid retaining former node selections indefinitely.
    if len(history) > 32:
        for old in list(history)[:-16]:
            history.pop(old, None)
    return value
