from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from concept_forge.subjects import SubjectValidationError
from everspark_memory import SubjectRevisionConflictError

from ..config.config import ConfigError, load_config
from .orchestrator import BusyError, Orchestrator, SubjectNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Infrastructure" / "Storage"))
from r2_manager import StorageError  # noqa: E402
from download_manager import DownloadError  # noqa: E402

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
        elif parsed.path == "/resources":
            self._send(
                200,
                {"ok": True, **self.server.orchestrator.resources()},
            )
        elif parsed.path == "/storage/resources":
            try:
                self._send(
                    200,
                    {"ok": True, **self.server.orchestrator.storage_resources()},
                )
            except StorageError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/storage/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send(
                200,
                {"ok": True, "job": self.server.orchestrator.storage_job(job_id)},
            )
        elif parsed.path == "/backup/resources":
            try:
                self._send(200, {"ok": True, **self.server.orchestrator.backup_resources()})
            except StorageError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/backup/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send(200, {"ok": True, "job": self.server.orchestrator.backup_job(job_id)})
        elif parsed.path == "/backup/restore-points":
            try:
                self._send(200, {"ok": True, "points": self.server.orchestrator.restore_points()})
            except StorageError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/downloads/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send(
                200,
                {"ok": True, "job": self.server.orchestrator.download_job(job_id)},
            )
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
        elif parsed.path == "/subjects/current":
            session_id = parse_qs(parsed.query).get("session_id", [""])[0]
            if not session_id:
                self._send(400, {"ok": False, "error": "session_id is required"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "session_id": session_id,
                    "document": self.server.orchestrator.get_session_subject(session_id),
                },
            )
        elif parsed.path == "/subjects":
            subject_id = parse_qs(parsed.query).get("subject_id", [""])[0]
            if subject_id:
                try:
                    document = self.server.orchestrator.get_subject(subject_id)
                except SubjectNotFoundError as exc:
                    self._send(404, {"ok": False, "error": str(exc)})
                    return
                self._send(
                    200,
                    {
                        "ok": True,
                        "document": document,
                    },
                )
            else:
                self._send(
                    200,
                    {
                        "ok": True,
                        "subjects": self.server.orchestrator.list_subjects(),
                    },
                )
        elif parsed.path == "/subjects/revisions":
            subject_id = parse_qs(parsed.query).get("subject_id", [""])[0]
            if not subject_id:
                self._send(400, {"ok": False, "error": "subject_id is required"})
                return
            try:
                revisions = self.server.orchestrator.get_subject_revisions(subject_id)
            except SubjectNotFoundError as exc:
                self._send(404, {"ok": False, "error": str(exc)})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "subject_id": subject_id,
                    "revisions": revisions,
                },
            )
        elif parsed.path == "/subjects/bundle":
            subject_id = parse_qs(parsed.query).get("subject_id", [""])[0]
            if not subject_id:
                self._send(400, {"ok": False, "error": "subject_id is required"})
                return
            try:
                bundle = self.server.orchestrator.subject_bundle(subject_id)
            except SubjectNotFoundError as exc:
                self._send(404, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True, "bundle": bundle})
        else:
            self._send(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        request_path = urlparse(self.path).path
        if request_path not in {
            "/tasks",
            "/conversation",
            "/memory/clear",
            "/subjects",
            "/subjects/generate",
            "/subjects/update",
            "/subjects/revise",
            "/subjects/select",
            "/subjects/compile",
            "/storage/pull",
            "/storage/paths",
            "/backup/upload",
            "/backup/restore",
            "/data/archive",
            "/data/import",
            "/downloads",
            "/downloads/cancel",
            "/downloads/retry",
        }:
            self._send(404, {"ok": False, "error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            if request_path == "/tasks":
                result = self.server.orchestrator.submit(
                    str(payload.get("text", "")),
                    str(payload.get("session_id", "")),
                    payload.get("selection"),
                )
                self._send(200, result)
            elif request_path == "/conversation":
                result = self.server.orchestrator.discuss(
                    str(payload.get("text", "")),
                    str(payload.get("session_id", "")),
                    payload.get("selection"),
                )
                self._send(200, result)
            elif request_path == "/memory/clear":
                session_id = str(payload.get("session_id", ""))
                self.server.orchestrator.clear_memory(session_id)
                self._send(200, {"ok": True, "session_id": session_id})
            elif request_path == "/subjects":
                document = payload.get("document")
                if not isinstance(document, dict):
                    raise ValueError("document must be a JSON object")
                saved = self.server.orchestrator.save_subject(document)
                self._send(201, {"ok": True, "document": saved})
            elif request_path == "/subjects/generate":
                subject_id = str(payload.get("subject_id", ""))
                text = str(payload.get("text", ""))
                generated = self.server.orchestrator.generate_subject(subject_id, text)
                self._send(201, {"ok": True, "document": generated})
            elif request_path == "/subjects/update":
                subject_id = str(payload.get("subject_id", ""))
                changes = payload.get("changes")
                if not isinstance(changes, dict):
                    raise ValueError("changes must be a JSON object")
                updated = self.server.orchestrator.update_subject(subject_id, changes)
                self._send(200, {"ok": True, "document": updated})
            elif request_path == "/subjects/revise":
                bundle = self.server.orchestrator.revise_subject_group(
                    str(payload.get("subject_id", "")),
                    str(payload.get("group", "")),
                    str(payload.get("instruction", "")),
                )
                self._send(200, {"ok": True, "bundle": bundle})
            elif request_path == "/subjects/select":
                subject = self.server.orchestrator.select_session_subject(
                    str(payload.get("session_id", "")), str(payload.get("subject_id", ""))
                )
                self._send(200, {"ok": True, "document": subject})
            elif request_path == "/storage/pull":
                job = self.server.orchestrator.start_storage_pull(
                    str(payload.get("kind", "")), str(payload.get("name", ""))
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/storage/paths":
                paths = self.server.orchestrator.save_storage_paths(payload.get("paths", {}))
                self._send(200, {"ok": True, "paths": paths})
            elif request_path == "/data/archive":
                archive_id = self.server.orchestrator.export_data_archive()
                self._send(200, {"ok": True, "id": archive_id})
            elif request_path == "/data/import":
                result = self.server.orchestrator.restore_data_archive(str(payload.get("id", "")))
                self._send(200, {"ok": True, **result})
            elif request_path == "/backup/upload":
                job = self.server.orchestrator.start_backup(
                    payload.get("names", []), payload.get("memory") is True,
                    payload.get("targets", {}), payload.get("outputs") is True,
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/backup/restore":
                job = self.server.orchestrator.start_restore(str(payload.get("id", "")))
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/downloads":
                job = self.server.orchestrator.start_download(
                    str(payload.get("kind", "")),
                    str(payload.get("url", "")),
                    str(payload.get("filename", "")),
                    str(payload.get("runtime_name", "")),
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/downloads/cancel":
                job = self.server.orchestrator.cancel_download(
                    str(payload.get("job_id", ""))
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/downloads/retry":
                job = self.server.orchestrator.retry_download(
                    str(payload.get("job_id", ""))
                )
                self._send(202, {"ok": True, "job": job})
            else:
                subject_id = str(payload.get("subject_id", ""))
                compiled = self.server.orchestrator.compile_subject(subject_id)
                self._send(200, {"ok": True, **compiled})
        except BusyError as exc:
            self._log(
                "warning",
                "task.busy",
                "Task submission rejected because the service is busy",
            )
            self._send(409, {"ok": False, "error": str(exc)})
        except SubjectRevisionConflictError as exc:
            self._log(
                "warning",
                "subject.revision.conflict",
                "Subject revision conflict",
                error=str(exc),
            )
            self._send(409, {"ok": False, "error": str(exc)})
        except SubjectNotFoundError as exc:
            self._send(404, {"ok": False, "error": str(exc)})
        except (StorageError, DownloadError) as exc:
            self._send(400, {"ok": False, "error": str(exc)})
        except (ValueError, SubjectValidationError, json.JSONDecodeError) as exc:
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
