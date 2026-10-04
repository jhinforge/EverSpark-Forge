"""Cloud onboarding never needs a tunnel credential or a handwritten env file."""
from contextlib import contextmanager
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from Archon.Vault.storage_config import StorageConfiguration, parse_rclone, MANAGED
from Archon.Vault.import_config import parse_env

CONFIG = '# keep this comment\n[r2-assets]\ntype = s3\nprovider = Cloudflare\nsecret_access_key = private-test-secret\n\n[drive]\ntype = drive\ntoken = private-token\n'


class StorageConfigurationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.run = Mock(return_value=subprocess.CompletedProcess([], 0, '[{"Name":"models","IsDir":true}]', ''))
        self.apply = Mock()
        self.service = StorageConfiguration(self.root, self.apply, self.run)

    def selection(self, images=None):
        return {'revision': self.service.status()['revision'], 'binary': sys.executable,
                'image_sources': images or ['r2-assets:bucket/cold', 'r2-assets:bucket/models'],
                'concept_source': 'r2-assets:bucket/ollama/models'}

    def test_import_without_env_or_cloudflare_is_private_and_inactive(self):
        status = self.service.import_file(CONFIG)
        self.assertTrue(status['imported'])
        self.assertFalse(status['enabled'])
        self.assertFalse((self.root / '.env').exists())
        self.assertNotIn('private-test-secret', json.dumps(status))
        self.assertEqual(self.service.draft.stat().st_mode & 0o777, 0o600)

    def test_selection_generates_union_env_and_applies_without_restart(self):
        (self.root / '.env').write_text('CF_HOSTNAME=example.test\nUNRELATED=value\n')
        self.service.import_file(CONFIG)
        status = self.service.save(self.selection())
        self.assertTrue(status['enabled'])
        values = parse_env(self.root / '.env')
        self.assertEqual(values['UNRELATED'], 'value')
        self.assertEqual(values['CF_HOSTNAME'], 'example.test')
        self.assertEqual(values['EVERSPARK_STORAGE_BACKEND'], 'rclone')
        self.assertEqual(values['IMAGE_FORGE_RCLONE_REMOTE'], MANAGED + ':')
        text = Path(values['RCLONE_CONFIG']).read_text()
        self.assertTrue(text.startswith(CONFIG))
        parser = parse_rclone(text)
        self.assertEqual(shlex.split(parser.get(MANAGED, 'upstreams')), ['r2-assets:bucket/cold:ro', 'r2-assets:bucket/models:ro'])
        self.assertEqual(parser.get(MANAGED, 'search_policy'), 'epall')
        self.apply.assert_called_once()
        self.assertFalse(self.service.draft.exists())
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)

    def test_single_directory_uses_original_remote_and_spaces_roundtrip(self):
        self.service.import_file(CONFIG)
        self.service.save(self.selection(['r2-assets:bucket/My Models']))
        values = parse_env(self.root / '.env')
        self.assertEqual(values['IMAGE_FORGE_RCLONE_REMOTE'], 'r2-assets:bucket/My Models')
        self.assertNotIn(MANAGED, parse_rclone(Path(values['RCLONE_CONFIG']).read_text()))

    def test_user_remote_with_reserved_name_is_preserved(self):
        original = CONFIG + f'\n[{MANAGED}]\ntype = union\nupstreams = drive:legacy\n'
        self.service.import_file(original)
        status = self.service.save(self.selection())
        text = Path(os.environ['RCLONE_CONFIG']).read_text()
        self.assertTrue(text.startswith(original))
        self.assertEqual(status['selection']['managed_remote'], MANAGED + '-1')

    def test_repeated_save_replaces_only_generated_union(self):
        self.service.import_file(CONFIG)
        self.service.save(self.selection())
        self.service.save(self.selection(['r2-assets:bucket/new', 'drive:more']))
        text = Path(os.environ['RCLONE_CONFIG']).read_text()
        self.assertEqual(text.count('[' + MANAGED + ']'), 1)
        self.assertIn('private-token', text)
        self.assertIn('drive:more:ro', text)

    def test_bad_import_does_not_replace_active_or_draft(self):
        self.service.import_file(CONFIG)
        self.service.save(self.selection())
        before = Path(os.environ['RCLONE_CONFIG']).read_bytes()
        with self.assertRaises(ValueError):
            self.service.import_file('[broken]\ntoken = secret\n')
        self.assertEqual(Path(os.environ['RCLONE_CONFIG']).read_bytes(), before)
        self.assertTrue(self.service.status()['enabled'])

    def test_failed_connection_does_not_activate_or_leak_stderr(self):
        self.service.import_file(CONFIG)
        self.run.return_value = subprocess.CompletedProcess([], 1, '', 'private-test-secret')
        with self.assertRaisesRegex(ValueError, 'Could not access') as error:
            self.service.save(self.selection())
        self.assertNotIn('private-test-secret', str(error.exception))
        self.assertFalse((self.root / '.env').exists())
        self.apply.assert_not_called()

    def test_apply_failure_rolls_back_files_and_environment(self):
        (self.root / '.env').write_text('UNRELATED=value\n')
        self.service.import_file(CONFIG)
        self.apply.side_effect = ValueError('busy')
        with self.assertRaisesRegex(ValueError, 'busy'):
            self.service.save(self.selection())
        self.assertEqual((self.root / '.env').read_text(), 'UNRELATED=value\n')
        self.assertNotIn('EVERSPARK_STORAGE_BACKEND', os.environ)
        self.assertFalse(self.service.selection.exists())
        self.assertFalse((self.service.directory / 'rclone.conf').exists())
        self.assertTrue(self.service.draft.exists())

    def test_stale_revision_and_unsafe_paths_are_rejected(self):
        self.service.import_file(CONFIG)
        body = self.selection()
        self.service.import_file(CONFIG + '\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.save(body)
        for path in ['unknown:bucket', 'r2-assets:../secrets', 'r2-assets:/absolute', 'r2-assets:bad\npath']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.service.browse({'revision': self.service.status()['revision'], 'path': path, 'binary': sys.executable})

    def test_browse_only_lists_directories_and_uses_private_config(self):
        self.service.import_file(CONFIG)
        body = {'revision': self.service.status()['revision'], 'path': 'r2-assets:bucket', 'binary': sys.executable}
        self.assertEqual(self.service.browse(body)['directories'], ['models'])
        command = self.run.call_args.args[0]
        self.assertIn('--dirs-only', command)
        self.assertIn(str(self.service.draft), command)
        self.assertEqual(self.run.call_args.kwargs['timeout'], 15)

    def test_busy_guard_rejects_before_any_active_file_is_written(self):
        self.service.import_file(CONFIG)
        self.service.save(self.selection())
        self.apply.reset_mock()
        active = Path(os.environ['RCLONE_CONFIG'])
        old_config, old_env = active.read_bytes(), (self.root / '.env').read_bytes()
        @contextmanager
        def busy():
            raise ValueError('busy')
            yield
        self.service.guard = busy
        self.service.import_file(CONFIG + '# new credentials draft\n')
        with self.assertRaisesRegex(ValueError, 'busy'):
            self.service.save(self.selection(['drive:new']))
        self.assertEqual(active.read_bytes(), old_config)
        self.assertEqual((self.root / '.env').read_bytes(), old_env)
        self.apply.assert_not_called()

    def test_changed_roots_clear_old_source_mappings_and_keep_upload_preferences(self):
        self.service.import_file(CONFIG)
        self.service.save(self.selection())
        mapping = self.service.directory / 'model_paths.json'
        mapping.write_text(json.dumps({'image_manual': {'lora': ['r2-assets:old']},
                                       'concept_manual': ['drive:old'],
                                       'image_upload': {'lora': 'drive:uploads'}, 'backup_remote': 'drive:backups'}))
        body = self.selection(['drive:new-images'])
        body['concept_source'] = 'drive:new-concept'
        self.service.save(body)
        updated = json.loads(mapping.read_text())
        self.assertEqual(updated['image_manual'], {})
        self.assertEqual(updated['concept_manual'], [])
        self.assertEqual(updated['backup_remote'], 'drive:backups')
        self.assertEqual(updated['image_upload'], {'lora': 'drive:uploads'})

    def test_old_cli_configuration_remains_enabled(self):
        self.service.directory.mkdir(parents=True)
        active = self.service.directory / 'rclone.conf'
        active.write_text(CONFIG)
        (self.root / '.env').write_text(f'RCLONE_CONFIG={active}\nEVERSPARK_STORAGE_BACKEND=rclone\nIMAGE_FORGE_RCLONE_REMOTE=r2-assets:images\nCONCEPT_FORGE_RCLONE_REMOTE=drive:llms\n')
        status = self.service.status()
        self.assertTrue(status['enabled'])
        self.assertEqual(status['selection']['image_sources'], ['r2-assets:images'])
