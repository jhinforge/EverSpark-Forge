"""Audio entry point for the existing Envoy task executor."""
import contextlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from Archon.Vault.runtime_config import load_config
from Aegis.Storage.output_resources import OutputResources
from Legate.Forge.AudioForge.audio_forge.voxcpm import synthesize, validate_runtime


def run(action, payload, config=None):
    configuration = config or load_config()
    settings = configuration["audio_forge"]
    if action == "stream":
        from Aegis.Storage.node_output_stream import send_output
        return send_output(configuration, payload, forge="audio")
    if action == "synthesize":
        result = synthesize(payload, settings)
        from Aegis.Storage.node_media_access import media_urls
        result["audio"] = media_urls(result.get("audio", []), forge="audio")
        return result
    if action == "fetch":
        if set(payload) != {"filename", "offset"}:
            raise ValueError("Invalid audio fetch request")
        return OutputResources(settings["output_directory"], {".wav"}).chunk(
            payload["filename"], "", payload["offset"])
    if action == "history":
        if set(payload) != {"limit"} or isinstance(payload["limit"], bool) or not isinstance(payload["limit"], int):
            raise ValueError("Invalid audio history request")
        outputs = OutputResources(settings["output_directory"], {".wav"})
        # Speech outputs live directly in the output directory, not in model/cache folders.
        files = (path for path in outputs.files() if path.parent == outputs.directory)
        import itertools
        from Aegis.Storage.node_media_access import media_urls
        return {"audio": media_urls([{"filename": path.name} for path in
                          itertools.islice(files, max(1, min(payload["limit"], 100)))], forge="audio")}
    if action == "health":
        torch = validate_runtime()
        if not torch.cuda.is_available():
            raise RuntimeError("Audio Forge requires an NVIDIA GPU")
        if not (Path(settings["model_directory"]) / "config.json").is_file():
            raise RuntimeError("Audio Forge model is not installed")
        return {"ok": True, "backend": "voxcpm2"}
    raise ValueError("Unsupported Audio Forge action")


def main():
    if len(sys.argv) != 3 or len(sys.argv[2].encode("utf-8")) > 60000:
        return 2
    payload = json.loads(sys.argv[2])
    if not isinstance(payload, dict):
        return 2
    # Model libraries print progress; protocol stdout must contain only JSON.
    with contextlib.redirect_stdout(sys.stderr):
        value = run(sys.argv[1], payload)
    print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
