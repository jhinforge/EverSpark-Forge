"""Restrict LibreSpeed discovery to the Node's public egress continent."""
import json
import re
from urllib.request import Request, build_opener, ProxyHandler

REGIONS = {"AS", "EU", "NA", "SA", "AF", "OC"}
SERVER_LIST = "https://librespeed.org/backend-servers/servers.php"
COUNTRIES = {
    "AS": ("Japan", "Singapore", "India", "Hong Kong", "Taiwan", "South Korea", "China",
           "Indonesia", "Thailand", "Malaysia", "Vietnam", "Philippines", "Bangladesh",
           "Pakistan", "Sri Lanka", "United Arab Emirates", "Saudi Arabia", "Israel"),
    "EU": ("Netherlands", "Germany", "Greece", "Serbia", "Finland", "England", "United Kingdom",
           "Poland", "Czech Republic", "Italy", "France", "Spain", "Sweden", "Norway", "Denmark",
           "Austria", "Switzerland", "Belgium", "Portugal", "Ireland", "Romania", "Hungary"),
    "NA": ("United States", "USA", "Canada", "Mexico"),
    "SA": ("Brazil", "Argentina", "Chile", "Colombia", "Peru", "Uruguay"),
    "AF": ("South Africa", "Kenya", "Egypt", "Nigeria", "Morocco"),
    "OC": ("Australia", "New Zealand"),
}


class RegionError(ValueError):
    pass


def fetch_json(url):
    # Use the Pod's public route, not its private Agent/Tailscale proxy.
    with build_opener(ProxyHandler({})).open(Request(url), timeout=5) as response:
        data = response.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise RegionError("Regional speed test metadata is too large")
    return json.loads(data)


def server_region(server):
    # The official list has location names but no continent field. Unknown
    # locations are excluded rather than guessing from latency or hostname.
    name = server.get("name", "")
    if not isinstance(name, str):
        return None
    for region, countries in COUNTRIES.items():
        if any(re.search(r"\b" + re.escape(country) + r"\b", name, re.I) for country in countries):
            return region
    return None


def discovery(fetch=fetch_json):
    try:
        location = fetch("https://ipwho.is/?fields=success,continent_code,country")
    except (OSError, ValueError):
        raise RegionError("Could not determine Node region; no cross-region test was run") from None
    if not isinstance(location, dict) or location.get("success") is not True or location.get("continent_code") not in REGIONS:
        raise RegionError("Could not determine Node region; no cross-region test was run")
    region = location["continent_code"]
    try:
        servers = fetch(SERVER_LIST)
    except (OSError, ValueError):
        raise RegionError("Regional speed test server list unavailable") from None
    if not isinstance(servers, list):
        raise RegionError("Regional speed test server list unavailable")
    selected = [server for server in servers if isinstance(server, dict) and server_region(server) == region]
    if not selected:
        raise RegionError("No speed test server in the Node region; no cross-region test was run")
    return {"region": region, "country": str(location.get("country", ""))[:100]}, selected
