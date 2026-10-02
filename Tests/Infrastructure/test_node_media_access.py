"""Direct media access requires an expiring file-specific signature."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from Aegis.Storage.node_media_access import ImageServer, signature
from Aegis.Storage.output_resources import OutputResources


class MediaAccessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = b"fixture" * 10000
        (self.root / "render.png").write_bytes(self.data)
        (self.root / "speech.wav").write_bytes(self.data)
        self.server = ImageServer(("127.0.0.1", 0),
            OutputResources(self.root, {".png", ".wav"}), "private-key")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def signed(self, filename="render.png", expires=None):
        expires = expires or int(time.time()) + 60
        return self.url + "/file?" + urlencode({"filename": filename, "subfolder": "",
            "expires": expires, "signature": signature("private-key", filename, "", expires)})

    def test_signed_image_url_streams_original_and_supports_head(self):
        with urlopen(self.signed()) as source:
            self.assertEqual(source.headers["Content-Type"], "image/png")
            self.assertEqual(source.read(), self.data)
        with urlopen(Request(self.signed(), method="HEAD")) as source:
            self.assertEqual(int(source.headers["Content-Length"]), len(self.data))
            self.assertEqual(source.read(), b"")

    def test_audio_range_supports_browser_seeking(self):
        request = Request(self.signed("speech.wav"), headers={"Range": "bytes=2-9"})
        with urlopen(request) as source:
            self.assertEqual(source.status, 206)
            self.assertEqual(source.headers["Content-Type"], "audio/wav")
            self.assertEqual(source.headers["Content-Range"], f"bytes 2-9/{len(self.data)}")
            self.assertEqual(source.read(), self.data[2:10])

    def test_expired_or_changed_signature_is_denied(self):
        for url in (self.signed(expires=int(time.time())-1),
                    self.signed().replace("render.png", "speech.wav")):
            with self.assertRaises(HTTPError) as caught:
                urlopen(url)
            self.assertEqual(caught.exception.code, 403)

    def test_signing_endpoint_requires_private_bearer_key(self):
        body = json.dumps([{"filename": "render.png"}]).encode()
        request = Request(self.url + "/sign", data=body)
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        request.add_header("Authorization", "Bearer private-key")
        with urlopen(request) as source:
            descriptor = json.load(source)["images"][0]
        self.assertNotIn("private-key", descriptor["url"])
        with urlopen(descriptor["url"]) as source:
            self.assertEqual(source.read(), self.data)

    def test_signature_does_not_allow_path_traversal(self):
        expires = int(time.time())+60
        filename = "../private.png"
        query = urlencode({"filename": filename, "subfolder": "", "expires": expires,
                          "signature": signature("private-key", filename, "", expires)})
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/file?" + query)
        self.assertEqual(caught.exception.code, 404)
