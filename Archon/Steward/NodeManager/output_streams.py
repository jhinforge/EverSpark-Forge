"""Bounded, one-use reverse binary streams on the existing Agent listener."""
import json
import mimetypes
import queue
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
from .errors import NodeError
from .identity import validate_id

BLOCK = 64 * 1024
MAX_IMAGE = 100 * 1024 * 1024
MAX_ARCHIVE = 2 * 1024 * 1024 * 1024


class Transfer:
    def __init__(self, archive=False):
        self.archive = archive
        self.blocks = queue.Queue(maxsize=8)
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.size = None
        self.error = None
        self.claimed = False
        self.deadline = time.monotonic() + 300

    def fail(self, message):
        self.error = message
        self.ready.set()

    def put(self, data):
        while not self.closed.is_set():
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Output stream expired")
            try:
                self.blocks.put(data, timeout=0.5)
                return
            except queue.Full:
                pass
        raise ConnectionAbortedError("Output consumer disconnected")

    def get(self):
        while not self.closed.is_set():
            try:
                return self.blocks.get(timeout=0.5)
            except queue.Empty:
                if self.error:
                    raise OSError(self.error)
                if time.monotonic() >= self.deadline:
                    raise TimeoutError("Output stream expired")
        raise ConnectionAbortedError("Output consumer disconnected")


class OutputStreams:
    def __init__(self, manager):
        self.manager = manager
        self.lock = threading.Lock()
        self.active = {}

    def close(self):
        with self.lock:
            for transfer in self.active.values():
                transfer.closed.set()
            self.active.clear()

    def serve(self, handler, query):
        node_id = validate_id(query.get("node_id", [""])[0])
        forge = query.get("forge", ["image"])[0]
        if forge not in {"image", "audio"}:
            raise NodeError("Invalid output owner", 400)
        archive = query.get("archive", ["0"])[0] == "1"
        filename = query.get("filename", [""])[0]
        subfolder = query.get("subfolder", [""])[0]
        if not archive and (not filename or "/" in filename or "\\" in filename
                            or ".." in filename or subfolder.startswith(("/", "\\"))
                            or ".." in subfolder or "\\" in subfolder
                            or query.get("type", ["output"])[0] != "output"):
            raise NodeError("Invalid image path", 400)
        if self.manager.status(node_id).get("status") != "online":
            raise NodeError("Image Node is offline", 503)
        transfer = Transfer(archive)
        token = secrets.token_hex(32)
        with self.lock:
            if len(self.active) >= 4:
                raise NodeError("Too many output streams; retry shortly", 429)
            self.active[token] = transfer
        message = json.dumps({"token": token, "archive": archive,
                              "filename": filename, "subfolder": subfolder})
        def request():
            try:
                self.manager.execute(node_id, "stream", message, timeout=300, forge=forge)
                if not transfer.ready.is_set():
                    transfer.fail("Image Node did not start the output stream")
            except Exception:
                transfer.fail("Image Node output stream failed")
        threading.Thread(target=request, daemon=True, name="node-output-stream").start()
        started = False
        try:
            if not transfer.ready.wait(60) or transfer.error:
                raise NodeError("Image Node output stream unavailable", 502)
            handler.send_response(200)
            mime = "application/zip" if archive else ("audio/wav" if forge == "audio" else (mimetypes.guess_type(filename)[0] or "application/octet-stream"))
            handler.send_header("Content-Type", mime)
            handler.send_header("Content-Length", str(transfer.size))
            handler.send_header("Cache-Control", "no-store")
            if archive:
                handler.send_header("Content-Disposition", 'attachment; filename="EverSpark-Outputs.zip"')
            handler.end_headers()
            started = True
            remaining = transfer.size
            while remaining:
                block = transfer.get()
                if not block or len(block) > remaining:
                    raise OSError("Incomplete output stream")
                handler.wfile.write(block)
                remaining -= len(block)
        except (OSError, TimeoutError):
            if not started:
                raise NodeError("Image Node output stream unavailable", 502) from None
            handler.close_connection = True
        finally:
            transfer.closed.set()
            with self.lock:
                self.active.pop(token, None)

    def upload(self, handler):
        # The capability is only delivered to the chosen Node in its task.
        # Never put it in URLs, browser responses or diagnostic logs.
        authorization = handler.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ")
        with self.lock:
            transfer = self.active.get(token) if authorization.startswith("Bearer ") else None
            if not transfer or transfer.claimed or transfer.closed.is_set():
                raise NodeError("Unknown output stream", 403)
            transfer.claimed = True
        try:
            size = int(handler.headers.get("Content-Length", "0"))
            limit = MAX_ARCHIVE if transfer.archive else MAX_IMAGE
            if handler.headers.get("Transfer-Encoding") or not 0 < size <= limit:
                raise NodeError("Invalid output size", 413)
            transfer.size = size
            transfer.ready.set()
            remaining = size
            while remaining:
                block = handler.rfile.read(min(BLOCK, remaining))
                if not block:
                    raise OSError("Incomplete output upload")
                transfer.put(block)
                remaining -= len(block)
            handler._send(200, {"ok": True})
        except Exception:
            transfer.fail("Output upload interrupted")
            raise
