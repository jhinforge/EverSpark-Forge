"""Image Forge node entry point; engine state and outputs stay on the image node."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for module_path in ("", "Legate/Forge/ImageForge", "Legate/Forge"):
    sys.path.insert(0, str(ROOT / module_path))

from Archon.Vault.runtime_config import load_config
from image_forge.adapters import create_engines, discover_plugins
from image_forge.gateway import ImageGateway
from image_forge.port import ImageRequest


def run(action: str, payload: dict) -> dict:
    config = load_config()
    if action == "archive":
        from Aegis.Storage.node_media_access import archive_job
        return archive_job(payload)
    if action == "stream":
        from Aegis.Storage.node_output_stream import send_output
        return send_output(config, payload)
    manifests = discover_plugins()
    engines = create_engines(config["image_forge"]["adapters"], config["workflow"], manifests)
    gateway = ImageGateway(engines, config["memory"]["database"],
                           config["image_forge"]["output_directory"],
                           config["image_forge"]["adapter"])
    if action == "resources":
        return gateway.resources(str(payload.get("engine", "")))
    if action == "plugins":
        from image_forge.plugins import PluginManager
        return PluginManager(manifests, gateway).plugins()
    if action == "default_negative":
        selected = gateway.select(str(payload.get("engine", "")))
        return {"negative_prompt": selected.default_negative_prompt(str(payload.get("workflow", "")))}
    if action == "submit":
        request = payload.get("request")
        if not isinstance(request, dict) or set(request) - set(ImageRequest.__dataclass_fields__):
            raise ValueError("Invalid image request")
        job_id, selection = gateway.submit(ImageRequest(**request),
                                           engine=str(payload.get("engine", "")))
        return {"prompt_id": job_id, "selection": selection}
    if action == "poll":
        result = gateway.result(str(payload.get("prompt_id", "")))
        from Aegis.Storage.node_media_access import media_urls
        result["images"] = media_urls(result.get("images", []))
        return result
    if action == "history":
        from Aegis.Storage.node_media_access import media_urls
        return {"images": media_urls(gateway.history(int(payload.get("limit", 24))))}
    if action == "fetch":
        filename = str(payload.get("filename", ""))
        subfolder = str(payload.get("subfolder", ""))
        kind = str(payload.get("type", "output"))
        if kind != "output":
            raise ValueError("Invalid image path")
        return gateway.outputs.chunk(filename, subfolder, payload.get("offset"))
    raise ValueError("Unsupported image task")


def main() -> int:
    if len(sys.argv) != 3 or len(sys.argv[2].encode("utf-8")) > 60000:
        return 2
    payload = json.loads(sys.argv[2])
    if not isinstance(payload, dict):
        return 2
    print(json.dumps(run(sys.argv[1], payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
