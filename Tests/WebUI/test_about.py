import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from Archon.Portal.about import build_info


class AboutTests(unittest.TestCase):
    def test_packaged_release_preserves_variant_commit_and_build_time_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = {'version': '0.1.0', 'revision': 'a'*40, 'built_at': '2026-10-06T09:00:00+00:00', 'variant': 'full', 'python': '3.11.9'}
            (root/'release.json').write_text(json.dumps(release))
            with patch('Archon.Portal.about.subprocess.check_output') as git:
                info = build_info(root)
            self.assertEqual(info, {key: release[key] for key in ('version', 'revision', 'built_at', 'variant')})
            git.assert_not_called()

    def test_source_checkout_without_git_or_release_has_honest_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/'Archon/Client/Windows/tauri.conf.json'
            config.parent.mkdir(parents=True)
            config.write_text('{"version":"0.1.0"}')
            (root/'release.json').write_text('invalid JSON')
            info = build_info(root)
            self.assertEqual(info, {'version': '0.1.0', 'variant': 'Source checkout'})
