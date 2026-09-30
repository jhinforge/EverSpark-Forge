"""Explicit Node target, with the former provider-ID API as a compatibility path."""
import re
from urllib.parse import urlsplit


def target(identity, control_url):
    if urlsplit(control_url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Archon control URL must be local")
    if isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{32}", identity):
        return control_url.rstrip("/")+"/nodes/task", {"node_id": identity}
    if isinstance(identity, int) and not isinstance(identity, bool) and identity > 0:
        return control_url.rstrip("/")+"/machines/vast/forge-task", {"instance_id": identity}
    raise ValueError("Remote Forge requires an explicit Node identity")
