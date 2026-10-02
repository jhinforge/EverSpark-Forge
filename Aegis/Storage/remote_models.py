"""Route model transfers to a fixed Forge node; backups remain on the host."""
import copy
import json
import re
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from Archon.Gate.remote_target import target
from download_manager import DownloadError

IMAGE_KINDS = {"checkpoint", "diffusion_model", "lora", "vae"}


class RemoteModels:
    def __init__(self, config, catalog):
        self.config, self.catalog = config, catalog
        self.bindings = config.get("remote_nodes", {})
        self.latest = {}
        self.lock = threading.RLock()

    def destination(self, kind):
        if kind not in IMAGE_KINDS | {"concept_model"}:
            raise DownloadError("Unsupported model resource kind")
        forge = "concept" if kind == "concept_model" else "image"
        identity = self.bindings.get(f"{forge}_node_id")
        if not identity:
            raise DownloadError(f"Select a {forge.title()} Forge node before downloading its models")
        return identity, forge

    def call(self, node, forge, action, payload):
        url, identity = target(node, self.bindings.get("control_url", "http://127.0.0.1:8765"))
        message = json.dumps(payload, ensure_ascii=False)
        if len(message.encode()) > 58000:
            raise DownloadError("Node storage request exceeds the transfer limit")
        request = Request(url, data=json.dumps({**identity, "forge": forge,
            "action": action, "message": message, "timeout": 120}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=130) as response:
                envelope = json.load(response)
            return json.loads(envelope["output"])
        except HTTPError as exc:
            # The node channel redacts diagnostics; retain its bounded detail.
            try:
                error = json.loads(exc.read(60000))
            except (ValueError, UnicodeError):
                error = {}
            raise DownloadError(error.get("detail") or error.get("error") or
                                f"Node model storage failed (HTTP {exc.code})") from exc
        except (OSError, ValueError, KeyError) as exc:
            raise DownloadError("Node model storage is unavailable; update the node source and retry") from exc

    def cloud_config(self):
        settings = self.catalog.settings
        if not settings.enabled or not settings.config_file or not settings.config_file.is_file():
            raise DownloadError("Configure rclone storage before pulling cloud models")
        storage = copy.deepcopy(self.config["storage"])
        storage["rclone"].pop("config_file", None)
        storage["rclone"].pop("binary", None)
        return {"storage": storage, "rclone_config": settings.config_file.read_text(encoding="utf-8"),
                "paths": self.catalog.paths.read()}

    def wrap(self, job, node, forge, channel):
        if job is None:
            return None
        result = {**job, "job_id": f"{node}:{forge}:{job['job_id']}",
                  "target_node_id": node, "target_forge": forge}
        with self.lock:
            self.latest[channel] = result["job_id"]
        return result

    def start(self, channel, kind, **payload):
        node, forge = self.destination(kind)
        if channel == "pull":
            payload["cloud"] = self.cloud_config()
        job = self.call(node, forge, f"models_{channel}_start", {"kind": kind, **payload})
        return self.wrap(job, node, forge, channel)

    def job(self, channel, job_id="", operation="job"):
        with self.lock:
            identifier = job_id or self.latest.get(channel, "")
        if not identifier:
            return None
        if not re.fullmatch(r"[0-9a-f]{32}:(image|concept):[0-9a-f]{32}", identifier):
            raise DownloadError("Invalid node model job ID")
        node, forge, local_id = identifier.split(":")
        # Encoded identity survives host runtime replacement and node selection.
        job = self.call(node, forge, f"models_{channel}_{operation}", {"job_id": local_id})
        return self.wrap(job, node, forge, channel)

    def annotate(self, resources):
        result = copy.deepcopy(resources)
        for forge, groups in (("image", list(result.get("image", {}).values())),
                              ("concept", [result.get("concept", {}).get("models", [])])):
            node = self.bindings.get(f"{forge}_node_id")
            entries = [entry for group in groups for entry in group]
            if entries and node:
                queries = [{"kind": kind, "name": entry["name"], "format": entry.get("format", "")}
                    for kind, group in (result.get("image", {}).items() if forge == "image"
                        else [("concept_model", entries)]) for entry in group]
                installed = []
                for offset in range(0, len(queries), 100):
                    installed.extend(self.call(node, forge, "models_installed", {"entries": queries[offset:offset + 100]}))
                if not isinstance(installed, list) or len(installed) != len(entries):
                    raise DownloadError("Invalid node model inventory")
            else:
                installed = [False] * len(entries)
            for entry, present in zip(entries, installed):
                entry.update(installed=bool(present), target_node_id=node or "", target_forge=forge)
        result["targets"] = {forge: self.bindings.get(f"{forge}_node_id", "") for forge in ("image", "concept")}
        return result
