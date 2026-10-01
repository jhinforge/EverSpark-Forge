"""Speech execution belongs to Audio Forge; file transport belongs to Storage."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from Aegis.Storage.output_resources import OutputResources
from Archon.Gate.remote_target import target
from Legate.Warden.audio_backend import run


class AudioService:
    def __init__(self, config):
        self.config = config
        settings = config["audio_forge"]
        remote = config.get("remote_nodes", {})
        identity = remote.get("audio_node_id") or remote.get("audio_instance_id")
        self.url, self.target_identity = target(identity, remote.get("control_url", "http://127.0.0.1:8765")) if identity else (None, {})
        directory = Path(settings["output_directory"])
        if identity:
            directory = directory / "remote" / str(identity)
        self.outputs = OutputResources(directory, {".wav"})

    def _call(self, action, payload):
        if not self.url:
            return run(action, payload, self.config)
        message = json.dumps(payload, ensure_ascii=False)
        if len(message.encode("utf-8")) > 60000:
            raise ValueError("Audio Forge task exceeds the node limit")
        timeout = {"timeout": 610} if "node_id" in self.target_identity else {}
        body = json.dumps({**self.target_identity, **timeout, "forge": "audio", "action": action,
                           "message": message}, ensure_ascii=False).encode("utf-8")
        request = Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=620) as response:
                envelope = json.load(response)
        except HTTPError as exc:
            try:
                failure = json.loads(exc.read(60000))
                if not isinstance(failure, dict):
                    raise ValueError("Expected error object")
            except (ValueError, UnicodeError):
                failure = {}
            finally:
                exc.close()
            detail = failure.get("detail") or failure.get("error") or exc.reason
            code = failure.get("exit_code")
            suffix = f", exit code {code}" if code is not None else ""
            raise RuntimeError(f"Audio Forge {action} failed (HTTP {exc.code}{suffix}): {detail}") from exc
        try:
            value = json.loads(envelope["output"])
            if not isinstance(value, dict):
                raise ValueError("Expected Audio result object")
            return value
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Remote Audio Forge returned invalid output") from exc

    def execute(self, instruction, selection=None, notify=None):
        if (not isinstance(instruction, dict) or set(instruction) != {"text"}
                or not isinstance(instruction["text"], str) or not instruction["text"].strip()
                or len(instruction["text"]) > self.config["audio_forge"]["max_text_chars"]):
            raise ValueError("Audio Forge requires non-empty bounded speech text")
        if notify:
            notify("Audio Forge: synthesizing speech")
        result = self._call("synthesize", instruction)
        if result.get("status") != "completed" or not isinstance(result.get("audio"), list) or not result["audio"]:
            raise RuntimeError("Audio Forge did not return completed speech")
        for resource in result["audio"]:
            self.audio_path(resource["filename"])
        return result

    def history(self, limit=24):
        limit = max(1, min(int(limit), 100))
        result = self._call("history", {"limit": limit})
        audio = result.get("audio")
        if not isinstance(audio, list):
            raise RuntimeError("Audio Forge returned invalid history")
        for resource in audio:
            self.outputs.path(resource["filename"], require_file=False)
        return audio[:limit]

    def health(self):
        return self._call("health", {})

    def audio_path(self, filename):
        if self.url:
            return self.outputs.receive(filename, "", lambda offset:
                self._call("fetch", {"filename": filename, "offset": offset}))
        return self.outputs.path(filename)
