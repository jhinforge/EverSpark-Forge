"""Gallery metadata does not eagerly download a page of remote image files."""
import base64
import tempfile
import unittest
from unittest.mock import Mock
from image_forge.remote import RemoteImageGateway


class RemoteImageHistoryTests(unittest.TestCase):
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
