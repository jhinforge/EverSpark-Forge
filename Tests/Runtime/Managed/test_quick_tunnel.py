from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "Runtime/Managed"))

import access_info  # noqa: E402
import quick_tunnel  # noqa: E402


class QuickTunnelTests(unittest.TestCase):
    def test_share_reuses_link_and_stops_only_its_owned_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "cloudflared"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'Your quick Tunnel has been created! https://demo-abc.trycloudflare.com'\n"
                "while true; do sleep 1; done\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            with (
                patch.object(quick_tunnel, "STATE_DIR", root / "state"),
                patch.object(quick_tunnel, "_log_path", return_value=root / "quick.log"),
                patch.object(quick_tunnel, "_local_ready", return_value=True),
                patch.object(quick_tunnel.shutil, "which", return_value=str(fake)),
                patch.object(quick_tunnel.Path, "home", return_value=root),
                patch.object(quick_tunnel, "discovery_environment", return_value={}),
            ):
                try:
                    started = quick_tunnel.start()
                    self.assertEqual(started["url"], "https://demo-abc.trycloudflare.com")
                    self.assertEqual(quick_tunnel.start(), started)
                    info = access_info.build_access_info({})
                    self.assertTrue(info["ready"])
                    self.assertEqual(info["quick_url"], started["url"])
                    self.assertIn(started["url"], access_info.render_access_info(info))
                    self.assertNotIn("missing SSH", access_info.render_access_info(info))
                    self.assertTrue(quick_tunnel.stop())
                    self.assertIsNone(quick_tunnel.status())
                finally:
                    quick_tunnel.stop()

    def test_no_webui_never_opens_public_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(quick_tunnel, "STATE_DIR", Path(directory) / "state"),
                patch.object(quick_tunnel, "_local_ready", return_value=False),
                patch.object(quick_tunnel, "discovery_environment", return_value={}),
            ):
                with self.assertRaisesRegex(quick_tunnel.QuickTunnelError, "start first"):
                    quick_tunnel.start()
                self.assertIsNone(quick_tunnel.status())


if __name__ == "__main__":
    unittest.main()
