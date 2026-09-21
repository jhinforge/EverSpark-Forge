from __future__ import annotations


def normalize_unicode(value: str) -> str:
    """Repair UTF-16 surrogate pairs produced by some browser terminals."""
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
