"""Exercise actual WebUI result functions with a minimal DOM."""
import shutil
import subprocess
import unittest
from pathlib import Path


class AudioResultUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend tests")
    def test_audio_playback_history_and_partial_failure(self):
        root = Path(__file__).resolve().parents[2]
        subprocess.run(["node", "Tests/WebUI/test_audio_results.js"], cwd=root, check=True)
