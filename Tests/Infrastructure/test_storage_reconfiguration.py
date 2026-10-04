import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from Archon.Vault.runtime_config import load_config
from Aegis.Storage.service import StorageService


class StorageReconfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = load_config()
        self.config['memory']['database'] = str(self.root / 'memory.sqlite')
        self.config['remote_nodes'] = {'remote_only': True, 'image_node_id': 'a' * 32,
                                      'concept_node_id': 'b' * 32, 'control_url': 'http://127.0.0.1:8765'}
        self.config['storage']['backend'] = 'local'
        self.service = StorageService(self.config)
        self.conf = self.root / 'rclone.conf'
        self.conf.write_text('[cloud]\ntype=s3\nsecret_access_key=private\n')
        self.values = {'EVERSPARK_STORAGE_BACKEND': 'rclone', 'RCLONE_CONFIG': str(self.conf),
                       'RCLONE_BIN': sys.executable, 'IMAGE_FORGE_RCLONE_REMOTE': 'cloud:images',
                       'CONCEPT_FORGE_RCLONE_REMOTE': 'cloud:concept'}

    def test_existing_runtime_uses_new_cloud_payload_without_losing_jobs_or_nodes(self):
        downloads, remote = self.service.downloads, self.service.remote
        remote.latest['download'] = 'a' * 32 + ':image:' + 'c' * 32
        self.service.backups._jobs['completed'] = {'status': 'completed'}
        self.service.reconfigure(self.values)
        self.assertIs(self.service.downloads, downloads)
        self.assertIs(self.service.remote, remote)
        self.assertEqual(remote.latest['download'], 'a' * 32 + ':image:' + 'c' * 32)
        self.assertEqual(self.service.backups._jobs['completed']['status'], 'completed')
        payload = remote.cloud_config()
        self.assertEqual(payload['storage']['rclone']['image_remote'], 'cloud:images')
        self.assertIn('private', payload['rclone_config'])
        self.assertNotIn('binary', payload['storage']['rclone'])
        self.assertNotIn('config_file', payload['storage']['rclone'])
        self.assertEqual(remote.destination('lora'), ('a' * 32, 'image'))
        self.assertEqual(remote.destination('concept_model'), ('b' * 32, 'concept'))
        self.assertTrue(self.service.backups.settings.enabled)

    def test_scan_and_backup_in_progress_prevent_configuration_switch(self):
        old = self.service.storage
        old._scan_state['status'] = 'running'
        with self.assertRaisesRegex(ValueError, 'current storage operation'):
            self.service.reconfigure(self.values)
        old._scan_state['status'] = 'idle'
        self.service.backups._jobs['active'] = {'status': 'running'}
        with self.assertRaisesRegex(ValueError, 'current storage operation'):
            with self.service.configuration_guard():
                self.fail('guard must reject')
        self.assertIs(self.service.storage, old)
        self.assertFalse(old.settings.enabled)
