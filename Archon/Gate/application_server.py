from __future__ import annotations

import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from concept_forge.port import ConceptError
from concept_forge.subjects import SubjectValidationError
from concept_forge.trace import trace_scope
from everspark_memory import SubjectRevisionConflictError

from Archon.Vault.runtime_config import ConfigError, load_config
from Aegis.Shared.errors import BusyError
from concept_forge.workspace import SubjectNotFoundError
from .application import GateApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Aegis" / "Storage"))
from r2_manager import StorageError  # noqa: E402
from download_manager import DownloadError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Aegis" / "Logging"))

from everspark_logging import EverSparkLogger, get_logger  # noqa: E402

LOG_DIR = Path(
    os.environ.get("EVERSPARK_LOG_DIR", str(REPO_ROOT / "Data" / "Logs"))
).expanduser()
if not LOG_DIR.is_absolute():
    LOG_DIR = REPO_ROOT / LOG_DIR
LOG_FILE = Path(
    os.environ.get("ORCHESTRATOR_LOG", str(LOG_DIR / "orchestrator/orchestrator.log"))
).expanduser()
if not LOG_FILE.is_absolute():
    LOG_FILE = REPO_ROOT / LOG_FILE


class OrchestratorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        application: GateApplication,
        logger: EverSparkLogger | None = None,
    ):
        super().__init__(address, RequestHandler)
        self.application = application
        self.orchestrator = getattr(application, "orchestrator", application)
        self.logger = logger


class RequestHandler(BaseHTTPRequestHandler):
    server: OrchestratorServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send(200, {"ok": True, "status": "standby"})
        elif parsed.path == "/image/health":
            try:
                health = self.server.application.image_health()
                self._send(200 if health["ok"] else 503, health)
            except Exception as exc:
                self._send(503, {"ok": False, "error": str(exc)})
        elif parsed.path == "/image/plugins":
            try:
                self._send(200, {"ok": True, **self.server.application.image_plugins()})
            except Exception as exc:
                self._send(502, {"ok": False, "error": str(exc)})
        elif parsed.path == "/concept/connections":
            self._send(200, {"ok": True, **self.server.application.concept_connections()})
        elif parsed.path == "/concept/connections/test/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            try:
                self._send(200, {"ok": True, "job": self.server.application.concept_connection_test_job(job_id)})
            except ValueError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/image/plugins/jobs":
            try:
                job_id = parse_qs(parsed.query).get("job_id", [""])[0]
                self._send(200, {"ok": True, "job": self.server.application.image_plugin_job(job_id)})
            except ValueError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/tasks/jobs":
            try:
                job_id = parse_qs(parsed.query).get("job_id", [""])[0]
                self._send(200, {"ok": True, "job": self.server.application.task_job(job_id)})
            except ValueError as exc:
                self._send(404, {"ok": False, "error": str(exc)})
        elif parsed.path == "/image/results":
            ids = [value for value in parse_qs(parsed.query).get("prompt_id", []) if value]
            if not ids or len(ids) > 20:
                self._send(400, {"ok": False, "error": "1 to 20 prompt_id values required"})
                return
            try:
                self._send(200, {"ok": True, "results": self.server.application.image_results(ids)})
            except KeyError:
                self._send(404, {"ok": False, "error": "Unknown image job"})
            except Exception as exc:
                self._send(502, {"ok": False, "error": str(exc)})
        elif parsed.path == "/image/history":
            try:
                limit = int(parse_qs(parsed.query).get("limit", ["24"])[0])
                self._send(200, {"ok": True, "images": self.server.application.image_history(limit)})
            except ValueError:
                self._send(400, {"ok": False, "error": "Invalid history limit"})
            except Exception as exc:
                self._send(502, {"ok": False, "error": str(exc)})
        elif parsed.path == "/audio/history":
            try:
                limit = int(parse_qs(parsed.query).get("limit", ["24"])[0])
                self._send(200, {"ok": True, "audio": self.server.application.audio_history(limit)})
            except ValueError:
                self._send(400, {"ok": False, "error": "Invalid history limit"})
            except Exception as exc:
                self._send(502, {"ok": False, "error": str(exc)})
        elif parsed.path == "/audio/file":
            query = parse_qs(parsed.query)
            audio = getattr(self.server.application, "audio", None)
            if audio is not None and getattr(audio, "url", None):
                self._stream_remote_output(lambda: audio.open_audio(query.get("filename", [""])[0]))
                return
            try:
                path = self.server.application.audio_path(query.get("filename", [""])[0])
            except ValueError:
                self._send(404, {"ok": False, "error": "Audio is unavailable"})
                return
            except (OSError, RuntimeError):
                self._send(502, {"ok": False, "error": "Audio Forge is unavailable"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    self.wfile.write(chunk)
        elif parsed.path in {"/image/archive/prepare", "/audio/archive/prepare"}:
            forge = parsed.path.split("/")[1]
            gateway = (getattr(self.server.application.image, "gateway", None) if forge == "image"
                       else getattr(self.server.application, "audio", None))
            try:
                job_id = parse_qs(parsed.query).get("job_id", [""])[0]
                self._send(200, gateway.archive_job(job_id))
            except (AttributeError, OSError, ValueError, RuntimeError) as exc:
                self._send(502, {"ok": False, "error": str(exc)})
        elif parsed.path == "/image/archive":
            gateway = getattr(self.server.application.image, "gateway", None)
            if not hasattr(gateway, "open_archive"):
                self._send(404, {"ok": False, "error": "Remote output archive unavailable"})
                return
            self._stream_remote_output(gateway.open_archive)
        elif parsed.path == "/image/file":
            query = parse_qs(parsed.query)
            gateway = getattr(self.server.application.image, "gateway", None)
            if hasattr(gateway, "open_image"):
                self._stream_remote_output(lambda: gateway.open_image(
                    query.get("filename", [""])[0], query.get("subfolder", [""])[0],
                    query.get("type", ["output"])[0]))
                return
            try:
                path = self.server.application.image_path(
                    query.get("filename", [""])[0], query.get("subfolder", [""])[0],
                    query.get("type", ["output"])[0])
            except ValueError:
                self._send(404, {"ok": False, "error": "Image is unavailable"})
                return
            import mimetypes
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as file:
                while chunk := file.read(1024 * 1024):
                    self.wfile.write(chunk)
        elif parsed.path == "/resources":
            try:
                self._send(200, {"ok": True, **self.server.application.resources(
                    parse_qs(parsed.query).get("engine", [""])[0])})
            except ValueError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send(502, {"ok": False, "error": str(exc)})
        elif parsed.path == "/storage/resources":
            try:
                self._send(
                    200,
                    {"ok": True, **self.server.application.storage_resources()},
                )
            except StorageError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/storage/scan":
            self._send(200, {"ok": True, **self.server.application.storage_scan()})
        elif parsed.path == "/storage/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send(
                200,
                {"ok": True, "job": self.server.application.storage_job(job_id)},
            )
        elif parsed.path == "/backup/resources":
            try:
                self._send(200, {"ok": True, **self.server.application.backup_resources()})
            except StorageError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/backup/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send(200, {"ok": True, "job": self.server.application.backup_job(job_id)})
        elif parsed.path == "/backup/restore-points":
            try:
                self._send(200, {"ok": True, "points": self.server.application.restore_points()})
            except StorageError as exc:
                self._send(400, {"ok": False, "error": str(exc)})
        elif parsed.path == "/downloads/jobs":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            self._send(
                200,
                {"ok": True, "job": self.server.application.download_job(job_id)},
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
                    "messages": self.server.application.get_history(session_id),
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
                    "document": self.server.application.get_session_subject(session_id),
                },
            )
        elif parsed.path == "/subjects":
            subject_id = parse_qs(parsed.query).get("subject_id", [""])[0]
            if subject_id:
                try:
                    document = self.server.application.get_subject(subject_id)
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
                        "subjects": self.server.application.list_subjects(),
                    },
                )
        elif parsed.path == "/subjects/revisions":
            subject_id = parse_qs(parsed.query).get("subject_id", [""])[0]
            if not subject_id:
                self._send(400, {"ok": False, "error": "subject_id is required"})
                return
            try:
                revisions = self.server.application.get_subject_revisions(subject_id)
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
                bundle = self.server.application.subject_bundle(subject_id)
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
            "/tasks/start",
            "/conversation",
            "/memory/clear",
            "/subjects",
            "/subjects/generate",
            "/subjects/update",
            "/subjects/revise",
            "/subjects/select",
            "/subjects/compile",
            "/storage/pull",
            "/storage/scan",
            "/storage/paths",
            "/storage/reconfigure",
            "/backup/upload",
            "/backup/restore",
            "/data/archive",
            "/data/import",
            "/downloads",
            "/downloads/cancel",
            "/downloads/retry",
            "/image/plugins/install",
            "/image/plugins/enable",
            "/image/plugins/default",
            "/concept/connections/save",
            "/concept/connections/test",
            "/concept/connections/remove",
            "/concept/connections/default",
        }:
            self._send(404, {"ok": False, "error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            if request_path == "/tasks":
                result = self.server.application.submit(
                    str(payload.get("text", "")),
                    str(payload.get("session_id", "")),
                    payload.get("selection"),
                )
                self._send(200, result)
            elif request_path == "/tasks/start":
                job = self.server.application.start_task(
                    str(payload.get("text", "")), str(payload.get("session_id", "")),
                    payload.get("selection"), str(payload.get("request_id", "")))
                self._send(202, {"ok": True, "job": job})
            elif request_path in {"/image/plugins/install", "/image/plugins/enable"}:
                job = self.server.application.start_image_plugin(
                    str(payload.get("plugin", "")), request_path.rsplit("/", 1)[-1])
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/image/plugins/default":
                result = self.server.application.set_default_image_plugin(str(payload.get("plugin", "")))
                self._send(200, {"ok": True, **result})
            elif request_path == "/concept/connections/save":
                self._send(200, {"ok": True, **self.server.application.save_concept_connection(payload)})
            elif request_path == "/concept/connections/test":
                self._send(202, {"ok": True, "job": self.server.application.start_concept_connection_test(payload)})
            elif request_path == "/concept/connections/remove":
                self._send(200, {"ok": True, **self.server.application.remove_concept_connection(str(payload.get("id", "")))})
            elif request_path == "/concept/connections/default":
                self._send(200, {"ok": True, **self.server.application.default_concept_connection(str(payload.get("id", "")))})
            elif request_path == "/conversation":
                candidate = str(payload.get("request_id", ""))
                trace_id = candidate if len(candidate) == 32 and all(
                    char in "0123456789abcdef" for char in candidate) else uuid.uuid4().hex
                started = time.monotonic()
                self._log("info", "conversation.start", "Conversation started", trace_id=trace_id)
                try:
                    with trace_scope(trace_id):
                        result = self.server.application.discuss(
                            str(payload.get("text", "")),
                            str(payload.get("session_id", "")),
                            payload.get("selection"),
                        )
                except Exception as exc:
                    self._log("error", "conversation.failed", "Conversation failed",
                              trace_id=trace_id, error_type=type(exc).__name__,
                              elapsed_ms=round((time.monotonic() - started) * 1000))
                    raise
                self._log("ok", "conversation.ok", "Conversation completed",
                          trace_id=trace_id,
                          elapsed_ms=round((time.monotonic() - started) * 1000))
                self._send(200, result)
            elif request_path == "/memory/clear":
                session_id = str(payload.get("session_id", ""))
                self.server.application.clear_memory(session_id)
                self._send(200, {"ok": True, "session_id": session_id})
            elif request_path == "/subjects":
                document = payload.get("document")
                if not isinstance(document, dict):
                    raise ValueError("document must be a JSON object")
                saved = self.server.application.save_subject(document)
                self._send(201, {"ok": True, "document": saved})
            elif request_path == "/subjects/generate":
                subject_id = str(payload.get("subject_id", ""))
                text = str(payload.get("text", ""))
                generated = self.server.application.generate_subject(subject_id, text)
                self._send(201, {"ok": True, "document": generated})
            elif request_path == "/subjects/update":
                subject_id = str(payload.get("subject_id", ""))
                changes = payload.get("changes")
                if not isinstance(changes, dict):
                    raise ValueError("changes must be a JSON object")
                updated = self.server.application.update_subject(subject_id, changes)
                self._send(200, {"ok": True, "document": updated})
            elif request_path == "/subjects/revise":
                bundle = self.server.application.revise_subject_group(
                    str(payload.get("subject_id", "")),
                    str(payload.get("group", "")),
                    str(payload.get("instruction", "")),
                )
                self._send(200, {"ok": True, "bundle": bundle})
            elif request_path == "/subjects/select":
                subject = self.server.application.select_session_subject(
                    str(payload.get("session_id", "")), str(payload.get("subject_id", ""))
                )
                self._send(200, {"ok": True, "document": subject})
            elif request_path == "/storage/reconfigure":
                import ipaddress
                if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                    self._send(403, {"ok": False, "error": "Local request required"})
                    return
                self.server.application.storage.reconfigure(payload["values"])
                self._send(200, {"ok": True})
            elif request_path == "/storage/scan":
                self._send(202, {"ok": True, **self.server.application.start_storage_scan()})
            elif request_path == "/storage/pull":
                job = self.server.application.start_storage_pull(
                    str(payload.get("kind", "")), str(payload.get("name", ""))
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/storage/paths":
                paths = self.server.application.save_storage_paths(payload.get("paths", {}))
                self._send(200, {"ok": True, "paths": paths})
            elif request_path == "/data/archive":
                archive_id = self.server.application.export_data_archive()
                self._send(200, {"ok": True, "id": archive_id})
            elif request_path == "/data/import":
                result = self.server.application.restore_data_archive(str(payload.get("id", "")))
                self._send(200, {"ok": True, **result})
            elif request_path == "/backup/upload":
                job = self.server.application.start_backup(
                    payload.get("names", []), payload.get("memory") is True,
                    payload.get("targets", {}), payload.get("outputs") is True,
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/backup/restore":
                job = self.server.application.start_restore(str(payload.get("id", "")))
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/downloads":
                job = self.server.application.start_download(
                    str(payload.get("kind", "")),
                    str(payload.get("url", "")),
                    str(payload.get("filename", "")),
                    str(payload.get("runtime_name", "")),
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/downloads/cancel":
                job = self.server.application.cancel_download(
                    str(payload.get("job_id", ""))
                )
                self._send(202, {"ok": True, "job": job})
            elif request_path == "/downloads/retry":
                job = self.server.application.retry_download(
                    str(payload.get("job_id", ""))
                )
                self._send(202, {"ok": True, "job": job})
            else:
                subject_id = str(payload.get("subject_id", ""))
                compiled = self.server.application.compile_subject(subject_id)
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
        except ConceptError as exc:
            self._send(502, {"ok": False, "error": str(exc)})
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

    def _stream_remote_output(self, opener):
        started = False
        try:
            with opener() as source:
                self.send_response(200)
                for name in ("Content-Type", "Content-Length", "Content-Disposition"):
                    if source.headers.get(name):
                        self.send_header(name, source.headers[name])
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                started = True
                remaining = int(source.headers["Content-Length"])
                while remaining:
                    block = source.read(min(64 * 1024, remaining))
                    if not block:
                        raise OSError("Incomplete image stream")
                    self.wfile.write(block)
                    remaining -= len(block)
        except (OSError, ValueError, RuntimeError):
            if not started:
                self._send(502, {"ok": False, "error": "Image Node output unavailable"})
            else:
                self.close_connection = True

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    logger = get_logger("orchestrator", LOG_FILE)
    concept_logger = get_logger("conceptforge", LOG_DIR / "concept/conceptforge.log")
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
        concept_logger.close()
        return 1
    host = str(config["orchestrator"]["host"])
    port = int(config["orchestrator"]["port"])
    try:
        server = OrchestratorServer((host, port), GateApplication(
            config, logger=logger, concept_logger=concept_logger), logger)
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
        concept_logger.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
