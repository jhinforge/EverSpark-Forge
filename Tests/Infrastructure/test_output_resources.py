"""Output cache transfer correctness after moving file management into Storage."""
import base64
import tempfile
import unittest
from pathlib import Path
from Aegis.Storage.output_resources import OutputResources


class OutputResourcesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.outputs = OutputResources(self.root, {".png"}, max_bytes=20)

    def test_chunked_transfer_is_atomic_reused_and_readable(self):
        calls = []
        def read(offset):
            calls.append(offset)
            return {"size": 6, "data": base64.b64encode(b"abcdef"[offset:offset+3]).decode()}
        path = self.outputs.receive("render.png", "nested", read)
        self.assertEqual(path.read_bytes(), b"abcdef")
        self.assertEqual(calls, [0, 3])
        self.assertEqual(self.outputs.receive("render.png", "nested", lambda _: self.fail("cache not reused")), path)
        self.assertEqual(base64.b64decode(self.outputs.chunk("render.png", "nested", 3)["data"]), b"def")
        self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_bad_transfer_is_not_published_and_temporary_file_is_removed(self):
        for chunks in ([{"size": 21, "data": "YQ=="}],
                       [{"size": 6, "data": "YWJj"}, {"size": 5, "data": "ZGU="}],
                       [{"size": 6, "data": "not base64"}]):
            iterator = iter(chunks)
            with self.assertRaises(ValueError):
                self.outputs.receive("render.png", "", lambda _: next(iterator))
            self.assertFalse((self.root / "render.png").exists())
            self.assertEqual(list(self.root.glob("*.part")), [])

    def test_path_traversal_and_symlink_escape_are_rejected_before_fetch(self):
        for filename, subfolder in (("../private.png", ""), ("render.png", ".."), ("file.txt", "")):
            with self.assertRaises(ValueError):
                self.outputs.receive(filename, subfolder, lambda _: self.fail("unsafe fetch"))
        with tempfile.TemporaryDirectory() as other:
            (self.root / "escape").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.outputs.receive("render.png", "escape", lambda _: self.fail("unsafe fetch"))
