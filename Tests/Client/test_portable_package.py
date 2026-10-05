import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("desktop_package", ROOT/"Archon/Client/Windows/package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PortablePackageTests(unittest.TestCase):
    def test_release_inventory_excludes_personal_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = ["Archon/Portal/app.py", "Archon/Vault/Import/env.txt", "Archon/Vault/user.json",
                     "Data/Logs/private.log", "Data/Outputs/private.png", ".env", "Tests/test.py",
                     "Runtime/Python/python.exe", "README.md", "everspark.cmd"]
            for path in paths:
                destination = root/path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("sample")
            with patch.object(package.subprocess, "check_output", return_value="\0".join(paths).encode()):
                selected = [p.relative_to(root).as_posix() for p in package.source_files(root)]
            self.assertEqual(selected, ["Archon/Portal/app.py", "everspark.cmd"])

    def test_both_packages_share_executable_and_only_full_contains_webview(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"source"; root.mkdir()
            source = root/"everspark.cmd"; source.write_text("launcher")
            exe = root/"client.exe"; exe.write_bytes(b"MZ-test-client")
            def python(archive, destination):
                destination.mkdir(parents=True); (destination/"python.exe").write_bytes(b"MZ-python")
            def webview(archive, destination):
                destination.mkdir(parents=True); (destination/"msedgewebview2.exe").write_bytes(b"MZ-webview")
            with patch.object(package, "source_files", return_value=[source]), \
                 patch.object(package.subprocess, "check_output", return_value="abc123\n"), \
                 patch.object(package, "prepare_python", side_effect=python), \
                 patch.object(package, "prepare_webview", side_effect=webview), \
                 patch.object(package.subprocess, "run"):
                archives = package.make_packages(exe, root/"dist", python_archive=root/"python.zip",
                                                  webview_archive=root/"webview.cab", root=root)
            for archive, variant in zip(archives, ["standard", "full"]):
                with zipfile.ZipFile(archive) as result:
                    prefix = "EverSpark-Forge/"
                    self.assertEqual(result.read(prefix+"EverSpark.exe"), exe.read_bytes())
                    self.assertIn(prefix+"Runtime/Python/python.exe", result.namelist())
                    self.assertEqual(prefix+"Runtime/WebView2/msedgewebview2.exe" in result.namelist(), variant == "full")
                    self.assertEqual(json.loads(result.read(prefix+"release.json"))["variant"], variant)
                self.assertTrue(archive.with_suffix(".zip.sha256").is_file())

    def test_python_checksum_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"bad.zip"; path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum"):
                package.prepare_python(path, Path(temporary)/"runtime")


if __name__ == "__main__":
    unittest.main()
