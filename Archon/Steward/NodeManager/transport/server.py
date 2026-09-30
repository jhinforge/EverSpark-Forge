"""HTTP framing, limits and errors; all Node behavior is delegated."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .protocol import dispatch
from ..errors import NodeError


class NodeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager):
        self.manager = manager
        super().__init__(address, NodeHandler)


class NodeHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(30)
        super().setup()

    def do_POST(self):
        try:
            self._send(200, dispatch(self.server.manager, self.path, self.read_body()))
        except (ValueError, TypeError, KeyError, UnicodeError):
            self._send(400, {"error": "Invalid Node request"})
        except NodeError as exc:
            self._send(exc.status, {"error": str(exc)})
        except (OSError, RuntimeError):
            self._send(503, {"error": "Node state storage unavailable"})

    def read_body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or not 0 < size <= 131072:
            raise NodeError("Invalid JSON request", 400)
        value = json.loads(self.rfile.read(size))
        if not isinstance(value, dict):
            raise NodeError("Invalid JSON request", 400)
        return value

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass
