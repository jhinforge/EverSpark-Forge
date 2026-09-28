"""Read-only Vast instance inventory for Steward."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://console.vast.ai/api/v1/instances"
_CURSOR = re.compile(r"[A-Za-z0-9_+/=-]{0,1024}\Z")


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
