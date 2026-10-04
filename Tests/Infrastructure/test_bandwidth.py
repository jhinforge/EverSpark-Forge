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

    def payload(self):
        return {'type':'result','download':{'bandwidth':97372229,'bytes':668774728,'elapsed':6902},
                'upload':{'bandwidth':95521432,'bytes':1376105189,'elapsed':15010},
                'ping':{'latency':8.655,'jitter':.216},'packetLoss':0,
                'server':{'id':5249,'name':'Fixture','location':'Seoul','country':'South Korea','ip':'private-server-ip'},
                'interface':{'externalIp':'private-public-ip','macAddr':'private-mac'},'isp':'private-isp',
                'result':{'url':'private-result-url'}}

    def test_result_units_server_location_and_privacy(self):
        result = module.parse_result(self.payload())
        self.assertEqual(result['download_mb_s'], 97.372229)
        self.assertEqual(result['upload_mb_s'], 95.521432)
        self.assertEqual(result['elapsed_seconds'],6.902)
        self.assertEqual(result['latency_ms'],8.655)
        self.assertEqual(result['server_country'],'South Korea')
        self.assertNotIn('region',result)
        self.assertTrue(result['qualified'])
        self.assertNotIn('private-',json.dumps(result))
        self.assertTrue(validate(result)['qualified'])
        slow=self.payload();slow['download']['bandwidth']=223826
        slow['packetLoss']=2.0066889632107023
        measured=module.parse_result(slow)
        self.assertEqual(measured['status'],'completed')
        self.assertAlmostEqual(measured['download_mb_s'],.223826)
        self.assertFalse(validate(measured)['qualified'])
        slow['packetLoss']=None
        self.assertNotIn('packet_loss_percent',module.parse_result(slow))

    def test_incomplete_nonfinite_and_error_results_cannot_be_measurements(self):
        for section,key,value in [('download','bandwidth',True),('download','bandwidth',float('nan')),
                                  ('upload','bytes',0),('download','elapsed',0),('ping','latency',-1),
                                  ('server','id',True),('server','country','')]:
            payload=self.payload();payload[section][key]=value
            with self.assertRaises(ValueError):module.parse_result(payload)
        payload=self.payload();payload['packetLoss']=101
        with self.assertRaises(ValueError):module.parse_result(payload)
        for payload in [None,{}, {'type':'error'}, {'type':'result','download':[]}]:
            with self.assertRaises(ValueError):module.parse_result(payload)

    def test_cli_command_default_selection_no_implicit_terms_acceptance(self):
        with patch.object(module.subprocess,'run',return_value=Mock(returncode=0,stdout=json.dumps(self.payload()))) as execute:
            module.measure(Path('/fixture/speedtest'))
        self.assertEqual(execute.call_args.args[0],['/fixture/speedtest','--format=json','--progress=no'])
        self.assertEqual(execute.call_args.kwargs['timeout'],90)
        self.assertEqual(execute.call_args.kwargs['stdin'],module.subprocess.DEVNULL)

    def test_failure_retries_once_but_terms_do_not_retry(self):
        success=Mock(returncode=0,stdout=json.dumps(self.payload()),stderr='')
        failure=Mock(returncode=1,stdout='{"type":"error","message":"No servers available"}',stderr='')
        with patch.object(module.subprocess,'run',side_effect=[failure,success]) as execute,patch.object(module.time,'sleep'):
            self.assertEqual(module.measure('fixture')['status'],'completed')
            self.assertEqual(execute.call_count,2)
        with patch.object(module.subprocess,'run',return_value=failure) as execute,patch.object(module.time,'sleep'):
            with self.assertRaisesRegex(ValueError,'No servers available'):module.measure('fixture')
            self.assertEqual(execute.call_count,2)
        terms=Mock(returncode=1,stdout='You must accept the license',stderr='')
        with patch.object(module.subprocess,'run',return_value=terms) as execute:
            with self.assertRaises(module.TermsRequired):module.measure('fixture')
            self.assertEqual(execute.call_count,1)
        for error in [module.subprocess.TimeoutExpired('fixture',90),FileNotFoundError('fixture missing')]:
            with patch.object(module.subprocess,'run',side_effect=error) as execute,patch.object(module.time,'sleep'):
                with self.assertRaises(type(error)):module.measure('fixture')
                self.assertEqual(execute.call_count,2)

    def test_actual_subprocess_can_be_repeated_without_shell_or_raw_data_storage(self):
        import sys
        binary=self.directory/'speedtest'
        binary.write_text('#!'+sys.executable+'\nimport json\nprint('+repr(json.dumps(self.payload()))+')\n')
        binary.chmod(0o700)
        for _ in range(3):
            self.assertEqual(module.measure(binary)['server_id'],5249)
        self.assertEqual(list(self.directory.iterdir()),[binary])

    def test_actual_background_worker_and_manual_retest_replace_state(self):
        import sys
        architecture={'x86_64':'x86_64','aarch64':'aarch64'}.get(module.platform.machine().lower())
        if architecture is None or sys.platform != 'linux': self.skipTest('Linux worker architecture required')
        binary=self.directory/f'ookla-speedtest-{module.VERSION}-{architecture}'/'speedtest'
        binary.parent.mkdir()
        binary.write_text('#!'+sys.executable+'\nimport sys\nprint("Speedtest by Ookla 1.2.0" if "--version" in sys.argv else '+repr(json.dumps(self.payload()))+')\n')
        binary.chmod(0o700)
        previous=None
        with patch.dict(os.environ, {'EVERSPARK_NODE_BANDWIDTH':'1'}):
            for _ in range(2):
                pending=module.start(self.directory,force=True)
                self.assertEqual(pending['status'],'pending')
                value=module._read(self.directory)
                self.assertNotEqual(value['run_id'],previous)
                previous=value['run_id']
                deadline=module.time.monotonic()+25
                while module._read(self.directory).get('status') in {'pending','running'} and module.time.monotonic()<deadline:
                    module.time.sleep(.05)
                completed=module.snapshot(self.directory)
                self.assertEqual(completed['status'],'completed',completed)
                self.assertAlmostEqual(completed['download_mb_s'],97.372229)
                self.assertTrue(validate(completed)['qualified'])
                self.assertNotIn('private-',json.dumps(completed))
                value=module._read(self.directory);value['finished_at']='2020-01-01T00:00:00+00:00'
                module.save(self.directory/'bandwidth.json',value)

    def test_private_install_extracts_only_regular_expected_files(self):
        import tarfile
        def install(args,**kwargs):
            archive=Path(args[args.index('-o')+1])
            with tarfile.open(archive,'w:gz') as package:
                for name in ['speedtest','speedtest.md','speedtest.5']:
                    data=b'fixture';member=tarfile.TarInfo(name);member.size=len(data)
                    package.addfile(member,io.BytesIO(data))
            return Mock(returncode=0)
        with patch.object(module.platform,'machine',return_value='x86_64'),patch.object(module.shutil,'which',return_value=None),patch.object(module.subprocess,'run',side_effect=install):
            binary=module.cli(self.directory)
        self.assertEqual(binary.read_bytes(),b'fixture')
        self.assertTrue(os.access(binary,os.X_OK))
        with patch.object(module.platform,'machine',return_value='x86_64'),patch.object(module.subprocess,'run',return_value=Mock(returncode=0,stdout='Speedtest by Ookla 1.2.0')) as command:
            self.assertEqual(module.cli(self.directory),binary)
            self.assertEqual(command.call_count,1)
        with patch.object(module.platform,'machine',return_value='unknown'):
            with self.assertRaisesRegex(ValueError,'architecture'):module.cli(self.directory)

    def test_installer_rejects_archive_symlink(self):
        import tarfile
        def install(args,**kwargs):
            with tarfile.open(args[args.index('-o')+1],'w:gz') as package:
                member=tarfile.TarInfo('speedtest');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd'
                package.addfile(member)
            return Mock(returncode=0)
        with patch.object(module.platform,'machine',return_value='x86_64'),patch.object(module.shutil,'which',return_value=None),patch.object(module.subprocess,'run',side_effect=install):
            with self.assertRaisesRegex(ValueError,'archive'):module.cli(self.directory)

    def test_auto_once_no_concurrent_worker_and_manual_cooldown(self):
        with patch.dict(os.environ, {'EVERSPARK_NODE_BANDWIDTH':'1','EVERSPARK_NODE_JOIN_TOKEN':'secret'}),patch.object(module.subprocess,'Popen',return_value=Mock(pid=os.getpid())) as spawn:
            self.assertEqual(module.start(self.directory)['method'],'ookla_cli')
            module.start(self.directory);module.start(self.directory,force=True)
            self.assertEqual(spawn.call_count,1)
            self.assertNotIn('EVERSPARK_NODE_JOIN_TOKEN',spawn.call_args.kwargs['env'])
            value=module._read(self.directory);value.update(status='completed',finished_at=module.now())
            module.save(self.directory/'bandwidth.json',value)
            module.start(self.directory);module.start(self.directory,force=True)
            self.assertEqual(spawn.call_count,1)
            value['finished_at']='2020-01-01T00:00:00+00:00';module.save(self.directory/'bandwidth.json',value)
            module.start(self.directory,force=True)
            self.assertEqual(spawn.call_count,2)

    def test_worker_saves_result_and_failure_is_not_zero_speed(self):
        for failure in [None,OSError('Network unavailable'),module.TermsRequired('Confirm terms')]:
            module.save(self.directory/'bandwidth.json',{'status':'pending','run_id':'fixture'})
            with patch.object(module,'cli',return_value='fixture'),patch.object(module,'measure',side_effect=failure,return_value=module.parse_result(self.payload())),patch.object(module.time,'sleep'),patch('sys.stderr',new_callable=io.StringIO) as log:
                module.run(self.directory,'fixture')
            result=module.snapshot(self.directory)
            self.assertEqual(result['policy'],module.POLICY)
            self.assertEqual(result['method'],'ookla_cli')
            self.assertNotIn('private-',json.dumps(result))
            if failure:
                self.assertEqual(result['status'],'failed')
                self.assertNotIn('download_mb_s',result)
                self.assertIn(str(failure),log.getvalue())
                if isinstance(failure,module.TermsRequired):self.assertEqual(result['error_code'],'terms_required')
            else:self.assertTrue(validate(result)['qualified'])

    def test_controller_validates_optional_metrics_and_preserves_old_sources(self):
        result=module.parse_result(self.payload())
        for key,value in [('latency_ms',True),('upload_mb_s',float('inf')),('packet_loss_percent',101),
                          ('elapsed_seconds',0),('server_id',0),('bytes_received',0),('server_country','')]:
            self.assertIsNone(validate({**result,key:value}))
        old={'status':'completed','method':'default_model_http',
             'server_url':'https://huggingface.co/fixture/model/resolve/main/model.safetensors',
             'elapsed_seconds':30,'bytes_received':1_500_000_000,'download_mb_s':50}
        self.assertTrue(validate(old)['qualified'])
        self.assertTrue(validate({**old,'method':'cloudflare_http','server_url':'https://speed.cloudflare.com/__down'})['qualified'])
        self.assertIsNone(validate({**old,'elapsed_seconds':1}))


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
