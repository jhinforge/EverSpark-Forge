"""Bounded optional download measurements; never change Node admission."""
import math
from urllib.parse import urlsplit


def validate(value):
    if not isinstance(value, dict) or value.get("status") not in {"pending", "running", "completed", "failed"}:
        return None
    result = {"status": value["status"]}
    for key in ("started_at", "finished_at", "server_name", "server_url", "error", "region", "server_region", "country", "method", "server_colo", "model_filename", "server_location", "server_country", "error_code"):
        if key in value:
            if not isinstance(value[key], str) or len(value[key]) > 300:
                return None
            result[key] = value[key]
    if value["status"] == "completed":
        speed = value.get("download_mb_s")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or speed < 0:
            return None
        regional = result.get("region") in {"AS", "EU", "NA", "SA", "AF", "OC"} and result.get("region") == result.get("server_region")
        cloudflare = result.get("method") == "cloudflare_http" and result.get("server_url") == "https://speed.cloudflare.com/__down"
        ookla = result.get("method") == "ookla_cli"
        if ookla:
            for key in ("upload_mb_s", "latency_ms", "jitter_ms", "packet_loss_percent", "elapsed_seconds"):
                item = value.get(key)
                if item is None and key in {"jitter_ms", "packet_loss_percent"}:
                    continue
                if (isinstance(item, bool) or not isinstance(item, (int, float))
                        or not math.isfinite(item) or item < 0
                        or (key == "packet_loss_percent" and item > 100)
                        or (key == "elapsed_seconds" and not 0 < item <= 180)):
                    return None
                result[key] = item
            for key in ("server_id", "bytes_received"):
                item = value.get(key)
                if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                    return None
                result[key] = item
            if not all(result.get(key) for key in ("server_name", "server_location", "server_country")):
                return None
        model_source = False
        if result.get("method") == "default_model_http":
            try:
                url = urlsplit(result.get("server_url", ""))
                model_source = (url.scheme == "https" and url.netloc == "huggingface.co"
                                and "/resolve/" in url.path and not url.query and not url.fragment)
            except ValueError:
                pass
            if not model_source:
                return None
        if cloudflare or model_source:
            elapsed, received = value.get("elapsed_seconds"), value.get("bytes_received")
            if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                    or not math.isfinite(elapsed) or not 27 <= elapsed <= 35
                    or isinstance(received, bool) or not isinstance(received, int) or received <= 0):
                return None
            result.update(elapsed_seconds=elapsed, bytes_received=received)
            if model_source and not math.isclose(speed, received / elapsed / 1_000_000, rel_tol=1e-6):
                return None
        result.update(download_mb_s=speed, threshold_mb_s=50, regional=regional,
                      qualified=(speed >= 50 if ookla or cloudflare or model_source or regional else None))
    return result
