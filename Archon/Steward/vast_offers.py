"""Live Vast offer search for the local Archon control plane."""

from __future__ import annotations

import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .vast_instances import VastError


OFFERS_URL = "https://console.vast.ai/api/v0/bundles/"
GPU_NAMES_URL = "https://console.vast.ai/api/v0/gpu_names/unique/"
_COUNTRY = re.compile(r"[A-Za-z]{2}\Z")
_GPU = re.compile(r"[A-Za-z0-9 _.-]{1,64}\Z")


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise VastError(f"Invalid {name}", 400)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise VastError(f"Invalid {name}", 400) from None
    if not math.isfinite(number) or not low <= number <= high:
        raise VastError(f"Invalid {name}", 400)
    return number


class VastOffers:
    def __init__(self, store, *, opener=urlopen):
        self.store = store
        self.opener = opener
        self._gpu_names = ()
        self._gpu_names_at = 0

    def gpu_names(self) -> dict:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        if self._gpu_names_at and time.time() - self._gpu_names_at < 86400:
            return {"gpu_names": list(self._gpu_names)}
        request = Request(GPU_NAMES_URL, headers={"Authorization": f"Bearer {key}",
                                                 "Accept": "application/json"})
        try:
            with self.opener(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise VastError("Vast rejected the API Key", 401) from None
            if exc.code == 429:
                raise VastError("Vast rate limit reached; try again shortly", 429) from None
            raise VastError(f"Vast GPU names request failed (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Cannot reach Vast or read its GPU names") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("gpu_names"), list):
            raise VastError("Vast returned an invalid GPU name list")
        self._gpu_names = tuple(sorted({name for name in payload["gpu_names"]
                                        if isinstance(name, str) and _GPU.fullmatch(name)}))
        self._gpu_names_at = time.time()
        return {"gpu_names": list(self._gpu_names)}

    def _resolve_gpu(self, gpu: str) -> str:
        normalized = " ".join(gpu.strip().replace("_", " ").split())
        # Vast CLI accepts underscores as spaces, but the REST API expects real names.
        if normalized.isdigit():
            normalized = f"RTX {normalized}"
        try:
            names = self.gpu_names()["gpu_names"]
        except VastError:
            names = self._gpu_names
        return next((name for name in names if name.casefold() == normalized.casefold()),
                    normalized.upper() if normalized.lower().startswith("rtx ") else normalized)

    def search(self, filters: dict) -> dict:
        key = self.store.get()
        if not key:
            raise VastError("Configure the Vast API Key first", 409)
        if not isinstance(filters, dict) or set(filters) - {
            "gpu_name", "min_gpu_ram_gb", "country", "max_hourly_usd",
            "min_reliability", "disk_gb", "sort", "num_gpus",
        }:
            raise VastError("Invalid offer filters", 400)

        disk = _number(filters.get("disk_gb", 50), "disk size", 8, 1000)
        if not disk.is_integer():
            raise VastError("Invalid disk size", 400)
        sort = filters.get("sort", "price")
        if sort not in {"price", "reliability"}:
            raise VastError("Invalid sort order", 400)
        query = {
            "type": "on-demand", "limit": 50,
            "verified": {"eq": True}, "rentable": {"eq": True},
            "rented": {"eq": False}, "gpu_arch": {"eq": "nvidia"},
            "disk_space": {"gte": int(disk)},
            "allocated_storage": int(disk),
            "order": [["dph_total", "asc"]] if sort == "price" else [["reliability", "desc"]],
        }
        gpu = filters.get("gpu_name", "")
        if not isinstance(gpu, str) or (gpu and not _GPU.fullmatch(gpu)):
            raise VastError("Invalid GPU name", 400)
        if gpu.strip():
            query["gpu_name"] = {"eq": self._resolve_gpu(gpu)}
        if filters.get("num_gpus") not in (None, ""):
            count = _number(filters["num_gpus"], "GPU count", 1, 32)
            if not count.is_integer():
                raise VastError("Invalid GPU count", 400)
            query["num_gpus"] = {"eq": int(count)}
        country = filters.get("country", "")
        if not isinstance(country, str) or (country and not _COUNTRY.fullmatch(country)):
            raise VastError("Use a two-letter country code", 400)
        if country:
            query["geolocation"] = {"eq": country.upper()}
        if filters.get("min_gpu_ram_gb") not in (None, ""):
            query["gpu_ram"] = {"gte": int(_number(
                filters["min_gpu_ram_gb"], "GPU memory", 1, 192) * 1000)}
        if filters.get("max_hourly_usd") not in (None, ""):
            query["dph_total"] = {"lte": _number(
                filters["max_hourly_usd"], "hourly price", 0.01, 1000)}
        if filters.get("min_reliability") not in (None, ""):
            query["reliability"] = {"gte": _number(
                filters["min_reliability"], "reliability", 0, 1)}

        request = Request(OFFERS_URL, data=json.dumps(query).encode("utf-8"),
                          headers={"Authorization": f"Bearer {key}",
                                   "Accept": "application/json",
                                   "Content-Type": "application/json"}, method="POST")
        try:
            with self.opener(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise VastError("Vast rejected the API Key", 401) from None
            if exc.code == 429:
                raise VastError("Vast rate limit reached; try again shortly", 429) from None
            raise VastError(f"Vast offer search failed (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise VastError("Cannot reach Vast or read its offers") from None
        if (not isinstance(payload, dict) or payload.get("success") is False or
                not isinstance(payload.get("offers"), list)):
            raise VastError("Vast returned an invalid offer list")
        fields = ("id", "gpu_name", "num_gpus", "gpu_ram", "geolocation",
                  "dph_total", "reliability", "disk_space", "storage_cost",
                  "inet_up_cost", "inet_down_cost", "verified")
        offers = [{field: offer.get(field) for field in fields}
                  for offer in payload["offers"] if isinstance(offer, dict)]
        return {"offers": offers, "disk_gb": int(disk),
                "fetched_at": int(time.time()), "limit": 50}
