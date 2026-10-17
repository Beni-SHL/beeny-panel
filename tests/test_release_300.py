import importlib.util, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import cluster,privileged_server
from scripts.scheduled_backup import encrypt
from scripts.decrypt_backup import decrypt
class ReleaseHardeningTests(unittest.TestCase):
    def test_https_node_port_and_credentials(self):
        for target,expected in [('https://node.example','https://node.example'),('http://node.example','http://node.example'),('192.0.2.1:6200','http://192.0.2.1:6200'),('node.example','http://node.example:5001')]:self.assertEqual(cluster.node_url(SimpleNamespace(host=target,ip='')),expected)
        for target in ['https://user:password@node.example','https://node.example?token=key','https://node.example#secret']:
            with self.assertRaises(ValueError):cluster.node_url(SimpleNamespace(host=target,ip=''))
    def test_helper_allowlist_and_username_paths(self):
        for name in ['ssh','nginx','../../etc/passwd']:
            with self.assertRaises(ValueError):privileged_server.dispatch('service',dict(name=name,action='stop'))
        for value in ['../root','/etc/passwd','.hidden','a;reboot','']:
            with self.assertRaises(ValueError):privileged_server.username(value)
        self.assertEqual(privileged_server.username('legacy.user-1'),'legacy.user-1')
    def test_failed_vpn_restart_propagates(self):
        import subprocess
        with patch('privileged_server.subprocess.run',side_effect=subprocess.CalledProcessError(1,['systemctl'])):
            with self.assertRaises(subprocess.CalledProcessError):privileged_server.dispatch('service',dict(name='openvpn-server@server',action='restart'))
    def test_encrypted_backup_and_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'snapshot';source.write_bytes(os.urandom(1500000));key=root/'key';key.write_bytes(os.urandom(32));encrypted=root/'snapshot.enc';target=root/'restored'
            encrypt(source,encrypted,key.read_bytes());decrypt(encrypted,target,key);self.assertEqual(target.read_bytes(),source.read_bytes())
            data=bytearray(encrypted.read_bytes());data[100]^=1;encrypted.write_bytes(data)
            with self.assertRaises(Exception):decrypt(encrypted,root/'invalid',key)
            self.assertFalse((root/'invalid').exists());self.assertFalse(list(root.glob('.beeny-decrypt-*')))
    def test_unprivileged_services(self):
        root=Path(__file__).resolve().parents[1]
        for file in ['beeny-panel.service','beeny-customer-worker.service']:
            text=(root/file).read_text();self.assertIn('User=beeny',text);self.assertIn('ProtectSystem=strict',text)
        self.assertIn('User=root',(root/'beeny-privileged.service').read_text())
class NodeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'node_agent/bridge.py';spec=importlib.util.spec_from_file_location('test_node_bridge_module',path);cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)
    def setUp(self):
        self.key=patch.object(self.module,'KEY','test-bridge-key');self.key.start();self.client=self.module.app.test_client();self.headers={'Authorization':'Bearer test-bridge-key'}
    def tearDown(self):self.key.stop()
    def test_authentication_and_path_allowlist(self):
        self.assertEqual(self.client.get('/api/node/stats').status_code,401);self.assertEqual(self.client.get('/api/node/arbitrary',headers=self.headers).status_code,404);self.assertEqual(self.client.post('/api/node/set-user-state',json={'username':'../root','active':True},headers=self.headers).status_code,400)
    def test_loopback_forwarding(self):
        session=Mock();session.post.return_value=SimpleNamespace(content=b'{"success":true}',status_code=200,headers={})
        with patch.object(self.module.requests,'Session',return_value=session):response=self.client.post('/api/node/install-cert',json={'username':'test'},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(session.post.call_args.args[0],'http://127.0.0.1:6200/api/node/install-cert');self.assertFalse(session.trust_env)
    def test_inactive_vpn_has_no_stale_connections(self):
        with patch.object(self.module.subprocess,'run',return_value=SimpleNamespace(returncode=1)),patch.object(self.module,'metrics',return_value={'interface':'eth0'}):response=self.client.get('/api/node/status-log',headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertFalse(response.json['vpn_active']);self.assertEqual(response.json['log'],'')
