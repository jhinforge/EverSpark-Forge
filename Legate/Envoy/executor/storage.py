"""Atomic private journal publication with serialization before fsync."""
import json
import os


def save(journal, entries):
    journal.parent.mkdir(parents=True, exist_ok=True)
    temporary = journal.with_name(journal.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            json.dump(entries, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(journal)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
