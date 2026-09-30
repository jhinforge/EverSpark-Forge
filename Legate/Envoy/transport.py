"""Generic HTTP(S) Node transport; optional HTTP proxy is deployment configuration."""
import http.client
import json
from urllib.parse import urlsplit


class BridgeError(RuntimeError):
    def __init__(self, status):
        super().__init__(f"Node transport returned HTTP {status}")
        self.status = status


class Transport:
    def __init__(self, url, proxy=None):
        self.url = url.rstrip("/")
        self.address = urlsplit(self.url)
        if self.address.scheme not in {"http", "https"} or not self.address.hostname or self.address.username or self.address.query or self.address.fragment:
            raise ValueError("Invalid Archon Node URL")
        self.proxy = urlsplit(proxy) if proxy else None
        if self.proxy and (self.proxy.scheme != "http" or not self.proxy.hostname or self.address.scheme != "http"):
            raise ValueError("HTTP proxy requires an HTTP Node URL")

    def request(self, path, body):
        address = self.proxy or self.address
        connection_type = http.client.HTTPSConnection if address.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(address.hostname, address.port, timeout=25)
        target = self.url+path if self.proxy else self.address.path.rstrip("/")+path
        try:
            connection.request("POST", target, json.dumps({"protocol_version": 2, **body}, ensure_ascii=False).encode(),
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(131073)
            if len(raw) > 131072:
                raise BridgeError(413)
            if response.status != 200:
                raise BridgeError(response.status)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Invalid Node response")
            return data
        finally:
            connection.close()
