import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from Legate.Envoy import bandwidth as module
from Archon.Steward.NodeManager.bandwidth import validate


class DownloadTestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def source(self):
        return module.download_source()

    def test_source_reuses_manifest_without_installing_models(self):
        from dataclasses import replace
        spec = next(spec for spec in module.load_specs() if spec.id == 'image-default')
        with patch.object(module, 'load_specs', return_value=[replace(spec, repo_id='Example/Model', revision='revision name', filename='nested/model.safetensors')]):
            source = module.download_source()
        self.assertEqual(source['server_url'], 'https://huggingface.co/Example/Model/resolve/revision%20name/nested/model.safetensors')
        self.assertEqual(source['model_filename'], 'nested/model.safetensors')
        with patch.object(module, 'load_specs', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'unavailable'): module.download_source()

    def test_deadline_timeout_with_payload_is_success_using_wall_clock(self):
        clock = [0.0]
        def transfer(args, **kwargs):
            clock[0] = 30.02
            return Mock(returncode=28, stdout='200 30.02 88536085')
        with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(module.subprocess, 'run', side_effect=transfer) as curl:
            result = module.measure()
        self.assertAlmostEqual(result['download_mb_s'], 88536085 / 30.02 / 1_000_000)
        self.assertFalse(result['qualified'])
        self.assertEqual(result['method'], 'default_model_http')
        self.assertTrue(validate(result)['download_mb_s'] > 0)
        args = curl.call_args.args[0]
        self.assertEqual(args[0], 'curl')
        self.assertEqual(args[args.index('-o')+1], os.devnull)
        self.assertEqual(args[args.index('--noproxy')+1], '*')
        self.assertEqual(args[-1], self.source()['server_url'])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_auto_once_and_manual_retry_without_waiting(self):
        process = Mock(pid=os.getpid())
        with patch.dict(os.environ, {"EVERSPARK_NODE_BANDWIDTH": "1", "EVERSPARK_NODE_JOIN_TOKEN": "secret"}), patch.object(module.subprocess, 'Popen', return_value=process) as spawn:
            self.assertEqual(module.start(self.directory)['status'], 'pending')
            module.start(self.directory)
            module.start(self.directory, force=True)
            self.assertEqual(spawn.call_count, 1)
            self.assertNotIn('EVERSPARK_NODE_JOIN_TOKEN', spawn.call_args.kwargs['env'])
            value = module._read(self.directory)
            value['status'] = 'completed'
            value['policy'] = module.POLICY
            value['download_mb_s'] = 70
            module.save(self.directory/'bandwidth.json', value)
            module.start(self.directory)
            self.assertEqual(spawn.call_count, 1)
            module.start(self.directory, force=True)
            self.assertEqual(spawn.call_count, 2)

    def test_completed_file_repeats_until_window_ends(self):
        clock = [0.0]
        def transfer(args, **kwargs):
            clock[0] += 10
            return Mock(returncode=0, stdout='206 10 500000000')
        with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(module.subprocess, 'run', side_effect=transfer) as curl:
            result = module.measure()
        self.assertEqual(curl.call_count, 3)
        self.assertEqual([float(call.args[0][call.args[0].index('--max-time')+1]) for call in curl.call_args_list], [30,20,10])
        self.assertEqual(result['elapsed_seconds'], 30)
        self.assertEqual(result['bytes_received'], 1_500_000_000)
        self.assertEqual(result['download_mb_s'], 50)
        self.assertTrue(result['qualified'])

    def test_actual_curl_discards_payload_and_accepts_sample_timeout(self):
        import shutil
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        if not shutil.which('curl'): self.skipTest('curl unavailable')
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                try:
                    self.send_response(200)
                    self.send_header('Content-Length', '10000000')
                    self.end_headers()
                    for _ in range(100):
                        self.wfile.write(b'x' * 8192)
                        self.wfile.flush()
                        time.sleep(.01)
                except (BrokenPipeError, ConnectionResetError): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            result = module.measure(duration=.3, source={**self.source(), 'server_url':f'http://127.0.0.1:{server.server_port}/model'})
            self.assertGreater(result['bytes_received'], 0)
            self.assertGreaterEqual(result['elapsed_seconds'], .27)
            self.assertEqual(result['method'], 'default_model_http')
            self.assertEqual(list(self.directory.iterdir()), [])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_worker_stores_source_and_measurement_without_credentials(self):
        module.save(self.directory/'bandwidth.json', {'status':'pending','run_id':'fixture','policy':2})
        result = {'status':'completed', 'method':'default_model_http', 'download_mb_s':50,
                  'elapsed_seconds':30, 'bytes_received':1_500_000_000,
                  'server_name':'Hugging Face', 'server_url':self.source()['server_url']}
        with patch.object(module, 'measure', return_value=result), patch.object(module.time, 'sleep'):
            module.run(self.directory, 'fixture')
        saved = module.snapshot(self.directory)
        self.assertEqual(saved['policy'],module.POLICY)
        self.assertEqual(saved['download_mb_s'],50)
        self.assertEqual(saved['method'],'default_model_http')
        self.assertNotIn('pid',saved)
        self.assertTrue(validate(saved)['qualified'])

    def test_failure_logs_cause_and_never_becomes_zero_speed(self):
        module.save(self.directory/'bandwidth.json', {'status':'pending','run_id':'fixture'})
        with patch.object(module, 'measure', side_effect=OSError('HTTP 503 fixture')), patch.object(module.time, 'sleep'), patch('sys.stderr',new_callable=io.StringIO) as log:
            module.run(self.directory,'fixture')
        result=module.snapshot(self.directory)
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('download_mb_s',result)
        self.assertIn('HTTP 503 fixture',result['error'])
        self.assertIn('HTTP 503 fixture',log.getvalue())

    def test_invalid_http_exit_and_statistics_never_produce_speed(self):
        for code, stats, elapsed in [(22,'403 1 0',1), (0,'200 1 0',1),
                                      (7,'200 1 1000',1), (28,'200 1 1000',1),
                                      (0,'200 nan 1000',1), (0,'malformed',1)]:
            clock = [0.0]
            def transfer(*args, **kwargs):
                clock[0] = elapsed
                return Mock(returncode=code, stdout=stats)
            with patch.object(module.time,'monotonic',side_effect=lambda:clock[0]), patch.object(module.subprocess,'run',side_effect=transfer):
                with self.assertRaises(ValueError): module.measure()
        for exc in [FileNotFoundError('curl missing'), module.subprocess.TimeoutExpired('curl', 35)]:
            with patch.object(module.subprocess,'run',side_effect=exc):
                with self.assertRaises(type(exc)): module.measure()

    def test_controller_validates_model_sample_and_keeps_old_methods(self):
        value={'status':'completed','method':'default_model_http','server_url':self.source()['server_url'],
               'elapsed_seconds':30,'bytes_received':1_500_000_000,'download_mb_s':50}
        self.assertTrue(validate(value)['qualified'])
        self.assertFalse(validate({**value,'download_mb_s':49,'bytes_received':1_470_000_000})['qualified'])
        for field, invalid in [('elapsed_seconds',.5),('elapsed_seconds',True),('bytes_received',0),
                               ('download_mb_s',float('nan')),('download_mb_s',51),('server_url','https://untrusted.test/model')]:
            self.assertIsNone(validate({**value,field:invalid}))
        self.assertIsNone(validate({'status':'completed','download_mb_s':True}))
        self.assertTrue(validate({'status':'completed','download_mb_s':50,'region':'AS','server_region':'AS'})['qualified'])
        old={**value,'method':'cloudflare_http','server_url':'https://speed.cloudflare.com/__down'}
        self.assertTrue(validate(old)['qualified'])


class RegionalDiscoveryTests(unittest.TestCase):
    def setUp(self):
        from Legate.Envoy import bandwidth_regions
        self.module = bandwidth_regions
        self.servers = [
            {'name': 'Tokyo, Japan (A573)', 'server': 'https://tokyo.test/', 'id': 82},
            {'name': 'Los Angeles, USA', 'server': 'https://usa.test/', 'id': 90},
            {'name': 'Frankfurt, Germany', 'server': 'https://eu.test/', 'id': 50},
            {'name': 'Unknown location', 'server': 'https://unknown.test/', 'id': 999},
        ]

    def fetcher(self, region='AS'):
        return lambda url: ({'success': True, 'continent_code': region, 'country': 'Fixture'}
                            if 'ipwho.is' in url else self.servers)

    def test_asian_pod_never_gets_us_or_eu_servers(self):
        region, servers = self.module.discovery(self.fetcher())
        self.assertEqual(region['region'], 'AS')
        self.assertEqual([server['id'] for server in servers], [82])
        for code, expected in [('EU', 50), ('NA', 90)]:
            _, servers = self.module.discovery(self.fetcher(code))
            self.assertEqual([server['id'] for server in servers], [expected])

    def test_unknown_region_or_absent_regional_server_does_not_fallback(self):
        for region in ['unknown', 'AF']:
            with self.assertRaises(self.module.RegionError):
                self.module.discovery(self.fetcher(region))
        self.assertIsNone(self.module.server_region({'name': 'Mystery server'}))

    def test_old_and_cross_region_measurements_cannot_recommend_replacement(self):
        for metadata in [{}, {'region': 'AS', 'server_region': 'NA'}]:
            result = validate({'status': 'completed', 'download_mb_s': 1, **metadata})
            self.assertIsNone(result['qualified'])
            self.assertFalse(result['regional'])

    def test_old_policy_is_retested_once_on_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            module.save(Path(directory)/'bandwidth.json', {'status': 'completed', 'download_mb_s': 1})
            with patch.dict(os.environ, {'EVERSPARK_NODE_BANDWIDTH': '1'}), patch.object(module.subprocess, 'Popen', return_value=Mock(pid=os.getpid())) as spawn:
                module.start(Path(directory))
                module.start(Path(directory))
                self.assertEqual(spawn.call_count, 1)
