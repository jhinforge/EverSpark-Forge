from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..config.config import ConfigError, load_config
from .orchestrator import BusyError, Orchestrator

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Logging"))

from everspark_logging import EverSparkLogger, get_logger  # noqa: E402

LOG_DIR = Path(
    os.environ.get("EVERSPARK_LOG_DIR", str(REPO_ROOT / "Data" / "Logs"))
).expanduser()
if not LOG_DIR.is_absolute():
    LOG_DIR = REPO_ROOT / LOG_DIR
LOG_FILE = Path(
    os.environ.get("ORCHESTRATOR_LOG", str(LOG_DIR / "orchestrator.log"))
).expanduser()
if not LOG_FILE.is_absolute():
    LOG_FILE = REPO_ROOT / LOG_FILE


class OrchestratorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        orchestrator: Orchestrator,
        logger: EverSparkLogger | None = None,
    ):
        super().__init__(address, RequestHandler)
        self.orchestrator = orchestrator
        self.logger = logger


class RequestHandler(BaseHTTPRequestHandler):
    server: OrchestratorServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True, "status": "standby"})
        elif parsed.path == "/memory/history":
            session_id = parse_qs(parsed.query).get("session_id", [""])[0]
            if not session_id:
                self._send(400, {"ok": False, "error": "session_id is required"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "session_id": session_id,
                    "messages": self.server.orchestrator.get_history(session_id),
                },
            )
        else:
            self._send(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        if self.path not in {"/tasks", "/memory/clear"}:
            self._send(404, {"ok": False, "error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/tasks":
                result = self.server.orchestrator.submit(
                    str(payload.get("text", "")),
                    str(payload.get("session_id", "")),
                )
                self._send(200, result)
            else:
                session_id = str(payload.get("session_id", ""))
                self.server.orchestrator.clear_memory(session_id)
                self._send(200, {"ok": True, "session_id": session_id})
        except BusyError as exc:
            self._log("warning", "task.busy", "Task submission rejected because the service is busy")
            self._send(409, {"ok": False, "error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            self._log(
                "warning",
                "request.invalid",
                "Invalid Orchestrator request",
                error_type=type(exc).__name__,
            )
            self._send(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._log(
                "error",
                "request.failed",
                "Orchestrator request failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._send(500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        self._log(
            "info",
            "http.access",
            "HTTP request completed",
            client=self.address_string(),
            request=format % args,
        )

    def _log(self, level: str, event: str, message: str, **fields: Any) -> None:
        if self.server.logger is not None:
            getattr(self.server.logger, level)(event, message, **fields)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    logger = get_logger("orchestrator", LOG_FILE)
    server: OrchestratorServer | None = None
    try:
        config = load_config()
    except ConfigError as exc:
        logger.error(
            "config.invalid",
            "Orchestrator configuration is invalid",
            error=str(exc),
        )
        logger.close()
        return 1
    host = str(config["orchestrator"]["host"])
    port = int(config["orchestrator"]["port"])
    try:
        server = OrchestratorServer((host, port), Orchestrator(config), logger)
        logger.ok(
            "server.ready",
            "EverSpark Orchestrator is ready",
            host=host,
            port=port,
        )
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("server.stop.requested", "Orchestrator shutdown requested")
    except Exception as exc:
        logger.error(
            "server.failed",
            "Orchestrator server failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 1
    finally:
        if server is not None:
            server.server_close()
            logger.ok("server.stopped", "EverSpark Orchestrator stopped")
        logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
