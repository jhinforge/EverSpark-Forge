"""Gallery metadata does not eagerly download a page of remote image files."""
import base64
import tempfile
import unittest
import io
import json
from urllib.error import HTTPError
from unittest.mock import Mock, patch
from image_forge.remote import RemoteImageGateway


class RemoteImageHistoryTests(unittest.TestCase):
    def test_archive_failure_preserves_node_diagnostic_and_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = RemoteImageGateway('a' * 32, 'http://127.0.0.1:8765', directory, 'comfyui')
            failure = HTTPError(gateway.url, 503, 'Service Unavailable', {}, io.BytesIO(json.dumps({
                'error': 'Node Agent execution failed', 'detail': 'Image URL service unavailable',
                'exit_code': 1}).encode()))
            with patch('image_forge.remote.urlopen', side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, r'archive failed .*HTTP 503, exit code 1.*Image URL service unavailable'):
                    gateway.archive_job()

    def test_non_json_node_error_still_reports_http_status_and_action(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = RemoteImageGateway('a' * 32, 'http://127.0.0.1:8765', directory, 'comfyui')
            failure = HTTPError(gateway.url, 503, 'Service Unavailable', {}, io.BytesIO(b'not json'))
            with patch('image_forge.remote.urlopen', side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, r'archive failed .*HTTP 503.*Service Unavailable'):
                    gateway.archive_job()

    def test_archive_returns_a_validated_node_url_without_opening_a_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = RemoteImageGateway('a' * 32, 'http://127.0.0.1:8765', directory, 'comfyui')
            value = {"status": "ready", "url": "http://100.64.0.1:9000/archive?signature=fixture"}
            gateway._call = Mock(return_value=value)
            self.assertEqual(gateway.archive_job('b' * 32), value)
            gateway._call.assert_called_once_with('archive', {"job_id": 'b' * 32})
            gateway._call.return_value = {"status": "ready", "url": "https://example.com/archive"}
            with self.assertRaises(ValueError):
                gateway.archive_job()
            self.assertEqual(gateway.outputs.files(), [])

    def test_history_returns_uncached_descriptors_then_file_request_transfers_and_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = RemoteImageGateway('a' * 32, 'http://127.0.0.1:8765', directory, 'comfyui')
            images = [{"filename": f"render-{i}.png", "subfolder": "", "type": "output"} for i in range(36)]
            content = b'PNG' + b'x' * 30000
            def call(action, payload):
                if action == 'history':
                    return {"images": images}
                offset = payload['offset']
                return {"size": len(content), "data": base64.b64encode(content[offset:offset+24576]).decode()}
            gateway._call = Mock(side_effect=call)
            self.assertEqual(gateway.history(36), images)
            gateway._call.assert_called_once_with('history', {"limit": 36})
            self.assertEqual(gateway.outputs.files(), [])
            self.assertEqual(gateway.image_path('render-0.png').read_bytes(), content)
            self.assertEqual(gateway._call.call_count, 3)
            gateway.image_path('render-0.png')
            self.assertEqual(gateway._call.call_count, 3)

    def test_history_rejects_unsafe_resource_paths_without_transferring(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = RemoteImageGateway('a' * 32, 'http://127.0.0.1:8765', directory, 'comfyui')
            gateway._call = Mock(return_value={"images": [{"filename": "../secret.png"}]})
            with self.assertRaises(ValueError):
                gateway.history()
            gateway._call.assert_called_once()
