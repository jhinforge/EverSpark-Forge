"""Version 2 Agent protocol; no machine-provider fields in request identities."""
from ..errors import NodeError

ROUTES = {
    "/node/register": lambda m, b: m.registration.register(b),
    "/node/heartbeat": lambda m, b: m.heartbeat.receive(b),
    "/node/next": lambda m, b: m.tasks.next_task(b),
    "/node/result": lambda m, b: m.tasks.finish(b),
}


def dispatch(manager, path, body):
    if body.get("protocol_version") != 2:
        raise NodeError("Node protocol_version 2 required; update Agent", 400)
    route = ROUTES.get(path)
    if route is None:
        raise NodeError("Not found", 404)
    return route(manager, body) or {}
