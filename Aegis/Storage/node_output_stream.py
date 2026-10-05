"""Send requested output bytes once over the existing outbound Node connection."""
import http.client
import os
import re
from urllib.parse import urlsplit
from Aegis.Storage.output_resources import OutputResources

def send_output(config, payload, forge="image"):
    if forge not in {"image", "audio"}:
        raise ValueError("Invalid output owner")
    token = payload.get("token", "")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValueError("Invalid output stream")
    if "archive" in payload:
        raise ValueError("ZIPs use the private archive URL service, not output streams")
    url = os.environ.get("EVERSPARK_NODE_URL") or os.environ.get("EVERSPARK_NODE_BRIDGE_URL", "")
    address = urlsplit(url.rstrip("/"))
    if address.scheme not in {"http", "https"} or not address.hostname or address.username or address.query or address.fragment:
        raise ValueError("Node connection URL unavailable")
    outputs = OutputResources(config[forge + "_forge"]["output_directory"],
                              {".wav"} if forge == "audio" else {".png", ".jpg", ".jpeg", ".webp"})
    path = outputs.path(payload.get("filename", ""), payload.get("subfolder", ""))
    size = path.stat().st_size
    if not 0 < size <= outputs.max_bytes:
        raise ValueError("Output exceeds transfer limit")
    proxy = urlsplit(os.environ["EVERSPARK_NODE_PROXY"]) if os.environ.get("EVERSPARK_NODE_PROXY") else None
    if proxy and (proxy.scheme != "http" or not proxy.hostname or address.scheme != "http"):
        raise ValueError("Invalid Node proxy")
    endpoint = proxy or address
    connection_type = http.client.HTTPSConnection if endpoint.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(endpoint.hostname, endpoint.port, timeout=60)
    destination = (url.rstrip("/") + "/node/output" if proxy else address.path.rstrip("/") + "/node/output")
    try:
        with path.open("rb") as source:
            connection.request("POST", destination, body=source, headers={
                "Content-Type": "application/octet-stream", "Content-Length": str(size),
                "Authorization": "Bearer " + token})
            response = connection.getresponse()
            response.read(4096)
            if response.status != 200:
                raise RuntimeError("Output consumer rejected the stream")
    finally:
        connection.close()
    return {"ok": True}
