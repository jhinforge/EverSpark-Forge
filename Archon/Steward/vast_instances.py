"""Read-only Vast instance inventory for Steward."""

from __future__ import annotations

import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


API_URL = "https://console.vast.ai/api/v1/instances"
CREATE_URL = "https://console.vast.ai/api/v0/asks/"
ACCOUNT_URL = "https://console.vast.ai/api/v0/users/current"
_CURSOR = re.compile(r"[A-Za-z0-9_+/=-]{0,1024}\Z")
_STARTUP_STATUS = re.compile(r"(?:failed:)?(?:package_install|source_checkout|source_ready|agent_launch|install_tailscale|start_tailscaled|authenticate_tailscale|register_agent|registered|registration_failed:(?:http_[0-9]{3}|[A-Za-z]+))\Z")


class VastError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class VastInstances:
    def __init__(self, store, *, opener=urlopen):
        self.store = store
        self.opener = opener

    def configured(self) -> bool:
        return bool(self.store.get())

    def test(self, key: str) -> dict:
        self._valid_key(key)
        return self._request(key, "")

    def save(self, key: str) -> dict:
        self._valid_key(key)
        candidate = key.strip()
        first_page = self.test(candidate)
        self.store.set(candidate)
        return first_page

    @staticmethod
    def _valid_key(key: str) -> None:
        if not isinstance(key, str) or not key.strip() or any(char in key for char in "\r\n\x00"):
            raise VastError("Enter a valid Vast API Key", 400)
        try:
            size = len(key.encode("utf-8"))
        except UnicodeError:
            raise VastError("Enter a valid Vast API Key", 400) from None
        if size > 2560:
            raise VastError("Enter a valid Vast API Key", 400)

    def remove(self) -> None:
        self.store.delete()

    def balance(self) -> dict:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        request = Request(ACCOUNT_URL, headers={"Authorization": f"Bearer {key}",
                                                "Accept": "application/json"})
        try:
            with self.opener(request, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise VastError("Vast rejected the API Key", 401) from None
            raise VastError(f"Could not read Vast balance (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Could not read Vast balance") from None
        credit = payload.get("credit") if isinstance(payload, dict) else None
        if isinstance(credit, bool) or not isinstance(credit, (int, float)) or not math.isfinite(credit):
            raise VastError("Vast returned an invalid credit balance")
        return {"balance_usd": credit}

    def destroy(self, instance_id: int) -> None:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        if isinstance(instance_id, bool) or not isinstance(instance_id, int) or instance_id < 1:
            raise VastError("Invalid instance ID", 400)
        request = Request(f"https://console.vast.ai/api/v0/instances/{instance_id}",
                          headers={"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"}, method="DELETE")
        try:
            with self.opener(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise VastError("Vast rejected the API Key", 401) from None
            if exc.code == 404:
                raise VastError("Vast instance was not found", 404) from None
            if exc.code == 429:
                raise VastError("Vast rate limit reached; try again shortly", 429) from None
            raise VastError(f"Could not destroy Vast instance (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Cannot confirm whether Vast destroyed the instance; refresh the list before retrying") from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise VastError("Vast did not confirm instance destruction; refresh the list before retrying")

    def create(self, offer: dict, image: str, node_env: dict | None = None) -> dict:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        disk = offer["disk_gb"]
        if not isinstance(image, str) or not image.startswith("nvidia/cuda:"):
            raise VastError("Invalid base image", 400)
        # SSH mode supplies the first connection. Git is installed inside the
        # container, then the source is cloned; Forge installation is separate.
        status = "/workspace/everspark-startup.status"
        onstart = (
            f"printf 'package_install\\n' > {status}; "
            "(apt-get update && apt-get install -y git ca-certificates curl python3) || "
            f"{{ printf 'failed:package_install\\n' > {status}; exit 1; }}; "
            f"printf 'source_checkout\\n' > {status}; "
            "(if [ ! -d /workspace/EverSpark-Forge/.git ]; then "
            "git clone --branch refactor/distributed-architecture --single-branch "
            "https://github.com/jhinforge/EverSpark-Forge.git /workspace/EverSpark-Forge; fi) || "
            f"{{ printf 'failed:source_checkout\\n' > {status}; exit 1; }}; "
            f"printf 'source_ready\\n' > {status}"
        )
        if node_env:
            onstart += (f"; printf 'agent_launch\\n' > {status}; "
                        "(nohup bash /workspace/EverSpark-Forge/Legate/Envoy/start_node.sh "
                        ">/workspace/everspark-node.log 2>&1 </dev/null &)")
        body = {"image": image, "disk": disk, "runtype": "ssh_direct",
                "onstart": onstart, "cancel_unavail": True, "label": "EverSpark Forge"}
        if node_env:
            body["env"] = node_env
        request = Request(f"{CREATE_URL}{offer['id']}/",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="PUT")
        try:
            with self.opener(request, timeout=20) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise VastError("Vast rejected the API Key", 401) from None
            raise VastError(f"Vast could not create this instance (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Cannot reach Vast or read its rental response") from None
        if not isinstance(payload, dict) or payload.get("success") is False or not isinstance(payload.get("new_contract"), int):
            raise VastError("Vast did not create an instance; search again")
        return {"instance_id": payload["new_contract"], "image": image, "disk_gb": disk}

    def startup_diagnostics(self, instance_id: int) -> dict:
        """Read the Pod's fixed, sanitized startup state via Vast's execute endpoint."""
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        if isinstance(instance_id, bool) or not isinstance(instance_id, int) or instance_id < 1:
            raise VastError("Invalid instance ID", 400)
        request = Request(f"https://console.vast.ai/api/v0/instances/command/{instance_id}",
            data=json.dumps({"command": "cat /workspace/everspark-startup.status"}).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="PUT")
        try:
            with self.opener(request, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise VastError(f"Could not inspect Pod startup (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Could not inspect Pod startup") from None
        result_url = payload.get("result_url") if isinstance(payload, dict) else None
        parsed = urlsplit(result_url) if isinstance(result_url, str) else None
        if (not parsed or parsed.scheme != "https" or parsed.netloc != "s3.amazonaws.com" or
            not parsed.path.startswith("/vast.ai/instance_logs/") or parsed.fragment or
            payload.get("success") is False):
            raise VastError("Vast returned an invalid startup result URL")
        for attempt in range(4):
            try:
                with self.opener(Request(result_url), timeout=5) as response:
                    output = response.read(8192).decode("utf-8", "replace").strip()
            except HTTPError as exc:
                if exc.code != 404:
                    raise VastError("Could not read Pod startup result") from None
                output = ""
            except (URLError, TimeoutError, OSError):
                raise VastError("Could not read Pod startup result") from None
            if output:
                break
            if attempt < 3:
                time.sleep(1)
        stage = next((line.strip() for line in reversed(output.splitlines())
                      if _STARTUP_STATUS.fullmatch(line.strip())), None)
        return {"stage": stage or "pending"}

    def attach_ssh(self, instance_id: int, public_key: str) -> None:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        request = Request(f"https://console.vast.ai/api/v0/instances/{instance_id}/ssh",
            data=json.dumps({"ssh_key": public_key}).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST")
        try:
            with self.opener(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            try:
                detail = self._ssh_error(json.load(exc), public_key, key)
            except (ValueError, OSError):
                detail = ""
            raise VastError(f"Vast SSH key request failed (HTTP {exc.code})"
                            + (f": {detail}" if detail else "")) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Could not attach deployment SSH key to Vast instance") from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            detail = self._ssh_error(payload, public_key, key)
            raise VastError("Vast rejected the deployment SSH key"
                            + (f": {detail}" if detail else ""))

    @staticmethod
    def _ssh_error(payload: object, public_key: str, api_key: str) -> str:
        if not isinstance(payload, dict):
            return "Unexpected Vast response"
        for field in ("error", "msg"):
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return value.replace(public_key, "[SSH key]").replace(api_key, "[API key]")[:300]
        return "Unexpected Vast response"

    def one(self, instance_id: int) -> dict:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        if not isinstance(instance_id, int) or isinstance(instance_id, bool) or instance_id < 1:
            raise VastError("Invalid instance ID", 400)
        request = Request(f"https://console.vast.ai/api/v0/instances/{instance_id}",
                          headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        try:
            with self.opener(request, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                raise VastError("Vast instance was not found", 404) from None
            raise VastError("Could not inspect Vast instance") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Could not inspect Vast instance") from None
        item = payload.get("instances") if isinstance(payload, dict) else None
        if not isinstance(item, dict) or item.get("id") != instance_id:
            raise VastError("Vast instance was not found", 404)
        return {field: item.get(field) for field in (
            "id", "actual_status", "ssh_host", "ssh_port", "gpu_name", "num_gpus")}

    def list(self, after_token: str = "") -> dict:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        if not isinstance(after_token, str) or not _CURSOR.fullmatch(after_token):
            raise VastError("Invalid page cursor", 400)
        return self._request(key, after_token)

    def _request(self, key: str, after_token: str) -> dict:
        query = {"limit": 25}
        if after_token:
            query["after_token"] = after_token
        request = Request(f"{API_URL}?{urlencode(query)}",
                          headers={"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        try:
            with self.opener(request, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise VastError("Vast rejected the API Key", 401) from None
            if exc.code == 429:
                raise VastError("Vast rate limit reached; try again shortly", 429) from None
            raise VastError(f"Vast request failed (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            raise VastError("Cannot reach Vast or read its response") from None
        if not isinstance(payload, dict) or payload.get("success") is False or not isinstance(
            payload.get("instances"), list
        ):
            raise VastError("Vast returned an invalid instance list")
        # Never forward full provider objects: they may contain tokens, environment
        # variables, or launch commands. The UI needs only inventory fields.
        instances = []
        for item in payload["instances"]:
            if isinstance(item, dict):
                instances.append({field: item.get(field) for field in (
                    "id", "label", "actual_status", "gpu_name", "num_gpus",
                    "dph_total", "geolocation", "ssh_host", "ssh_port")})
        return {"instances": instances, "total": payload.get("total_instances"),
                "next_token": payload.get("next_token") or None}
