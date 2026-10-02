import io
import json
import os
import tarfile
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

    def result(self, speed=400):
        return json.dumps([{"download": speed, "bytes_received": 1500000000,
                            "server": {"name": "Fixture", "url": "https://example.test/"}}])

    def test_mbps_conversion_and_threshold(self):
        for speed, expected in [(399.99, False), (400, True), (800, True)]:
            result = module.parse_result(self.result(speed))
            self.assertEqual(result["download_mb_s"], speed / 8)
            self.assertEqual(result["qualified"], expected)
        for speed in [True, -1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                module.parse_result(self.result(speed))
        with self.assertRaises(ValueError):
            module.parse_result('[]')

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

    def test_worker_uses_download_only_and_stores_result(self):
        value = {"status": "pending", "run_id": "fixture", "created": 0, "pid": os.getpid()}
        module.save(self.directory/'bandwidth.json', value)
        with patch.object(module, 'install', return_value=Path('/fixture/librespeed-cli')), patch.object(module, 'discovery', return_value=({'region': 'AS', 'country': 'Japan'}, [{'server': 'https://example.test/'}])), patch.object(module.time, 'sleep'), patch.object(module.subprocess, 'run', return_value=Mock(stdout=self.result())) as execute:
            module.run(self.directory, 'fixture')
        args = execute.call_args.args[0]
        self.assertIn('--no-upload', args)
        self.assertEqual(args[args.index('--duration')+1], '30')
        result = module.snapshot(self.directory)
        self.assertEqual(result['download_mb_s'], 50)
        self.assertNotIn('pid', result)
        self.assertNotIn('client', result)

    def test_failure_is_not_a_zero_speed_measurement(self):
        module.save(self.directory/'bandwidth.json', {"status": "pending", "run_id": "fixture"})
        with patch.object(module, 'install', side_effect=OSError('offline')), patch.object(module.time, 'sleep'):
            module.run(self.directory, 'fixture')
        result = module.snapshot(self.directory)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('download_mb_s', result)
        self.assertIsNone(validate({"status": "completed", "download_mb_s": float('nan')}))
        self.assertIsNone(validate({"status": "completed", "download_mb_s": True}))
        self.assertTrue(validate({"status": "completed", "download_mb_s": 50, "region": "AS", "server_region": "AS"})['qualified'])

    def test_checksum_failure_never_installs_executable(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'not the official archive'
        with patch.object(module.platform, 'machine', return_value='x86_64'), patch.object(module, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(ValueError):
                module.install(self.directory)
        self.assertFalse((self.directory/('librespeed-cli-'+module.VERSION)).exists())

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

    def test_cross_region_cli_result_is_rejected_even_when_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            module.save(path/'bandwidth.json', {'status': 'pending', 'run_id': 'fixture'})
            wrong = json.dumps([{'download': 800, 'bytes_received': 10000000,
                                  'server': {'name': 'USA', 'url': 'https://usa.test/'}}])
            with patch.object(module, 'install', return_value=Path('/fixture/cli')), patch.object(module.time, 'sleep'), patch.object(module, 'discovery', return_value=({'region': 'AS'}, self.servers[:1])), patch.object(module.subprocess, 'run', return_value=Mock(stdout=wrong)) as execute:
                module.run(path, 'fixture')
            result = module.snapshot(path)
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('download_mb_s', result)
            self.assertIn('--local-json', execute.call_args.args[0])
            self.assertFalse((path/'bandwidth-servers.json').exists())
