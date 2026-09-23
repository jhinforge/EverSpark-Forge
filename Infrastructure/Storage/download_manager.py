from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_KINDS = {
    "checkpoint": ("checkpoints", {".safetensors", ".ckpt"}),
    "diffusion_model": ("diffusion_models", {".safetensors", ".ckpt"}),
    "lora": ("loras", {".safetensors", ".ckpt"}),
    "vae": ("vae", {".safetensors", ".ckpt", ".pt"}),
}
RUNTIME_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class DownloadError(RuntimeError):
    pass


class DownloadCancelled(DownloadError):
    pass


@dataclass(frozen=True)
class DownloadSettings:
    image_root: Path
    concept_root: Path
    temporary_root: Path
    modelfile_root: Path
    ollama_url: str
    timeout: int = 60

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "DownloadSettings":
        provider = config.get("concept_forge", {}).get("providers", {}).get("ollama", {})
        return cls(
            image_root=(REPO_ROOT / "Data/Models/ImageForge").resolve(),
            concept_root=(REPO_ROOT / "Data/Models/ConceptForge").resolve(),
            temporary_root=(REPO_ROOT / "Data/Downloads").resolve(),
            modelfile_root=(REPO_ROOT / "Data/Runtime/Models/Imports").resolve(),
            ollama_url=str(provider.get("base_url", "http://127.0.0.1:11434")).rstrip("/"),
            timeout=60,
        )


def _validate_public_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"}:
        raise DownloadError("Only http:// and https:// model URLs are supported")
    if not parsed.hostname or parsed.username or parsed.password:
        raise DownloadError("The model URL must contain a public host without embedded credentials")
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise DownloadError(f"Could not resolve the model download host: {exc}") from exc
    if not addresses:
        raise DownloadError("The model download host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise DownloadError("Model downloads cannot access local or private network addresses")
    return urlunparse(parsed)


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        safe_url = _validate_public_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def _open_public_url(url: str, headers: dict[str, str], timeout: int):
    safe_url = _validate_public_url(url)
    request = Request(safe_url, headers=headers, method="GET")
    return build_opener(_PublicRedirectHandler()).open(request, timeout=timeout)


def _public_source(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _safe_filename(value: str) -> str:
    filename = unquote(str(value or "").strip()).replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or filename in {".", ".."} or "\x00" in filename:
        raise DownloadError("A valid model filename is required")
    if len(filename) > 240:
        raise DownloadError("The model filename is too long")
    return filename


def _safe_vae_filename(value: str) -> str:
    name = unquote(str(value or "").strip()).replace("\\", "/")
    parts = name.split("/")
    if (not name or name.startswith("/") or len(name) > 240
            or any(part in {"", ".", ".."} or "\x00" in part for part in parts)):
        raise DownloadError("A safe relative VAE filename is required")
    return "/".join(parts)


def _default_runtime_name(filename: str) -> str:
    stem = Path(filename).stem.casefold()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-._")
    return normalized or "everspark-concept"


class DirectDownloadManager:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        open_url: Callable[[str, dict[str, str], int], Any] = _open_public_url,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ):
        self.settings = DownloadSettings.from_config(config)
        self._open_url = open_url
        self._run = run
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._requests: dict[str, dict[str, str]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_job = ""

    def start(
        self,
        kind: str,
        url: str,
        filename: str = "",
        runtime_name: str = "",
    ) -> dict[str, Any]:
        request = self._normalize_request(kind, url, filename, runtime_name)
        return self._queue(request)

    def _queue(self, request: dict[str, str]) -> dict[str, Any]:
        with self._lock:
            if self._active_job:
                active = self._jobs.get(self._active_job, {})
                if active.get("status") in {"queued", "downloading", "registering"}:
                    raise DownloadError("A direct model download is already running")
            job_id = uuid.uuid4().hex
            job = {
                "job_id": job_id,
                "kind": request["kind"],
                "name": request["filename"] or "Resolving filename",
                "runtime_name": request["runtime_name"],
                "source": _public_source(request["url"]),
                "status": "queued",
                "progress": self._progress_payload(),
                "error": "",
                "started_at": time.time(),
                "finished_at": 0.0,
            }
            self._jobs[job_id] = job
            self._requests[job_id] = request
            self._cancel_events[job_id] = threading.Event()
            self._active_job = job_id
        self._launch(job_id)
        return copy.deepcopy(job)

    def retry(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            previous = self._jobs.get(str(job_id))
            request = self._requests.get(str(job_id))
            if previous is None or request is None:
                raise DownloadError("Download job was not found")
            if previous.get("status") not in {"failed", "cancelled"}:
                raise DownloadError("Only failed or cancelled downloads can be retried")
            retry_request = dict(request)
        return self._queue(retry_request)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(str(job_id))
            event = self._cancel_events.get(str(job_id))
            if job is None or event is None:
                raise DownloadError("Download job was not found")
            if job.get("status") not in {"queued", "downloading"}:
                raise DownloadError("The download job is no longer running")
            event.set()
            return copy.deepcopy(job)

    def job(self, job_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            selected = str(job_id) or self._active_job
            job = self._jobs.get(selected)
            return copy.deepcopy(job) if job else None

    def _launch(self, job_id: str) -> None:
        threading.Thread(
            target=self._run_job,
            args=(job_id,),
            name=f"everspark-download-{job_id[:8]}",
            daemon=True,
        ).start()

    def _run_job(self, job_id: str) -> None:
        request = self._requests[job_id]
        try:
            installed_path = request.get("installed_path", "")
            destination = Path(installed_path) if installed_path else self._download(job_id, request)
            if not destination.is_file() or destination.stat().st_size < 1:
                raise DownloadError("The downloaded model file is no longer available")
            request["installed_path"] = str(destination)
            if request["kind"] == "concept_model":
                self._register_concept_model(job_id, destination, request["runtime_name"])
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "completed"
                job["finished_at"] = time.time()
                job["progress"]["percent"] = 100.0
                job["progress"]["eta_seconds"] = 0
        except DownloadCancelled:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "cancelled"
                job["error"] = "Download cancelled"
                job["finished_at"] = time.time()
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "failed"
                job["error"] = str(exc)
                job["finished_at"] = time.time()

    def _download(self, job_id: str, request: dict[str, str]) -> Path:
        cancel_event = self._cancel_events[job_id]
        explicit_name = request["filename"]
        url_name = Path(unquote(urlparse(request["url"]).path)).name
        candidate_name = explicit_name or url_name
        response = None
        partial: Path | None = None
        try:
            response = self._request(request["url"], 0)
            header_name = ""
            if hasattr(response.headers, "get_filename"):
                header_name = response.headers.get_filename() or ""
            filename = (_safe_vae_filename(explicit_name) if request["kind"] == "vae" and explicit_name
                        else _safe_filename(explicit_name or header_name or candidate_name))
            destination = self._destination(request["kind"], filename)
            self._validate_extension(request["kind"], destination.suffix)
            if destination.exists():
                raise DownloadError(f"A model with this filename already exists: {filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(request["url"].encode("utf-8")).hexdigest()[:12]
            partial = destination.with_name(f".{destination.name}.{digest}.part")
            offset = partial.stat().st_size if partial.is_file() else 0
            if offset:
                response.close()
                response = self._request(request["url"], offset)
            status = int(getattr(response, "status", response.getcode()))
            append = offset > 0 and status == 206
            if append:
                content_range = str(response.headers.get("Content-Range", ""))
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if not match or int(match.group(1)) != offset:
                    raise DownloadError("The server returned an invalid resume range; retry the download")
            if offset and not append:
                offset = 0
            total = self._total_size(response, offset if append else 0)
            remaining = max(0, total - offset) if total else 0
            if remaining and remaining > shutil.disk_usage(destination.parent).free:
                raise DownloadError(
                    f"Not enough disk space for {filename}: {remaining} bytes still required"
                )
            with self._lock:
                job = self._jobs[job_id]
                job["name"] = filename
                job["status"] = "downloading"
            completed = offset
            self._set_progress(job_id, completed, total)
            with partial.open("ab" if append else "wb") as target:
                while True:
                    if cancel_event.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    completed += len(chunk)
                    self._set_progress(job_id, completed, total)
                target.flush()
                os.fsync(target.fileno())
            if total and completed != total:
                raise DownloadError(
                    f"Downloaded size mismatch for {filename}: expected {total}, got {completed}"
                )
            if completed < 1:
                raise DownloadError("The model download returned an empty file")
            if request["kind"] == "concept_model":
                with partial.open("rb") as model_file:
                    if model_file.read(4) != b"GGUF":
                        raise DownloadError("The downloaded file is not a GGUF model")
            partial.replace(destination)
            self._set_progress(job_id, completed, total or completed)
            request["filename"] = filename
            return destination
        finally:
            if response is not None:
                response.close()

    def _request(self, url: str, offset: int):
        headers = {"User-Agent": "EverSpark-Forge/0.1", "Accept": "application/octet-stream"}
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        try:
            return self._open_url(url, headers, self.settings.timeout)
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(f"Could not open the model download: {exc}") from exc

    def _register_concept_model(
        self, job_id: str, model_path: Path, runtime_name: str
    ) -> None:
        if self._cancel_events[job_id].is_set():
            raise DownloadCancelled()
        name = runtime_name or _default_runtime_name(model_path.name)
        if not RUNTIME_NAME_PATTERN.fullmatch(name):
            raise DownloadError("The Ollama model name contains unsupported characters")
        ollama = shutil.which("ollama")
        if ollama is None:
            raise DownloadError("Ollama is not installed; run ./everspark setup first")
        self.settings.modelfile_root.mkdir(parents=True, exist_ok=True)
        modelfile = self.settings.modelfile_root / f"{job_id}.Modelfile"
        modelfile.write_text(
            f"FROM {json.dumps(str(model_path))}\nPARAMETER num_ctx 8192\n",
            encoding="utf-8",
        )
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "registering"
            job["runtime_name"] = name
        environment = os.environ.copy()
        parsed = urlparse(self.settings.ollama_url)
        if parsed.hostname:
            environment["OLLAMA_HOST"] = f"{parsed.hostname}:{parsed.port or 11434}"
        try:
            completed = self._run(
                [ollama, "create", name, "-f", str(modelfile)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
        except OSError as exc:
            raise DownloadError(f"Could not start Ollama model registration: {exc}") from exc
        if completed.returncode != 0:
            output = ANSI_ESCAPE.sub("", "\n".join(filter(None, (completed.stderr, completed.stdout))))
            lines = [line.strip() for line in output.replace("\r", "\n").splitlines()]
            errors = [line for line in lines if line.startswith("Error:")]
            detail = errors[-1] if errors else next((line for line in reversed(lines) if line), "unknown error")
            raise DownloadError(f"Ollama model registration failed: {detail}")

    def _normalize_request(
        self, kind: str, url: str, filename: str, runtime_name: str
    ) -> dict[str, str]:
        normalized_kind = str(kind).strip().lower()
        if normalized_kind not in {*IMAGE_KINDS, "concept_model"}:
            raise DownloadError(f"Unsupported model download kind: {kind}")
        normalized_url = str(url).strip()
        if not normalized_url:
            raise DownloadError("A direct model URL is required")
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DownloadError("A valid http:// or https:// model URL is required")
        normalized_filename = ((_safe_vae_filename(filename) if normalized_kind == "vae" else _safe_filename(filename))
                               if str(filename).strip() else "")
        normalized_runtime = str(runtime_name).strip()
        if normalized_kind != "concept_model" and normalized_runtime:
            raise DownloadError("runtime_name is only valid for Concept Forge models")
        if normalized_runtime and not RUNTIME_NAME_PATTERN.fullmatch(normalized_runtime):
            raise DownloadError("The Ollama model name contains unsupported characters")
        return {
            "kind": normalized_kind,
            "url": normalized_url,
            "filename": normalized_filename,
            "runtime_name": normalized_runtime,
        }

    def _destination(self, kind: str, filename: str) -> Path:
        if kind == "concept_model":
            return self.settings.concept_root / filename
        directory = IMAGE_KINDS[kind][0]
        return self.settings.image_root / directory / filename

    @staticmethod
    def _validate_extension(kind: str, suffix: str) -> None:
        allowed = {".gguf"} if kind == "concept_model" else IMAGE_KINDS[kind][1]
        if suffix.casefold() not in allowed:
            expected = ", ".join(sorted(allowed))
            raise DownloadError(f"Unsupported model file extension; expected {expected}")

    @staticmethod
    def _total_size(response: Any, offset: int) -> int:
        content_range = str(response.headers.get("Content-Range", ""))
        if "/" in content_range:
            raw_total = content_range.rsplit("/", 1)[-1]
            if raw_total.isdigit():
                return int(raw_total)
        content_length = str(response.headers.get("Content-Length", ""))
        return offset + int(content_length) if content_length.isdigit() else 0

    @staticmethod
    def _progress_payload(
        completed: int = 0, total: int = 0, elapsed: float = 0.0
    ) -> dict[str, int | float]:
        percent = completed * 100 / total if total else 0.0
        speed = int(completed / elapsed) if elapsed > 0 else 0
        eta = int((total - completed) / speed) if total and speed > 0 else 0
        return {
            "bytes_completed": completed,
            "bytes_total": total,
            "percent": round(min(100.0, max(0.0, percent)), 1),
            "speed_bytes_per_second": speed,
            "eta_seconds": max(0, eta),
        }

    def _set_progress(self, job_id: str, completed: int, total: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            elapsed = max(0.0, time.time() - float(job["started_at"]))
            job["progress"] = self._progress_payload(completed, total, elapsed)
