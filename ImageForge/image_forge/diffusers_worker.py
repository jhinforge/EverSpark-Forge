"""Local Diffusers SDXL worker; install dependencies in its managed venv."""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "Data/Models/ImageForge"
_output_path = Path(os.environ.get("EVERSPARK_OUTPUT_DIR", str(ROOT / "Data/Outputs")))
OUTPUTS = (_output_path if _output_path.is_absolute() else ROOT / _output_path).resolve()
JOBS = ROOT / "Data/Runtime/Diffusers/jobs"
executor = ThreadPoolExecutor(max_workers=1)
lock = threading.RLock()


def inventory(kind: str) -> list[str]:
    base = MODELS / kind
    if not base.is_dir():
        return []
    return sorted(path.relative_to(base).as_posix() for path in base.rglob("*")
                  if path.is_file() and not path.is_symlink()
                  and path.suffix.lower() in {".safetensors", ".ckpt"})


def model_path(kind: str, name: str) -> Path:
    if not isinstance(name, str) or name not in inventory(kind):
        raise ValueError(f"Unavailable {kind}: {name}")
    base = (MODELS / kind).resolve()
    path = (base / name).resolve()
    if base not in path.parents:
        raise ValueError("Invalid model path")
    return path


def read_job(job_id: str) -> dict[str, Any]:
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise ValueError("Invalid image job ID")
    path = JOBS / (job_id + ".json")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["status"] in {"running", "queued"} and job_id not in active_jobs:
        return {"status": "failed", "images": [], "error": "Diffusers worker restarted during generation"}
    return result


active_jobs: set[str] = set()


def write_job(job_id: str, result: dict[str, Any]) -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    path = JOBS / (job_id + ".json")
    temporary = JOBS / (job_id + ".tmp")
    with lock:
        temporary.write_text(json.dumps(result), encoding="utf-8")
        temporary.replace(path)


def generate(job_id: str, data: dict[str, Any]) -> None:
    write_job(job_id, {"status": "running", "images": []})
    try:
        import torch
        from diffusers import AutoencoderKL, StableDiffusionXLPipeline

        checkpoint = model_path("checkpoints", data["checkpoint"])
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        pipe = StableDiffusionXLPipeline.from_single_file(str(checkpoint),
                                                            torch_dtype=dtype)
        if data.get("vae"):
            vae = model_path("vae", data["vae"])
            pipe.vae = AutoencoderKL.from_single_file(str(vae), torch_dtype=dtype)
        pipe.to("cuda" if torch.cuda.is_available() else "cpu")
        names, weights = [], []
        for index, item in enumerate(data.get("loras", [])):
            path = model_path("loras", item["name"])
            adapter_name = f"adapter_{index}"
            pipe.load_lora_weights(str(path.parent), weight_name=path.name,
                                   adapter_name=adapter_name)
            names.append(adapter_name)
            weights.append(float(item.get("strength_model", 1)))
        if names:
            pipe.set_adapters(names, adapter_weights=weights)
        generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu")
        generator.manual_seed(int(data["seed"]))
        def on_step(_pipe: Any, step: int, _timestep: Any,
                    callback_kwargs: dict[str, Any]) -> dict[str, Any]:
            write_job(job_id, {"status": "running", "images": [],
                               "progress": round(100 * (step + 1) / 45)})
            return callback_kwargs

        image = pipe(prompt=data["positive_prompt"],
                     negative_prompt=data["negative_prompt"], width=1024,
                     height=1536, num_inference_steps=45, guidance_scale=7,
                     generator=generator, callback_on_step_end=on_step).images[0]
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        filename = f"EverSpark_Diffusers_{job_id}.png"
        image.save(OUTPUTS / filename)
        write_job(job_id, {"status": "completed", "images": [
            {"filename": filename, "subfolder": "", "type": "output"}]})
        del image, pipe
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as exc:
        write_job(job_id, {"status": "failed", "images": [], "error": str(exc)})
    finally:
        with lock:
            active_jobs.discard(job_id)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code: int, data: dict[str, Any]) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond(200, {"ok": True})
        elif self.path == "/models":
            self.respond(200, {"checkpoints": inventory("checkpoints"),
                               "loras": inventory("loras"), "vaes": inventory("vae")})
        elif self.path.startswith("/jobs/"):
            try:
                self.respond(200, read_job(self.path.removeprefix("/jobs/")))
            except (ValueError, FileNotFoundError):
                self.respond(404, {"error": "Unknown image job"})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/jobs":
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 1_000_000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Image request must be an object")
            model_path("checkpoints", data["checkpoint"])
            if data.get("vae"):
                model_path("vae", data["vae"])
            for item in data.get("loras", []):
                model_path("loras", item["name"])
                if float(item.get("strength_model", 1)) != float(item.get("strength_clip", 1)):
                    raise ValueError("Diffusers requires equal LoRA strengths")
            job_id = uuid.uuid4().hex
            with lock:
                active_jobs.add(job_id)
                write_job(job_id, {"status": "queued", "images": []})
                executor.submit(generate, job_id, data)
            self.respond(202, {"id": job_id})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.respond(400, {"error": str(exc)})


def main() -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    address = urlparse(os.environ.get("EVERSPARK_DIFFUSERS_URL", "http://127.0.0.1:8190"))
    host = os.environ.get("EVERSPARK_DIFFUSERS_HOST", address.hostname or "127.0.0.1")
    port = int(os.environ.get("EVERSPARK_DIFFUSERS_PORT", str(address.port or 8190)))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
