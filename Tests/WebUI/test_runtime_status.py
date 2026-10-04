import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Archon.Portal.app import RequestHandler, Settings, ManifestError


class RuntimeStatusTests(unittest.TestCase):
    def handler(self, selected=None):
        handler = object.__new__(RequestHandler)
        bindings = None if selected is None else SimpleNamespace(
            bindings=selected, url='http://127.0.0.1:9000', lock=threading.RLock())
        handler.server = SimpleNamespace(settings=Settings(request_timeout=600), forge_bindings=bindings,
                                         orchestrator_url=bindings.url if bindings else Settings().orchestrator_url)
        handler._json = Mock()
        return handler

    @staticmethod
    def upstream(url, timeout, payload=None):
        if payload:
            if payload['forge'] == 'concept':
                return 200, {'output': json.dumps(['everspark-concept'])}
            return 200, {'output': json.dumps({'ok': True})}
        return 200, {'ok': True}

    def test_bound_forges_use_actual_service_checks_with_bounded_timeouts(self):
        handler = self.handler({'concept': 'a' * 32, 'image': 'b' * 32, 'audio': 'c' * 32})
        with patch('Archon.Portal.app.request_json', side_effect=self.upstream) as call:
            services = handler._collect_service_health()
        for key in ['archon_backend', 'concept_forge', 'image_forge', 'audio_forge']:
            self.assertTrue(services[key]['online'])
        payloads = [args.args[2] for args in call.call_args_list if len(args.args) == 3]
        self.assertEqual({(p['forge'], p['action']) for p in payloads}, {('concept', 'models'), ('audio', 'health')})
        self.assertTrue(all(args.args[1] <= 11 for args in call.call_args_list))
        self.assertEqual(services['concept_forge']['source'], 'node_models')
        self.assertEqual(services['audio_forge']['source'], 'node_audio_health')
        self.assertTrue(any(args.args[0].endswith('/image/health') for args in call.call_args_list))

    def test_http_success_does_not_override_failed_health_or_invalid_output(self):
        handler = self.handler({'concept': 'a' * 32, 'audio': 'c' * 32})
        def upstream(url, timeout, payload=None):
            if payload:
                return 200, {'output': json.dumps({'ok': True} if payload['forge'] == 'concept' else {'ok': False})}
            return 200, {'ok': False}
        with patch('Archon.Portal.app.request_json', side_effect=upstream):
            services = handler._collect_service_health()
        self.assertTrue(all(not service['online'] for service in services.values()))

    def test_unbound_forges_are_unverified_without_running_model_inference(self):
        handler = self.handler({})
        with patch('Archon.Portal.app.request_json', side_effect=self.upstream) as call:
            services = handler._collect_service_health()
        for key in ['concept_forge', 'audio_forge']:
            self.assertEqual(services[key]['status'], 'unavailable')
        self.assertTrue(all(len(args.args) == 2 for args in call.call_args_list))

    def test_probe_timeout_is_unavailable_not_online(self):
        handler = self.handler({'concept': 'a' * 32, 'audio': 'c' * 32})
        with patch('Archon.Portal.app.request_json', side_effect=TimeoutError):
            services = handler._collect_service_health()
        self.assertTrue(all(s['status'] == 'unavailable' and not s['online'] for s in services.values()))

    def test_missing_log_manifest_and_optional_audio_do_not_block_image_readiness(self):
        handler = self.handler({'concept': 'a' * 32, 'image': 'b' * 32})
        with patch('Archon.Portal.app.request_json', side_effect=self.upstream), patch(
                'Archon.Portal.app.collect_log_status', side_effect=ManifestError('missing')):
            handler._runtime_status()
        status, body = handler._json.call_args.args
        self.assertEqual(status, 200)
        self.assertTrue(body['ready'])
        self.assertFalse(body['logging']['ready'])
        self.assertFalse(body['services']['audio_forge']['online'])

    def test_audio_with_concept_can_be_ready_without_image(self):
        handler = self.handler({'concept': 'a' * 32, 'audio': 'c' * 32})
        def upstream(url, timeout, payload=None):
            if url.endswith('/image/health'):
                return 503, {'ok': False}
            return self.upstream(url, timeout, payload)
        with patch('Archon.Portal.app.request_json', side_effect=upstream), patch(
                'Archon.Portal.app.collect_log_status', return_value={'configured': 0, 'present': 0, 'needs_rotation': 0}):
            handler._runtime_status()
        self.assertTrue(handler._json.call_args.args[1]['ready'])


if __name__ == '__main__':
    unittest.main()
