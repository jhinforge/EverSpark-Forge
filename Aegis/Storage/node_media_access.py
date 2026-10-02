"""Private node media URLs. Originals remain on the node; no host cache."""
from __future__ import annotations
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Aegis.Storage.output_resources import OutputResources
from Archon.Vault.runtime_config import load_config

STATE = ROOT / "Data/Runtime/media-access/image"
ENDPOINT = STATE / "endpoint.json"
VERSION = 1


def signature(key, filename, subfolder, expires):
    message = json.dumps([filename, subfolder, expires], ensure_ascii=False, separators=(",", ":"))
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


class ImageServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, outputs, key):
        self.outputs, self.key = outputs, key
        super().__init__(address, ImageHandler)


class ImageHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(30)
        super().setup()

    def _json(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        value = self.headers.get("Authorization", "")
        return hmac.compare_digest(value, "Bearer " + self.server.key)

    def do_POST(self):
        if self.path != "/sign" or not self._authorized():
            self._json(403, {"error": "Forbidden"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 60000:
                raise ValueError("Invalid request")
            images = json.loads(self.rfile.read(length))
            if not isinstance(images, list) or len(images) > 100:
                raise ValueError("Invalid request")
            values = []
            expires = int(time.time()) + 3600
            host, port = self.server.server_address
            for image in images:
                if not isinstance(image, dict) or image.get("type", "output") != "output":
                    raise ValueError("Invalid image")
                filename, subfolder = image["filename"], image.get("subfolder", "")
                self.server.outputs.path(filename, subfolder)
                query = urlencode({"filename": filename, "subfolder": subfolder,
                                   "expires": expires, "signature": signature(self.server.key, filename, subfolder, expires)})
                values.append({**image, "url": f"http://{host}:{port}/file?{query}"})
            self._json(200, {"images": values})
        except (ValueError, TypeError, KeyError, OSError):
            self._json(400, {"error": "Image is unavailable"})

    def do_GET(self):
        self._serve_image(False)

    def do_HEAD(self):
        self._serve_image(True)

    def _serve_image(self, head):
        if self.path == "/health" and self._authorized():
            self._json(200, {"version": VERSION})
            return
        from urllib.parse import urlsplit
        parsed = urlsplit(self.path)
        if parsed.path != "/file":
            self._json(404, {"error": "Not found"})
            return
        started = False
        try:
            query = parse_qs(parsed.query)
            filename = query["filename"][0]
            subfolder = query.get("subfolder", [""])[0]
            expires = int(query["expires"][0])
            supplied = query["signature"][0]
            now = int(time.time())
            if not now <= expires <= now + 3600 or not hmac.compare_digest(
                    supplied, signature(self.server.key, filename, subfolder, expires)):
                self._json(403, {"error": "Image URL expired or invalid"})
                return
            path = self.server.outputs.path(filename, subfolder)
            size = path.stat().st_size
            if not 0 < size <= self.server.outputs.max_bytes:
                raise ValueError("Image too large")
            start, end, status = 0, size - 1, 200
            requested = self.headers.get("Range")
            if requested:
                import re
                match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", requested.strip())
                if not match or not any(match.groups()):
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), size-1) if right else size-1
                else:
                    start = max(0, size-int(right))
                if start >= size or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
            # Open before headers so missing files produce a useful status.
            with path.open("rb") as source:
                self.send_response(status)
                self.send_header("Content-Type", "audio/wav" if path.suffix.lower() == ".wav" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"))
                self.send_header("Content-Length", str(end-start+1))
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", f"private, max-age={max(0, expires-now)}")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                started = True
                if not head:
                    source.seek(start)
                    remaining = end-start+1
                    while remaining:
                        block = source.read(min(64 * 1024, remaining))
                        if not block:
                            raise OSError("Incomplete media file")
                        self.wfile.write(block)
                        remaining -= len(block)
        except (ValueError, TypeError, KeyError, OSError):
            if not started:
                self._json(404, {"error": "Image is unavailable"})
            else:
                self.close_connection = True

    def log_message(self, *_args):
        pass  # Signed URLs are capabilities; never log them.


def _request(endpoint, path, images=None):
    url = f"http://{endpoint['host']}:{endpoint['port']}{path}"
    body = json.dumps(images, ensure_ascii=False).encode() if images is not None else None
    request = Request(url, data=body, headers={"Authorization": "Bearer " + endpoint["token"],
                                             "Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        return json.load(response)


def _existing():
    try:
        endpoint = json.loads(ENDPOINT.read_text())
        os.kill(endpoint["pid"], 0)
        if _request(endpoint, "/health").get("version") == VERSION:
            return endpoint
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def endpoint(forge="image"):
    global STATE, ENDPOINT
    if forge not in {"image", "audio"}:
        raise ValueError("Invalid media owner")
    STATE = ROOT / "Data/Runtime/media-access" / forge
    ENDPOINT = STATE / "endpoint.json"
    STATE.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (STATE / "startup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _existing()
        if current:
            return current
        # Only bind the private overlay address, never 0.0.0.0/public interfaces.
        done = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3, check=True)
        host = done.stdout.strip().splitlines()[0]
        import ipaddress
        if ipaddress.ip_address(host) not in ipaddress.ip_network("100.64.0.0/10"):
            raise ValueError("Private Node address unavailable")
        with (STATE / "service.log").open("ab") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve", host, forge],
                             cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             start_new_session=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = _existing()
            if current:
                return current
            time.sleep(0.05)
        raise RuntimeError("Image URL service unavailable")


def media_urls(images, forge="image"):
    if not images or not (os.environ.get("EVERSPARK_NODE_URL") or os.environ.get("EVERSPARK_NODE_BRIDGE_URL")):
        return images
    try:
        return _request(endpoint(forge), "/sign", images)["images"]
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
        # Public sharing/non-overlay deployments continue through the host stream.
        return images


def serve(host, forge):
    global STATE, ENDPOINT
    if forge not in {"image", "audio"}:
        raise ValueError("Invalid media owner")
    STATE = ROOT / "Data/Runtime/media-access" / forge
    STATE.mkdir(parents=True, exist_ok=True)
    ENDPOINT = STATE / "endpoint.json"
    config = load_config()
    outputs = OutputResources(config[forge + "_forge"]["output_directory"], {".wav"} if forge == "audio" else {".png", ".jpg", ".jpeg", ".webp"})
    key = secrets.token_hex(32)
    server = ImageServer((host, 0), outputs, key)
    data = {"host": host, "port": server.server_port, "pid": os.getpid(), "token": key}
    temporary = ENDPOINT.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        json.dump(data, file)
    os.chmod(temporary, 0o600)
    temporary.replace(ENDPOINT)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "serve":
        raise SystemExit(2)
    serve(sys.argv[2], sys.argv[3])
