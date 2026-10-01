"""Node-local model transfer service, independent of short-lived Envoy tasks."""
import contextlib
import copy
import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
for relative in ("", "Aegis/Storage", "Legate/Forge/ConceptForge"):
    sys.path.insert(0, str(ROOT / relative))
from Archon.Vault.runtime_config import load_config
from download_manager import DirectDownloadManager, IMAGE_KINDS
from r2_manager import R2StorageManager

ACTIONS = {"models_download_start", "models_download_job", "models_download_cancel",
           "models_download_retry", "models_pull_start", "models_pull_job", "models_installed"}
STATE = Path(os.environ.get("EVERSPARK_MODEL_STORAGE_STATE", str(ROOT / "Data/Runtime/model-storage"))).resolve()


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    temporary.replace(path)


class ModelStorage:
    def __init__(self, config):
        self.config = copy.deepcopy(config)
        self.config.pop("remote_nodes", None)
        self.config["concept_forge"]["providers"]["ollama"]["base_url"] = "http://127.0.0.1:11434"
        self.downloads = DirectDownloadManager(self.config)
        self.clouds, self.pulls = {}, {}
        self.lock = threading.RLock()

    def cloud(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"storage", "rclone_config", "paths"}:
            raise ValueError("Invalid cloud storage configuration")
        text = payload["rclone_config"]
        if not isinstance(text, str) or len(text.encode()) > 45000:
            raise ValueError("Invalid cloud storage credentials")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if digest in self.clouds:
            return self.clouds[digest]
        if not shutil.which("rclone"):
            subprocess.run(["bash", "-c", 'source "$1"; core_rclone_install', "model-storage",
                str(ROOT / "Aegis/Storage/rclone.sh")], check=True, stdout=sys.stderr, stderr=sys.stderr, timeout=90)
        directory = STATE / "cloud" / digest
        private_write(directory / "rclone.conf", text)
        config = copy.deepcopy(self.config)
        config["storage"] = copy.deepcopy(payload["storage"])
        config["storage"]["rclone"]["config_file"] = str(directory / "rclone.conf")
        manager = R2StorageManager(config)
        manager.client.validate()
        manager.paths.save(payload["paths"])
        self.clouds[digest] = manager
        return manager

    def installed(self, entries, forge):
        if not isinstance(entries, list):
            raise ValueError("Invalid inventory request")
        names = None
        result = []
        for entry in entries:
            kind, name = entry["kind"], entry["name"]
            path = PurePosixPath(name)
            if (not isinstance(name, str) or not name or path.is_absolute()
                    or any(p in {"", ".", ".."} for p in name.split("/")) or "\\" in name):
                raise ValueError("Unsafe model name")
            if forge == "image" and kind in IMAGE_KINDS:
                result.append((ROOT / "Data/Models/ImageForge" / IMAGE_KINDS[kind][0] / name).is_file())
            elif forge == "concept" and kind == "concept_model":
                if entry.get("format") == "gguf":
                    local = ROOT / "Data/Models/ConceptForge" / path.name
                    marker = ROOT / "Data/Runtime/Models/Imports" / (path.name + ".registered.json")
                    try:
                        result.append(local.is_file() and json.loads(marker.read_text()).get("size") == local.stat().st_size)
                    except (OSError, ValueError):
                        result.append(False)
                else:
                    if names is None:
                        from concept_forge.adapters.ollama import OllamaAdapter
                        names = OllamaAdapter(self.config["concept_forge"]["providers"]["ollama"]).list_models()
                    result.append(name in names or name + ":latest" in names)
            else:
                raise ValueError("Model type does not belong to this Forge")
        return result

    def dispatch(self, action, payload, forge):
        if action not in ACTIONS or forge not in {"image", "concept"} or not isinstance(payload, dict):
            raise ValueError("Unsupported model storage action")
        with self.lock:
            if action == "models_installed":
                return self.installed(payload["entries"], forge)
            if action.endswith("_start"):
                kind = payload["kind"]
                if (forge == "image" and kind not in IMAGE_KINDS) or (forge == "concept" and kind != "concept_model"):
                    raise ValueError("Model type does not belong to this Forge")
                if action == "models_download_start":
                    return self.downloads.start(kind, payload["url"], payload.get("filename", ""), payload.get("runtime_name", ""))
                manager = self.cloud(payload["cloud"])
                job = manager.start_pull(kind, payload["name"])
                self.pulls[job["job_id"]] = manager
                return job
            job_id = payload["job_id"]
            if action == "models_pull_job":
                manager = self.pulls.get(job_id)
                if not manager:
                    raise ValueError("Cloud job is unavailable; the node storage service may have restarted")
                job = manager.job(job_id)
            else:
                job = self.downloads.job(job_id)
            if not job or ("concept" if job["kind"] == "concept_model" else "image") != forge:
                raise ValueError("Unknown model job for this Forge")
            if action == "models_download_cancel":
                return self.downloads.cancel(job_id)
            if action == "models_download_retry":
                return self.downloads.retry(job_id)
            return job


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.token):
                self.send_error(403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/models" or not 0 < length <= 60000:
                raise ValueError("Invalid model storage request")
            request = json.loads(self.rfile.read(length))
            value = self.server.models.dispatch(request["action"], request["payload"], request["forge"])
            response = {"ok": True, "value": value}
        except Exception as exc:
            # Never reflect credential-bearing payloads or command arguments.
            response = {"ok": False, "error": "Model storage failed: " +
                (str(exc) if isinstance(exc, ValueError) else type(exc).__name__)}
        body = json.dumps(response, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def call_endpoint(endpoint, action, payload, forge):
    request = Request(f"http://127.0.0.1:{endpoint['port']}/models", data=json.dumps({
        "action": action, "payload": payload, "forge": forge}).encode(),
        headers={"Authorization": "Bearer " + endpoint["token"], "Content-Type": "application/json"})
    with urlopen(request, timeout=110) as response:
        result = json.load(response)
    if not result["ok"]:
        raise RuntimeError(result["error"])
    return result["value"]


def proxy(action, payload, forge):
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True)
    endpoint_path = STATE / "endpoint.json"
    with (STATE / "startup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            endpoint = json.loads(endpoint_path.read_text())
            os.kill(endpoint["pid"], 0)
            # Verify the process by its private token before trusting a reused PID.
            call_endpoint(endpoint, "models_installed", {"entries": []}, forge)
        except (OSError, ValueError, KeyError, RuntimeError):
            endpoint_path.unlink(missing_ok=True)
            with (STATE / "service.log").open("ab") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + 10
            while not endpoint_path.is_file():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Node model storage service failed to start")
                time.sleep(0.05)
            endpoint = json.loads(endpoint_path.read_text())
    return call_endpoint(endpoint, action, payload, forge)


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.token = secrets.token_hex(32)
    server.models = ModelStorage(load_config())
    private_write(STATE / "endpoint.json", json.dumps({"port": server.server_port,
        "token": server.token, "pid": os.getpid()}))
    server.serve_forever()


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
    elif len(sys.argv) == 4 and sys.argv[2] in ACTIONS and len(sys.argv[3].encode()) <= 60000:
        with contextlib.redirect_stdout(sys.stderr):
            result = proxy(sys.argv[2], json.loads(sys.argv[3]), sys.argv[1])
        print(json.dumps(result, ensure_ascii=False))
    else:
        raise SystemExit(2)
