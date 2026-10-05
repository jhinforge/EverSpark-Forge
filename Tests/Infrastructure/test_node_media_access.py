"""Direct media access requires an expiring file-specific signature."""
import json
import tempfile
import threading
import time
import unittest
import io
import zipfile
from unittest.mock import patch
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
            OutputResources(self.root, {".png", ".wav"}), "private-key", self.root / "archives")
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

    def archive_request(self, job_id=""):
        request = Request(self.url + "/archives", data=json.dumps({"job_id": job_id}).encode(),
                          headers={"Authorization": "Bearer private-key"})
        with urlopen(request) as source:
            return json.load(source)

    def ready_archive(self):
        job = self.archive_request()
        deadline = time.monotonic() + 3
        while job["status"] == "preparing" and time.monotonic() < deadline:
            time.sleep(.01)
            job = self.archive_request(job["job_id"])
        self.assertEqual(job["status"], "ready", job)
        return job

    def test_archive_download_is_signed_retained_and_resumable(self):
        job = self.ready_archive()
        with urlopen(job["url"]) as source:
            data = source.read()
            self.assertEqual(source.headers["Content-Type"], "application/zip")
            self.assertIn("attachment", source.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.read("EverSpark-Outputs/render.png"), self.data)
            self.assertEqual(archive.read("EverSpark-Outputs/speech.wav"), self.data)
        with urlopen(Request(job["url"], headers={"Range": "bytes=10-29"})) as source:
            self.assertEqual(source.status, 206)
            self.assertEqual(source.read(), data[10:30])
        self.assertTrue(self.server.archives.path(job["job_id"]).is_file())
        # A media signature cannot authorize an archive, and vice versa.
        with self.assertRaises(HTTPError) as caught:
            urlopen(job["url"].replace("/archive?", "/file?"))
        self.assertEqual(caught.exception.code, 403)
        with patch("Aegis.Storage.output_archives.time.time", return_value=job["expires"] + 1):
            self.server.archives.cleanup()
        self.assertFalse((self.root / "archives" / (job["job_id"] + ".zip")).exists())

    def test_audio_archive_contains_only_audio_and_has_its_own_filename(self):
        self.server.archives.outputs = OutputResources(self.root, {".wav"})
        self.server.outputs = self.server.archives.outputs
        job = self.ready_archive()
        with urlopen(job["url"]) as source:
            self.assertIn("EverSpark-Audio.zip", source.headers["Content-Disposition"])
            with zipfile.ZipFile(io.BytesIO(source.read())) as archive:
                self.assertEqual(archive.namelist(), ["EverSpark-Outputs/speech.wav"])

    def test_unchanged_outputs_reuse_a_zip_but_new_outputs_prepare_a_new_one(self):
        job = self.ready_archive()
        self.assertEqual(self.archive_request()["job_id"], job["job_id"])
        (self.root / "new.png").write_bytes(b"new-output")
        newer = self.ready_archive()
        self.assertNotEqual(newer["job_id"], job["job_id"])
        with urlopen(newer["url"]) as source:
            with zipfile.ZipFile(io.BytesIO(source.read())) as archive:
                self.assertEqual(archive.read("EverSpark-Outputs/new.png"), b"new-output")

    def test_empty_and_oversized_archives_fail_without_retaining_partial_files(self):
        for max_bytes in (0, 1):
            with self.subTest(max_bytes=max_bytes):
                if max_bytes == 0:
                    self.server.archives.outputs = OutputResources(self.root / "empty", {".png"})
                else:
                    self.server.archives.outputs = self.server.outputs
                with patch("Aegis.Storage.output_archives.MAX_BYTES", max_bytes):
                    job = self.archive_request()
                    deadline = time.monotonic() + 3
                    while job["status"] == "preparing" and time.monotonic() < deadline:
                        time.sleep(.01)
                        job = self.archive_request(job["job_id"])
                    self.assertEqual(job["status"], "failed", job)
                self.assertFalse(list((self.root / "archives").glob("*.part")))
