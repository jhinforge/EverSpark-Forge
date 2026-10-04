from dataclasses import replace
from types import SimpleNamespace
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from Archon.Portal.app import Settings, WebUIServer
from Archon.Vault.storage_config import StorageConfiguration


class StorageConfigAPITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = WebUIServer(Settings(port=0))
        self.applied = Mock()
        run = Mock(return_value=subprocess.CompletedProcess([], 0, '[]', ''))
        self.server.storage_configuration = StorageConfiguration(self.root, self.applied, run)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.close)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.worker.join(2)
        self.server.server_close()

    def request(self, path, payload=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        request = Request(self.base + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_import_browse_save_without_handwritten_env_or_uuid(self):
        code, data = self.request('/api/storage/config')
        self.assertEqual(code, 200)
        self.assertFalse(data['enabled'])
        code, data = self.request('/api/storage/config/import', {'content': '[cloud]\ntype=s3\nsecret_access_key=private\n'})
        self.assertEqual(code, 200)
        self.assertNotIn('private', json.dumps(data))
        code, browse = self.request('/api/storage/config/browse', {'revision': data['revision'], 'path': 'cloud:bucket', 'binary': sys.executable})
        self.assertEqual(code, 200)
        self.assertEqual(browse['directories'], [])
        code, active = self.request('/api/storage/config/save', {'revision': data['revision'], 'image_sources': ['cloud:bucket/images'], 'concept_source': 'cloud:bucket/concept', 'binary': sys.executable})
        self.assertEqual(code, 200)
        self.assertTrue(active['enabled'])
        self.assertTrue((self.root / '.env').exists())
        self.applied.assert_called_once()

    def test_selected_runtime_updates_without_rebuilding_bindings(self):
        storage = Mock()
        runtime = SimpleNamespace(server=SimpleNamespace(application=SimpleNamespace(storage=storage)), busy=lambda: False)
        bindings = SimpleNamespace(lock=threading.RLock(), runtime=runtime, active_requests=0)
        self.server.forge_bindings = bindings
        self.server.apply_storage_configuration({'EVERSPARK_STORAGE_BACKEND': 'rclone'})
        storage.reconfigure.assert_called_once_with({'EVERSPARK_STORAGE_BACKEND': 'rclone'})
        self.assertIs(bindings.runtime, runtime)
        bindings.active_requests = 1
        with self.assertRaisesRegex(ValueError, 'current task'):
            with self.server.storage_configuration_guard():
                self.fail('guard must reject active request')

    def test_explicit_legacy_runtime_is_reloaded_when_no_binding_runtime_exists(self):
        self.server.forge_bindings = SimpleNamespace(lock=threading.RLock(), runtime=None, active_requests=0)
        self.server.settings = replace(self.server.settings, orchestrator_url='http://127.0.0.1:8767')
        with patch('Archon.Portal.app.request_json', return_value=(200, {'ok': True})) as request:
            self.server.apply_storage_configuration({'EVERSPARK_STORAGE_BACKEND': 'rclone'})
        self.assertEqual(request.call_args.args[0], 'http://127.0.0.1:8767/storage/reconfigure')

    def test_cross_origin_import_is_denied(self):
        code, _ = self.request('/api/storage/config/import', {'content': '[cloud]\ntype=s3'}, origin='https://evil.example')
        self.assertEqual(code, 403)
        self.assertFalse(self.server.storage_configuration.draft.exists())

    def test_invalid_file_and_path_report_errors_without_activation(self):
        self.assertEqual(self.request('/api/storage/config/import', {'content': 'RCLONE_ENCRYPT_V0:secret'})[0], 400)
        self.assertEqual(self.request('/api/storage/config/save', {'revision': 'stale'})[0], 400)
        self.assertFalse((self.root / '.env').exists())
