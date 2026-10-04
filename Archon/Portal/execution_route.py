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
        execution = path.startswith("/api/") and not path.startswith("/api/machines/") and path != "/api/forge-bindings" and not path.startswith("/api/storage/config")
        if not bindings or not execution:
            return method(handler)
        with bindings.request() as url:
            if path in REQUIRED_NODES and bindings.bindings:
                states = bindings.status()["nodes"]
                try:
                    payload = handler._read_json()
                    if not isinstance(payload.get("selection", {}), dict):
                        raise ValueError("selection must be a JSON object")
                except (ValueError, UnicodeError) as exc:
                    handler._json(400, {"ok": False, "error": str(exc)})
                    return
                handler._execution_payload = payload
                provider = (payload.get("selection") or {}).get("concept_provider", "")
                if not provider:
                    application = getattr(getattr(bindings.runtime, "server", None), "application", None)
                    provider = application.concept.connections.gateway.default if application else "ollama"
                roles = REQUIRED_NODES[path]
                if path in {"/api/generate", "/api/generate/start"}:
                    mode = (payload.get("selection") or {}).get("creation_mode", "image")
                    if mode not in {"image", "audio", "image_audio", "plan"}:
                        handler._json(400, {"ok": False, "error": "Invalid generation mode"})
                        return
                    roles = ("concept", "audio") if mode == "audio" else ("concept", "image", "audio") if mode == "image_audio" else roles
                required = [role for role in roles if role != "concept" or provider == "ollama"]
                if not url or any(states.get(role) != "online" for role in required):
                    handler._json(503, {"ok": False, "error": "Selected Forge Node is offline. Wait for reconnection or select another ready machine."})
                    return
            handler._execution_url = url or handler.server.orchestrator_url
            try:
                return method(handler)
            finally:
                handler._execution_url = None
                handler._execution_payload = None
    return wrapped
