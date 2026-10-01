"""VoxCPM 2.0.3 text-only adapter. No reference audio or unsupported seed argument."""
import os
import tempfile
import uuid
from pathlib import Path
from Aegis.Storage.output_resources import OutputResources


def synthesize(payload, settings):
    if (not isinstance(payload, dict) or set(payload) != {"text"}
            or not isinstance(payload["text"], str) or not payload["text"].strip()
            or len(payload["text"]) > settings["max_text_chars"]):
        raise ValueError("Invalid VoxCPM2 speech text")
    model_path = Path(settings["model_directory"])
    if not (model_path / "config.json").is_file():
        raise RuntimeError("Deploy Audio Forge before synthesizing speech")
    from voxcpm import VoxCPM
    import soundfile as sf
    model = VoxCPM.from_pretrained(str(model_path), load_denoiser=False)
    wav = model.generate(text=payload["text"], cfg_value=2.0, inference_timesteps=10)
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
        "sample_rate": rate, "text": payload["text"]}]}
