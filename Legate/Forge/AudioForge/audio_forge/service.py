"""Speech execution belongs to Audio Forge; file transport belongs to Storage."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit
from Aegis.Storage.output_resources import OutputResources
from Archon.Gate.remote_target import target
from Legate.Warden.audio_backend import run
from .voxcpm import validate_instruction


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
        validate_instruction(instruction, self.config["audio_forge"]["max_text_chars"])
        if notify:
            notify("Audio Forge: synthesizing speech")
        result = self._call("synthesize", instruction)
        if result.get("status") != "completed" or not isinstance(result.get("audio"), list) or not result["audio"]:
            raise RuntimeError("Audio Forge did not return completed speech")
        if self.url:
            result["audio"] = self._media_links(result["audio"])
        else:
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
        return self._media_links(audio[:limit]) if self.url else audio[:limit]

    def health(self):
        return self._call("health", {})

    def _media_links(self, resources):
        import ipaddress
        for resource in resources:
            self.outputs.path(resource["filename"], require_file=False)
            fallback = "/api/audio/file?" + urlencode({
                "filename": resource["filename"], **self.target_identity})
            resource["fallback_url"] = fallback
            direct = resource.get("url", "")
            address = urlsplit(direct)
            try:
                private = address.scheme == "http" and ipaddress.ip_address(address.hostname) in ipaddress.ip_network("100.64.0.0/10")
            except (ValueError, TypeError):
                private = False
            resource["url"] = direct if private and not address.username else fallback
        return resources

    def open_audio(self, filename):
        self.outputs.path(filename, require_file=False)
        if not self.url:
            return None
        if "node_id" not in self.target_identity:
            raise RuntimeError("Select a registered Audio Node for streaming outputs")
        url = self.url.rsplit("/", 1)[0] + "/output?" + urlencode({
            **self.target_identity, "forge": "audio", "filename": filename})
        return urlopen(url, timeout=320)

    def archive_job(self, job_id=""):
        from Aegis.Storage.output_archives import validate_result
        return validate_result(self._call("archive", {"job_id": job_id}))

    def audio_path(self, filename):
        if self.url:
            return self.outputs.receive(filename, "", lambda offset:
                self._call("fetch", {"filename": filename, "offset": offset}))
        return self.outputs.path(filename)
