"""Pin the selected remote runtime for the duration of a Portal request."""
from functools import wraps
from urllib.parse import urlsplit

REQUIRED_NODES = {"/api/generate": ("concept", "image"),
                  "/api/generate/start": ("concept", "image"),
                  "/api/conversation": ("concept",)}


def execution_request(method):
    @wraps(method)
    def wrapped(handler):
        path = urlsplit(handler.path).path
        bindings = handler.server.forge_bindings
        execution = path.startswith("/api/") and not path.startswith("/api/machines/") and path != "/api/forge-bindings"
        if not bindings or not execution:
            return method(handler)
        with bindings.request() as url:
            if url and path in REQUIRED_NODES:
                states = bindings.status()["nodes"]
                if any(states.get(role) != "online" for role in REQUIRED_NODES[path]):
                    handler._json(503, {"ok": False, "error": "Selected Forge Node is offline. Wait for reconnection or select another ready machine."})
                    return
            handler._execution_url = url or handler.server.orchestrator_url
            try:
                return method(handler)
            finally:
                handler._execution_url = None
    return wrapped
