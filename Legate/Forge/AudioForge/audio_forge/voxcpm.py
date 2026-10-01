"""Pinned upstream VoxCPM2 adapter. Voice Design uses a control prefix."""
import importlib.metadata
import json
import os
import tempfile
import uuid
from pathlib import Path
from Aegis.Storage.output_resources import OutputResources


def validate_source_pin():
    """Check pip's installed VCS provenance against the installer's source pin."""
    requirement = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text().strip()
    source, revision = requirement.removeprefix("voxcpm @ git+").rsplit("@", 1)
    try:
        provenance = json.loads(importlib.metadata.distribution("voxcpm").read_text("direct_url.json") or "{}")
        vcs = provenance.get("vcs_info", {})
        matches = (provenance.get("url") == source and vcs.get("vcs") == "git"
                   and vcs.get("commit_id") == revision)
    except (importlib.metadata.PackageNotFoundError, ValueError, AttributeError, TypeError):
        matches = False
    if not matches:
        raise RuntimeError(f"Audio Forge requires VoxCPM source commit {revision}; redeploy Audio Forge")
    return revision


def validate_runtime():
    """Load the speech SDK and its native extensions without loading a model."""
    validate_source_pin()
    import torch
    import torchaudio
    profiles = {"2.9.1+cu126": "12.6", "2.9.1+cu128": "12.8"}
    if (torch.__version__ not in profiles or torchaudio.__version__ != torch.__version__
            or torch.version.cuda != profiles[torch.__version__]):
        raise RuntimeError("Audio Forge requires matching Torch/torchaudio 2.9.1 CUDA builds; redeploy Audio Forge")
    from voxcpm import VoxCPM
    return torch


def validate_instruction(payload, max_text_chars):
    if (not isinstance(payload, dict) or "text" not in payload
            or set(payload) - {"text", "voice_description"}
            or not isinstance(payload["text"], str) or not payload["text"].strip()
            or len(payload["text"]) > max_text_chars
            or not isinstance(payload.get("voice_description", ""), str)
            or len(payload.get("voice_description", "")) > 1000):
        raise ValueError("Audio Forge requires bounded speech text and an optional voice description")


def synthesize(payload, settings):
    validate_instruction(payload, settings["max_text_chars"])
    model_path = Path(settings["model_directory"])
    if not (model_path / "config.json").is_file():
        raise RuntimeError("Deploy Audio Forge before synthesizing speech")
    from voxcpm import VoxCPM
    import soundfile as sf
    model = VoxCPM.from_pretrained(str(model_path), load_denoiser=False)
    # VoxCPM2 Voice Design expects (control)text. This SDK format stays in Audio.
    control = payload.get("voice_description", "").translate(str.maketrans("", "", "()（）"))
    control = " ".join(control.split())
    model_text = f"({control}){payload['text']}" if control else payload["text"]
    wav = model.generate(text=model_text, cfg_value=2.0, inference_timesteps=10)
    outputs = OutputResources(settings["output_directory"], {".wav"})
    outputs.directory.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + ".wav"
    destination = outputs.path(filename, require_file=False)
    fd, temporary_name = tempfile.mkstemp(prefix=".speech-", suffix=".part", dir=outputs.directory)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        rate = int(model.tts_model.sample_rate)
        sf.write(str(temporary), wav, rate, format="WAV")
        if temporary.stat().st_size > outputs.max_bytes:
            raise ValueError("Speech output exceeds transfer limit")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "completed", "audio": [{"filename": filename,
        "sample_rate": rate, "text": payload["text"],
        **({"voice_description": control} if control else {})}]}
