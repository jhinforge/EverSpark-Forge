import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from Archon.Portal import lora_update
from Archon.Portal.lora_plugin import LoRAPlugin


def package(version, extra=None):
    files = {
        "VERSION": version,
        "panel.js": version,
        "panel.css": "",
        "thumbnail_names.py": "",
        "catalog.py": "from .message import VERSION",
        "message.py": f"VERSION = {version!r}",
        **(extra or {}),
    }
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"checkout/{lora_update.PANEL}/{name}", content)
    return data.getvalue()


class LoRAUpdateTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.plugin = LoRAPlugin(Path(root.name))

    def upgrade(self, version, data):
        with patch.object(lora_update, "fetch", side_effect=[version.encode(), data]) as fetch:
            status = self.plugin.install()
        self.assertEqual(fetch.call_count, 2)
        return status

    def test_install_and_update_without_client_change(self):
        self.assertTrue(self.upgrade("1.0.0", package("1.0.0"))["changed"])
        self.assertEqual(self.plugin._catalog_module().VERSION, "1.0.0")
        self.assertEqual(self.upgrade("1.1.0", package("1.1.0"))["version"], "1.1.0")
        self.assertEqual(self.plugin._catalog_module().VERSION, "1.1.0")
        self.assertEqual(self.plugin.asset("panel.js")[0], b"1.1.0")

    def test_same_version_only_downloads_version_file(self):
        self.upgrade("1.0.0", package("1.0.0"))
        with patch.object(lora_update, "fetch", return_value=b"1.0.0\n") as fetch:
            self.assertFalse(self.plugin.install()["changed"])
        fetch.assert_called_once_with(lora_update.VERSION_URL, lora_update.MAX_VERSION_SIZE)

    def test_incomplete_or_inconsistent_download_preserves_old_install(self):
        self.upgrade("1.0.0", package("1.0.0"))
        for data in (b"invalid archive", package("2.0.1"), package("2.0.0", {"../escape": "no"})):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                self.upgrade("2.0.0", data)
            self.assertEqual(self.plugin.status()["version"], "1.0.0")
            self.assertEqual(self.plugin.asset("panel.js")[0], b"1.0.0")

    def test_existing_install_can_open_before_first_versioned_update(self):
        legacy = self.plugin.plugin_dir / ("a" * 40)
        legacy.mkdir(parents=True)
        for name in lora_update.REQUIRED_FILES:
            if name != "VERSION":
                (legacy / name).write_bytes(b"")
        self.assertEqual(self.plugin.status(), {"installed": True, "version": "legacy"})
        self.assertEqual(self.plugin.asset("panel.js")[0], b"")
        self.assertEqual(self.upgrade("0.1.0", package("0.1.0"))["version"], "0.1.0")
        self.assertTrue(legacy.exists())
