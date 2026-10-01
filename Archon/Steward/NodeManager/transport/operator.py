"""Loopback-only Node administration, shared by Gate and standalone Node host."""
import ipaddress
from .server import NodeServer, NodeHandler
from ..errors import NodeError
from ..identity import validate_id


def local_request(handler):
    host = handler.headers.get("Host", "")
    allowed = {f"127.0.0.1:{handler.server.server_port}", f"localhost:{handler.server.server_port}"}
    origin = handler.headers.get("Origin")
    if not ipaddress.ip_address(handler.client_address[0]).is_loopback or host not in allowed or (origin and origin != f"http://{host}"):
        raise NodeError("Local origin required", 403)


def join(manager, body):
    if set(body)-{"ttl"}:
        raise NodeError("Invalid join request", 400)
    return {"join_token": manager.issue_join_token(body.get("ttl", 3600))}


def remove(manager, body):
    if set(body) != {"node_id"}:
        raise NodeError("Invalid remove request", 400)
    manager.remove(validate_id(body["node_id"]))
    return {}


def task(manager, body):
    if set(body)-{"node_id", "forge", "action", "message", "task_id", "timeout"} or not {"node_id", "action"} <= set(body):
        raise NodeError("Invalid task request", 400)
    timeout = body.get("timeout", 240)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3700:
        raise NodeError("Invalid task timeout", 400)
    return {"output": manager.execute(validate_id(body["node_id"]), body["action"], body.get("message", ""),
                                      timeout=timeout, forge=body.get("forge", "concept"), task_id=body.get("task_id"))}


POST_ROUTES = {"/nodes/join": join, "/nodes/remove": remove, "/nodes/task": task}


def handle(handler, manager, method, path):
    if path != "/nodes" and not path.startswith("/nodes/"):
        return False
    try:
        local_request(handler)
        if manager is None:
            raise NodeError("Node management unavailable", 503)
        if method == "GET" and path == "/nodes":
            value = {"nodes": manager.list_nodes()}
        elif method == "POST" and path in POST_ROUTES:
            value = POST_ROUTES[path](manager, NodeHandler.read_body(handler))
        else:
            raise NodeError("Not found", 404)
        handler._send(200, {"ok": True, **value})
    except NodeError as exc:
        handler._send(exc.status, {"ok": False, "error": str(exc)})
    except (ValueError, TypeError, KeyError, UnicodeError):
        handler._send(400, {"ok": False, "error": "Invalid Node request"})
    except (OSError, RuntimeError):
        handler._send(503, {"ok": False, "error": "Node state unavailable"})
    return True


class OperatorHandler(NodeHandler):
    def do_GET(self):
        if not handle(self, self.server.manager, "GET", self.path):
            self._send(404, {"error": "Not found"})

    def do_POST(self):
        if not handle(self, self.server.manager, "POST", self.path):
            self._send(404, {"error": "Not found"})


class OperatorServer(NodeServer):
    def __init__(self, address, manager):
        self.manager = manager
        # Operator API may never be exposed on the Agent listener.
        if address[0] != "127.0.0.1":
            raise ValueError("Operator server must bind loopback")
        from http.server import ThreadingHTTPServer
        ThreadingHTTPServer.__init__(self, address, OperatorHandler)
