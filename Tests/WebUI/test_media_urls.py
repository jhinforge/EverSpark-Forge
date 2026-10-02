import shutil
import subprocess
import unittest
from pathlib import Path


class MediaURLUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_direct_media_and_fallback(self):
        subprocess.run(["node", "Tests/WebUI/test_media_urls.js"],
                       cwd=Path(__file__).resolve().parents[2], check=True)
