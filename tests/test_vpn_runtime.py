import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import vpn_runtime as runtime
import tunnel_manager

ORIGINAL='port 110\nproto tcp-server\ndev tun\nmanagement /run/openvpn/beeny-management.sock unix\nclient-connect /opt/beeny-panel/scripts/vpn_admission.py\nca /etc/openvpn/ca.crt\n'

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.config=self.root/'server.conf';self.config.write_text(ORIGINAL)
        self.patchers=[patch.object(runtime,'ROOT',self.root/'runtime'),patch.object(runtime,'CONFIG',self.config)]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
        self.failed=False;self.fail_new=False;self.commands=[]
        def run(*args,check=True):
            self.commands.append(args)
            if args[:2]==('systemctl','restart') and self.fail_new and runtime.settings(self.config.read_text())['proto']=='udp':
                raise subprocess.CalledProcessError(1,args)
            if args[:2]==('systemctl','show'):out='8123\n'
            elif args[0]=='ss':out='LISTEN 0 32 0.0.0.0:1194 users:(("openvpn",pid=8123,fd=7))'
            else:out=''
            return subprocess.CompletedProcess(args,0,out,'')
        self.mock=patch.object(runtime,'run',side_effect=run);self.mock.start();self.addCleanup(self.mock.stop)
    def apply(self):
        return runtime.handle('apply',dict(proto='udp',tcp_port=110,udp_port=free_port()),runtime.status()['revision'])
    def test_transaction_changes_core_keeps_pki_and_hooks_and_confirms(self):
        state=self.apply()
        self.assertEqual(state['proto'],'udp');self.assertIsNotNone(state['pending'])
        text=self.config.read_text()
        for line in ORIGINAL.splitlines()[2:]:self.assertIn(line,text)
        self.assertTrue(any(c[0]=='systemd-run' for c in self.commands))
        self.assertIsNone(runtime.handle('confirm',revision=state['pending']['token'])['pending'])
    def test_failed_restart_restores_original(self):
        self.fail_new=True
        with self.assertRaises(subprocess.CalledProcessError):self.apply()
        self.assertEqual(self.config.read_text(),ORIGINAL)
        self.assertFalse((runtime.ROOT/'pending.json').exists())
    def test_unconfirmed_expired_change_rolls_back(self):
        self.apply();pending=runtime.load('pending.json');pending['deadline']=0;runtime.save('pending.json',pending)
        self.assertEqual(runtime.handle('status')['proto'],'tcp');self.assertEqual(self.config.read_text(),ORIGINAL)
    def test_external_edits_are_never_overwritten_by_rollback(self):
        state=self.apply();self.config.write_text(self.config.read_text()+'# operator edit\n')
        with self.assertRaises(RuntimeError):runtime.handle('rollback',revision=state['pending']['token'])
        self.assertIn('# operator edit',self.config.read_text())
    def test_stale_revision_does_not_restart(self):
        with self.assertRaises(ValueError):runtime.handle('apply',dict(proto='udp',tcp_port=110,udp_port=1194),'old')
        self.assertFalse(any(c[:2]==('systemctl','restart') for c in self.commands))
    def test_boot_recovers_unconfirmed_configuration_without_restart(self):
        self.apply();self.commands.clear();runtime.recover_boot()
        self.assertEqual(self.config.read_text(),ORIGINAL);self.assertFalse(self.commands)
    def test_external_change_cannot_be_confirmed(self):
        state=self.apply();self.config.write_text(self.config.read_text()+'# external edit\n')
        with self.assertRaises(ValueError):runtime.handle('confirm',revision=state['pending']['token'])
    def test_occupied_udp_port_rejected_before_config_write(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.bind(('0.0.0.0',0))
            with self.assertRaises(OSError):runtime.handle('apply',dict(proto='udp',tcp_port=110,udp_port=sock.getsockname()[1]),runtime.status()['revision'])
        self.assertEqual(self.config.read_text(),ORIGINAL)
    def test_ports_remain_independent_when_switching_back(self):
        state=self.apply();udp=state['udp_port'];runtime.handle('confirm',revision=state['pending']['token'])
        state=runtime.handle('apply',dict(proto='tcp',tcp_port=free_port(),udp_port=udp),runtime.status()['revision'])
        self.assertEqual(state['udp_port'],udp);self.assertEqual(state['port'],state['tcp_port'])
    def test_malformed_ports_and_ambiguous_config_rejected(self):
        for p in [True,-1,0,65536,'1; reboot','1.5',None]:
            with self.subTest(port=p),self.assertRaises(ValueError):runtime.port(p)
        with self.assertRaises(ValueError):runtime.settings(ORIGINAL+'port 443\n')
        with self.assertRaises(ValueError):runtime.settings(ORIGINAL+'config other.conf\n')
    def test_single_session_commands_and_management_stay_unchanged(self):
        transformed=runtime.transform(ORIGINAL,'udp',1194)
        self.assertIn('management /run/openvpn/beeny-management.sock unix',transformed)
        self.assertNotIn('killall',transformed)

def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:sock.bind(('0.0.0.0',0));return sock.getsockname()[1]

class PairingTests(unittest.TestCase):
    def test_invitation_pins_a_real_certificate_and_contains_no_private_key(self):
        pem,key=tunnel_manager.cert()
        value=tunnel_manager.validate_invitation(dict(version=1,mode='tls',token='c'*64,host='IR.example.com',control_port=7000,public_port=2443,ca=pem))
        self.assertEqual(value['host'],'ir.example.com');self.assertEqual(len(value['fingerprint']),64)
        self.assertNotIn('PRIVATE KEY',json.dumps(value))
        config=tunnel_manager.config_exit(value,dict(proto='udp',port=1194))
        self.assertIn('trustedCaFile',config);self.assertIn('serverName = "beeny-tunnel"',config)
        self.assertIn('udpPacketSize = 2048',config);self.assertNotIn('proxyProtocol',config)
    def test_invitation_rejects_arbitrary_targets_or_credentials(self):
        for value in [None,{},dict(version=1,mode='bad'),dict(version=1,mode='tls',token='x')]:
            with self.assertRaises((ValueError,TypeError)):tunnel_manager.validate_invitation(value)
        for host in ['https://host/path','host;id','x\nlocalhost','',None]:
            with self.assertRaises(ValueError):tunnel_manager.host(host)
