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

    def test_payload_average_uses_decimal_mb_and_shared_elapsed_window(self):
        for size in [49_000_000, 50_000_000, 60_000_000]:
            clock = [0.0]
            class Response:
                status = 200
                headers = {"CF-Ray": "fixture-ICN"}
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read1(self, count):
                    clock[0] += 1
                    return b"x" * size if clock[0] < 30 else b""
            with patch.object(module.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(module, 'build_opener') as opener:
                opener.return_value.open.return_value = Response()
                result = module.measure(workers=1)
            self.assertEqual(result['bytes_received'], 29 * size)
            self.assertEqual(result['download_mb_s'], 29 * size / 30 / 1_000_000)
            # The whole 30-second sample includes startup / last-read overhead.
            self.assertEqual(result['qualified'], result['download_mb_s'] >= 50)
            self.assertEqual(result['server_colo'], 'ICN')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Accept-encoding'), 'identity')
            self.assertTrue(request.full_url.startswith(module.DOWNLOAD_URL))

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

    def test_actual_http_streams_share_one_window_and_discard_payload(self):
        import threading
        import time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        active = [0, 0]
        guard = threading.Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                with guard:
                    active[0] += 1
                    active[1] = max(active)
                try:
                    self.send_response(200)
                    self.send_header('Content-Type','application/octet-stream')
                    self.send_header('CF-Ray','fixture-NRT')
                    self.end_headers()
                    for _ in range(100):
                        self.wfile.write(b'x' * 8192)
                        self.wfile.flush()
                        time.sleep(.005)
                except (BrokenPipeError, ConnectionResetError): pass
                finally:
                    with guard: active[0] -= 1
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with patch.object(module,'DOWNLOAD_URL',f'http://127.0.0.1:{server.server_port}/down'):
                result = module.measure(duration=.2,workers=3)
            self.assertEqual(active[1],3)
            self.assertGreater(result['bytes_received'],0)
            self.assertEqual(result['server_colo'],'NRT')
            self.assertAlmostEqual(result['elapsed_seconds'],.2)
            self.assertAlmostEqual(result['download_mb_s'],result['bytes_received']/.2/1_000_000)
            self.assertEqual(list(self.directory.iterdir()),[])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_worker_stores_source_and_measurement_without_credentials(self):
        module.save(self.directory/'bandwidth.json', {'status':'pending','run_id':'fixture','policy':2})
        result = {'status':'completed', 'method':'cloudflare_http', 'download_mb_s':50,
                  'elapsed_seconds':30, 'bytes_received':1_500_000_000,
                  'server_name':'Cloudflare (ICN)', 'server_url':module.DOWNLOAD_URL, 'server_colo':'ICN'}
        with patch.object(module, 'measure', return_value=result), patch.object(module.time, 'sleep'):
            module.run(self.directory, 'fixture')
        saved = module.snapshot(self.directory)
        self.assertEqual(saved['policy'],3)
        self.assertEqual(saved['download_mb_s'],50)
        self.assertEqual(saved['method'],'cloudflare_http')
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

    def test_network_failure_is_bounded_and_has_no_measurement(self):
        with patch.object(module, 'build_opener') as opener:
            opener.return_value.open.side_effect=OSError('connection unavailable')
            with self.assertRaisesRegex(ValueError,'connection unavailable'):
                module.measure(workers=1)
        self.assertEqual(opener.return_value.open.call_count,3)

    def test_no_payload_or_non_200_cannot_qualify(self):
        for status, headers in [(200,{}),(503,{}),(200,{"Content-Type":"text/html"}),(200,{"Content-Encoding":"gzip"})]:
            response=Mock(status=status,headers=headers)
            response.__enter__=Mock(return_value=response)
            response.__exit__=Mock(return_value=False)
            response.read1.return_value=b''
            with patch.object(module,'build_opener') as opener:
                opener.return_value.open.return_value=response
                with self.assertRaises(ValueError): module.measure(workers=1)

    def test_controller_validates_cloudflare_samples_and_keeps_legacy_guard(self):
        value={'status':'completed','method':'cloudflare_http','server_url':module.DOWNLOAD_URL,
               'elapsed_seconds':30,'bytes_received':1_500_000_000,'download_mb_s':50}
        self.assertTrue(validate(value)['qualified'])
        self.assertFalse(validate({**value,'download_mb_s':49})['qualified'])
        for field, invalid in [('elapsed_seconds',.5),('elapsed_seconds',True),('bytes_received',0),('download_mb_s',float('nan'))]:
            self.assertIsNone(validate({**value,field:invalid}))
        self.assertIsNone(validate({'status':'completed','download_mb_s':True}))
        self.assertIsNone(validate({'status':'completed','download_mb_s':float('nan')}))
        self.assertTrue(validate({'status':'completed','download_mb_s':50,'region':'AS','server_region':'AS'})['qualified'])


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
