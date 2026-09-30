"""Loopback-only API for manual remote Forge connections."""
import json
from Archon.Steward.NodeManager.errors import NodeError
from Archon.Steward.NodeManager.transport.operator import local_request


def handle(handler, bindings, method, path):
    if path != "/forge-bindings":
        return False
    try:
        local_request(handler)
        if bindings is None:
            raise NodeError("Remote Forge connections are unavailable", 503)
        if method == "GET":
            result = bindings.status()
        else:
            if handler.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise NodeError("JSON request required", 415)
            length = int(handler.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise NodeError("Invalid selection request size", 400)
            result = bindings.select(json.loads(handler.rfile.read(length)))
        handler._send(200, {"ok": True, **result})
    except NodeError as exc:
        handler._send(exc.status, {"ok": False, "error": str(exc)})
    except (ValueError, TypeError, KeyError, UnicodeError):
        handler._send(400, {"ok": False, "error": "Invalid Forge Node selection"})
    except Exception as exc:
        handler._send(503, {"ok": False, "error": str(exc)})
    return True
