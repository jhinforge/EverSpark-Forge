from __future__ import annotations

import json
import mimetypes
import os
import sys
import tempfile
import threading
import time
import zipfile
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "Runtime" / "Logging"))

from everspark_logging import EverSparkLogger, get_logger  # noqa: E402
from log_manifest import ManifestError, collect_log_status  # noqa: E402


LOG_DIR = Path(
    os.environ.get("EVERSPARK_LOG_DIR", str(REPO_ROOT / "Data" / "Logs"))
).expanduser()
if not LOG_DIR.is_absolute():
    LOG_DIR = REPO_ROOT / LOG_DIR
LOG_FILE = Path(
    os.environ.get("EVERSPARK_WEBUI_LOG", str(LOG_DIR / "webui/webui.log"))
).expanduser()
if not LOG_FILE.is_absolute():
    LOG_FILE = REPO_ROOT / LOG_FILE


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8780
    orchestrator_url: str = "http://127.0.0.1:8765"
    request_timeout: int = 600
    output_directory: Path = REPO_ROOT / "Data" / "Outputs"


def load_settings() -> Settings:
    output_directory = Path(
        os.environ.get("EVERSPARK_OUTPUT_DIR", str(REPO_ROOT / "Data" / "Outputs"))
    ).expanduser()
    if not output_directory.is_absolute():
        output_directory = (REPO_ROOT / output_directory).resolve()
    return Settings(
        host=os.environ.get("EVERSPARK_WEBUI_HOST", "127.0.0.1"),
        port=int(os.environ.get("EVERSPARK_WEBUI_PORT", "8780")),
        orchestrator_url=os.environ.get(
            "EVERSPARK_ORCHESTRATOR_URL", "http://127.0.0.1:8765"
        ).rstrip("/"),
        request_timeout=int(
            os.environ.get("EVERSPARK_WEBUI_REQUEST_TIMEOUT", "600")
        ),
        output_directory=output_directory,
    )


def request_json(
    url: str,
    timeout: int,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None
    method = "GET"
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("Upstream response must be a JSON object")
            return response.status, body
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"ok": False, "error": raw or f"HTTP {exc.code}"}
        if not isinstance(body, dict):
            body = {"ok": False, "error": f"HTTP {exc.code}"}
        return exc.code, body


class WebUIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        settings: Settings,
        logger: EverSparkLogger | None = None,
    ):
        super().__init__((settings.host, settings.port), RequestHandler)
        self.settings = settings
        self.logger = logger
        self.archive_lock = threading.Lock()


class RequestHandler(BaseHTTPRequestHandler):
    server: WebUIServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        routes = {
            "/api/health": self._health,
            "/api/runtime/status": self._runtime_status,
            "/api/resources": lambda: self._proxy_orchestrator_get(
                "/resources", parsed.query
            ),
            "/api/generate/jobs": lambda: self._proxy_orchestrator_get("/tasks/jobs", parsed.query),
            "/api/image/plugins": lambda: self._proxy_orchestrator_get("/image/plugins"),
            "/api/concept/connections": lambda: self._proxy_orchestrator_get("/concept/connections"),
            "/api/concept/connections/test/jobs": lambda: self._proxy_orchestrator_get(
                "/concept/connections/test/jobs", parsed.query),
            "/api/image/plugins/jobs": lambda: self._proxy_orchestrator_get("/image/plugins/jobs", parsed.query),
            "/api/storage/resources": lambda: self._proxy_orchestrator_get(
                "/storage/resources", parsed.query
            ),
            "/api/storage/scan": lambda: self._proxy_orchestrator_get("/storage/scan"),
            "/api/storage/jobs": lambda: self._proxy_orchestrator_get(
                "/storage/jobs", parsed.query
            ),
            "/api/backup/resources": lambda: self._proxy_orchestrator_get("/backup/resources"),
            "/api/backup/jobs": lambda: self._proxy_orchestrator_get("/backup/jobs", parsed.query),
            "/api/backup/restore-points": lambda: self._proxy_orchestrator_get("/backup/restore-points"),
            "/api/downloads/jobs": lambda: self._proxy_orchestrator_get(
                "/downloads/jobs", parsed.query
            ),
            "/api/subjects": lambda: self._proxy_orchestrator_get(
                "/subjects", parsed.query
            ),
            "/api/subjects/revisions": lambda: self._proxy_orchestrator_get(
                "/subjects/revisions", parsed.query
            ),
            "/api/subjects/bundle": lambda: self._proxy_orchestrator_get(
                "/subjects/bundle", parsed.query
            ),
            "/api/subjects/current": lambda: self._proxy_orchestrator_get(
                "/subjects/current", parsed.query
            ),
            "/api/conversation/history": lambda: self._proxy_orchestrator_get(
                "/memory/history", parsed.query
            ),
            "/api/results": lambda: self._results(parse_qs(parsed.query)),
            "/api/history": lambda: self._history(parse_qs(parsed.query)),
            "/api/image/view": lambda: self._proxy_image(parse_qs(parsed.query)),
            "/api/outputs/archive": self._output_archive,
            "/api/data/archive": self._data_archive,
        }
        if parsed.path in routes:
            routes[parsed.path]()
        elif parsed.path == "/":
            self._static("index.html")
        elif parsed.path.startswith("/static/"):
            self._static(parsed.path.removeprefix("/static/"))
        else:
            self._json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        upstream_paths = {
            "/api/image/plugins/install": "/image/plugins/install",
            "/api/image/plugins/enable": "/image/plugins/enable",
            "/api/image/plugins/default": "/image/plugins/default",
            "/api/concept/connections/save": "/concept/connections/save",
            "/api/concept/connections/test": "/concept/connections/test",
            "/api/concept/connections/remove": "/concept/connections/remove",
            "/api/concept/connections/default": "/concept/connections/default",
            "/api/subjects/generate": "/subjects/generate",
            "/api/subjects/update": "/subjects/update",
            "/api/subjects/revise": "/subjects/revise",
            "/api/subjects/select": "/subjects/select",
            "/api/subjects/compile": "/subjects/compile",
        }
        try:
            if path == "/api/data/import":
                self._data_import()
                return
            payload = self._read_json()
            if path == "/api/generate":
                self._generate(payload)
            elif path == "/api/generate/start":
                self._start_generation(payload)
            elif path == "/api/conversation":
                self._conversation(payload)
            elif path == "/api/conversation/clear":
                self._proxy_orchestrator_post("/memory/clear", payload)
            elif path == "/api/storage/scan":
                self._proxy_orchestrator_post("/storage/scan", payload)
            elif path == "/api/storage/pull":
                self._proxy_orchestrator_post("/storage/pull", payload)
            elif path == "/api/storage/paths":
                self._proxy_orchestrator_post("/storage/paths", payload)
            elif path == "/api/backup/upload":
                self._proxy_orchestrator_post("/backup/upload", payload)
            elif path == "/api/backup/restore":
                self._proxy_orchestrator_post("/backup/restore", payload)
            elif path == "/api/downloads":
                self._proxy_orchestrator_post("/downloads", payload)
            elif path == "/api/downloads/cancel":
                self._proxy_orchestrator_post("/downloads/cancel", payload)
            elif path == "/api/downloads/retry":
                self._proxy_orchestrator_post("/downloads/retry", payload)
            elif path in upstream_paths:
                self._proxy_orchestrator_post(upstream_paths[path], payload)
            else:
                self._json(404, {"ok": False, "error": "Not found"})
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Request body must be JSON"})
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except (URLError, TimeoutError) as exc:
            self._upstream_unavailable(exc)
        except Exception as exc:
            self._log(
                "error",
                "request.failed",
                "WebUI request failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._json(500, {"ok": False, "error": str(exc)})

    def _generate(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message", "")).strip()
        session_id = str(payload.get("session_id", "main")).strip()
        if not message:
            raise ValueError("Describe the scene before generating")
        request_payload = {
            "text": message,
            "session_id": session_id,
            "selection": payload.get("selection", {}),
        }
        self._proxy_orchestrator_post("/tasks", request_payload)

    def _start_generation(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message", "")).strip()
        session_id = str(payload.get("session_id", "main")).strip()
        if not message:
            raise ValueError("Describe the scene before generating")
        self._proxy_orchestrator_post("/tasks/start", {
            "text": message, "session_id": session_id,
            "selection": payload.get("selection", {}),
            "request_id": str(payload.get("request_id", "")),
        })

    def _conversation(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message", "")).strip()
        session_id = str(payload.get("session_id", "main")).strip()
        if not message:
            raise ValueError("Message cannot be empty")
        self._proxy_orchestrator_post(
            "/conversation",
            {
                "text": message,
                "session_id": session_id,
                "selection": payload.get("selection", {}),
                "request_id": uuid.uuid4().hex,
            },
        )

    def _proxy_orchestrator_get(self, path: str, query: str = "") -> None:
        url = f"{self.server.settings.orchestrator_url}{path}"
        if query:
            url += f"?{query}"
        try:
            status, body = request_json(url, self.server.settings.request_timeout)
            self._json(status, body)
        except (URLError, TimeoutError) as exc:
            self._upstream_unavailable(exc)

    def _proxy_orchestrator_post(
        self, path: str, payload: dict[str, Any]
    ) -> None:
        trace_id = str(payload.get("request_id", ""))
        started = time.monotonic()
        if path == "/conversation":
            self._log("info", "conversation.proxy.start", "WebUI forwarded conversation",
                      trace_id=trace_id)
        try:
            status, body = request_json(
                f"{self.server.settings.orchestrator_url}{path}",
                self.server.settings.request_timeout,
                payload,
            )
        except Exception as exc:
            if path == "/conversation":
                self._log("error", "conversation.proxy.failed", "WebUI proxy failed",
                          trace_id=trace_id, error_type=type(exc).__name__,
                          elapsed_ms=round((time.monotonic() - started) * 1000))
            raise
        if path == "/conversation":
            self._log("ok" if status < 400 else "error", "conversation.proxy.result",
                      "WebUI received conversation response", trace_id=trace_id,
                      http_status=status,
                      elapsed_ms=round((time.monotonic() - started) * 1000))
        self._json(status, body)

    def _health(self) -> None:
        self._json(200, {"ok": True, "services": self._collect_service_health()})

    def _collect_service_health(self) -> dict[str, dict[str, Any]]:
        checks = {
            "orchestrator": f"{self.server.settings.orchestrator_url}/health",
            "image_forge": f"{self.server.settings.orchestrator_url}/image/health",
        }
        services: dict[str, dict[str, Any]] = {}
        for name, url in checks.items():
            try:
                status, _ = request_json(url, self.server.settings.request_timeout)
                services[name] = {"online": 200 <= status < 300}
            except Exception as exc:
                services[name] = {
                    "online": False,
                    "error": type(exc).__name__,
                }
        return services

    def _runtime_status(self) -> None:
        services = self._collect_service_health()
        try:
            log_status = collect_log_status()
            logging_status = {
                "ready": True,
                "configured": log_status["configured"],
                "present": log_status["present"],
                "needs_rotation": log_status["needs_rotation"],
            }
        except (ManifestError, OSError) as exc:
            logging_status = {"ready": False, "error": type(exc).__name__}
        self._json(
            200,
            {
                "ok": True,
                "services": services,
                "logging": logging_status,
                "ready": all(item["online"] for item in services.values()),
            },
        )

    def _results(self, query: dict[str, list[str]]) -> None:
        prompt_ids = [item for item in query.get("prompt_id", []) if item]
        if not prompt_ids:
            self._json(400, {"ok": False, "error": "prompt_id is required"})
            return
        self._proxy_orchestrator_get("/image/results", urlencode(
            [("prompt_id", item) for item in prompt_ids]))

    def _history(self, query: dict[str, list[str]]) -> None:
        try:
            limit = max(1, min(100, int(query.get("limit", ["24"])[0])))
        except ValueError:
            self._json(400, {"ok": False, "error": "limit must be an integer"})
            return
        self._proxy_orchestrator_get("/image/history", urlencode({"limit": limit}))

    def _proxy_image(self, query: dict[str, list[str]]) -> None:
        filename = query.get("filename", [""])[0]
        subfolder = query.get("subfolder", [""])[0]
        folder_type = query.get("type", ["output"])[0]
        if not filename or filename.startswith("/") or ".." in filename:
            self._json(400, {"ok": False, "error": "Invalid filename"})
            return
        if subfolder.startswith("/") or ".." in subfolder:
            self._json(400, {"ok": False, "error": "Invalid subfolder"})
            return
        if folder_type != "output":
            self._json(400, {"ok": False, "error": "Invalid image type"})
            return
        upstream_query = urlencode(
            {"filename": filename, "subfolder": subfolder, "type": folder_type}
        )
        request = Request(
            f"{self.server.settings.orchestrator_url}/image/file?{upstream_query}",
            method="GET",
        )
        try:
            with urlopen(
                request, timeout=self.server.settings.request_timeout
            ) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header(
                    "Content-Type",
                    response.headers.get("Content-Type", "application/octet-stream"),
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "private, max-age=3600")
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as exc:
            self._json(exc.code, {"ok": False, "error": "Image not found"})
        except (URLError, TimeoutError) as exc:
            self._upstream_unavailable(exc, "Image Forge")

    def _data_archive(self) -> None:
        try:
            status, response = request_json(
                f"{self.server.settings.orchestrator_url}/data/archive",
                self.server.settings.request_timeout,
                {},
            )
        except (URLError, TimeoutError) as exc:
            self._upstream_unavailable(exc)
            return
        if status != 200 or not response.get("ok"):
            self._json(status, response)
            return
        archive_id = str(response.get("id", ""))
        if len(archive_id) != 32 or any(char not in "0123456789abcdef" for char in archive_id):
            self._json(502, {"ok": False, "error": "Invalid archive response"})
            return
        path = REPO_ROOT / "Data/Runtime/Archives" / f"everspark-data-{archive_id}.zip"
        response_started = False
        try:
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="EverSpark-Data-{archive_id}.zip"')
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            response_started = True
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        except OSError as exc:
            if not response_started:
                self._json(500, {"ok": False, "error": str(exc)})
        finally:
            path.unlink(missing_ok=True)

    def _data_import(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("ZIP upload size is invalid") from exc
        if length < 1 or length > 128 * 1024 * 1024:
            raise ValueError("ZIP upload must be between 1 byte and 128 MiB")
        imports = REPO_ROOT / "Data/Imports"
        imports.mkdir(parents=True, exist_ok=True)
        archive_id = uuid.uuid4().hex
        path = imports / f"{archive_id}.zip"
        try:
            remaining = length
            with path.open("xb") as output:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("ZIP upload was interrupted")
                    output.write(chunk)
                    remaining -= len(chunk)
            status, response = request_json(
                f"{self.server.settings.orchestrator_url}/data/import",
                self.server.settings.request_timeout,
                {"id": archive_id},
            )
            self._json(status, response)
        finally:
            path.unlink(missing_ok=True)

    def _output_archive(self) -> None:
        if not self.server.archive_lock.acquire(blocking=False):
            self._json(409, {"ok": False, "error": "An output archive is already being prepared"})
            return
        archive_path: Path | None = None
        response_started = False
        try:
            output_root = self.server.settings.output_directory.resolve()
            output_root.mkdir(parents=True, exist_ok=True)
            archive_root = REPO_ROOT / "Data" / "Runtime" / "Archives"
            archive_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix="everspark-outputs-",
                suffix=".zip",
                dir=archive_root,
                delete=False,
            ) as handle:
                archive_path = Path(handle.name)
            file_count = 0
            with zipfile.ZipFile(
                archive_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                archive.writestr("EverSpark-Outputs/", b"")
                for path in sorted(output_root.rglob("*")):
                    if path.is_symlink() or not path.is_file():
                        continue
                    relative = path.relative_to(output_root)
                    archive.write(path, (Path("EverSpark-Outputs") / relative).as_posix())
                    file_count += 1
            filename = f"EverSpark-Outputs-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}.zip"
            size = archive_path.stat().st_size
            self._log(
                "info",
                "outputs.archive.ready",
                "Output archive prepared",
                files=file_count,
                bytes=size,
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            response_started = True
            with archive_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        except (OSError, zipfile.BadZipFile) as exc:
            self._log(
                "error",
                "outputs.archive.failed",
                "Could not prepare output archive",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if not response_started:
                self._json(500, {"ok": False, "error": "Could not create output archive"})
        finally:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)
            self.server.archive_lock.release()

    def _static(self, relative_path: str) -> None:
        target = (STATIC_ROOT / relative_path).resolve()
        try:
            target.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self._json(403, {"ok": False, "error": "Forbidden"})
            return
        if not target.is_file():
            self._json(404, {"ok": False, "error": "Not found"})
            return
        body = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(target.name)
        self.send_response(200)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 1_000_000:
            raise ValueError("Request body size is invalid")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _upstream_unavailable(
        self, exc: Exception, service: str = "Orchestrator"
    ) -> None:
        self._log(
            "warning",
            "upstream.unavailable",
            "WebUI could not reach an upstream service",
            service=service,
            error_type=type(exc).__name__,
        )
        self._json(
            502,
            {
                "ok": False,
                "error": f"{service} is unavailable. Start it and try again.",
            },
        )

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _log(self, level: str, event: str, message: str, **fields: Any) -> None:
        if self.server.logger is not None:
            getattr(self.server.logger, level)(event, message, **fields)

    def log_message(self, format: str, *args: Any) -> None:
        self._log(
            "info",
            "http.access",
            "HTTP request completed",
            client=self.address_string(),
            request=format % args,
        )


def main() -> int:
    logger = get_logger("webui", LOG_FILE)
    server: WebUIServer | None = None
    try:
        settings = load_settings()
        server = WebUIServer(settings, logger)
        logger.ok(
            "server.ready",
            "EverSpark WebUI is ready",
            host=settings.host,
            port=server.server_port,
        )
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("server.stop.requested", "WebUI shutdown requested")
    except Exception as exc:
        logger.error(
            "server.failed",
            "WebUI server failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return 1
    finally:
        if server is not None:
            server.server_close()
            logger.ok("server.stopped", "EverSpark WebUI stopped")
        logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
