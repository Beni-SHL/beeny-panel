import importlib.util
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, Mock
import os
import subprocess
from traffic_ledger import parse_status

spec=importlib.util.spec_from_file_location('legacy',Path(__file__).resolve().parents[1]/'scripts/upgrade_legacy.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)

class LegacyTests(unittest.TestCase):
    def test_status_v1_ignores_routing_and_keeps_distinct_sessions(self):
        text='''OpenVPN CLIENT LIST
Updated,Wed Oct 7 22:00:00 2026
Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
alice,198.51.100.1:123,100,200,Wed Oct 7 21:00:00 2026
alice,198.51.100.1:456,300,400,Wed Oct 7 21:30:00 2026
ROUTING TABLE
Virtual Address,Common Name,Real Address,Last Ref
10.8.0.2,alice,198.51.100.1:123,Wed Oct 7 22:00:00 2026
GLOBAL STATS
Max bcast/mcast queue length,0
END
'''
        rows=parse_status(text)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0][2:4],(100,200))
        self.assertNotEqual(rows[0][1],rows[1][1])

    def test_legacy_inspection_and_primary_promotion_preserve_remote_node_and_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'panel';vpn=Path(tmp)/'openvpn'
            for folder in (root/'instance',root/'venv/bin',vpn/'server',vpn/'easy-rsa/pki/issued',vpn/'easy-rsa/pki/private'):
                folder.mkdir(parents=True)
            (root/'venv/bin/python').write_text('placeholder')
            (root/'app.py').write_text("class Node:\n __tablename__ = 'nodes'\napp.run(host='0.0.0.0',port=8080)\n")
            (root/'config.json').write_text(json.dumps({'panel_path':'/Ho@B3n2','panel_url':'http://localhost:8080'}))
            for rel in ('easy-rsa/ta.key','easy-rsa/pki/ca.crt','easy-rsa/pki/issued/server.crt','easy-rsa/pki/private/server.key'):
                (vpn/rel).write_text('existing-material')
            conf=f'''port 110
proto tcp
dev tun
ca {vpn}/easy-rsa/pki/ca.crt
cert {vpn}/easy-rsa/pki/issued/server.crt
key {vpn}/easy-rsa/pki/private/server.key
tls-auth {vpn}/easy-rsa/ta.key 0
management 127.0.0.1 7505
'''
            (vpn/'server/server.conf').write_text(conf)
            database=root/'instance/beeny.db'
            with sqlite3.connect(database) as db:
                db.executescript("CREATE TABLE nodes(id INTEGER PRIMARY KEY,name TEXT,ip TEXT,host TEXT,country TEXT,api_key TEXT);CREATE TABLE user(id INTEGER PRIMARY KEY,username TEXT);CREATE TABLE admin(id INTEGER PRIMARY KEY,password TEXT);CREATE TABLE user_nodes(id INTEGER,user_id INTEGER,node_id INTEGER);")
                db.execute("INSERT INTO admin VALUES (1,'scrypt:test-hash')")
                db.execute("INSERT INTO user VALUES (1,'existing-user')")
                db.execute("INSERT INTO nodes VALUES (1,'Main','185.208.172.91','', 'NL','old-local-key')")
                db.execute("INSERT INTO nodes VALUES (2,'England','192.0.2.2','','GB','remote-private-key')")
                db.execute('INSERT INTO user_nodes VALUES (1,1,2)')
            facts=legacy.inspect_install(root,vpn)
            self.assertEqual(facts['config']['panel_path'],'/Ho@B3n2')
            self.assertEqual(facts['vpn_port'],110)
            legacy.promote_primary(database,facts['nodes'][0])
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT api_key FROM nodes WHERE id=2').fetchone()[0],'remote-private-key')
                self.assertEqual(db.execute('SELECT node_id FROM user_nodes').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM traffic_baseline WHERE pending=1').fetchone()[0],2)
            self.assertEqual((vpn/'server/server.conf').read_text(),conf)
            # Exercise preparation rollback with the original service/node/files intact.
            with sqlite3.connect(database) as db:
                db.execute("UPDATE nodes SET api_key='old-local-key' WHERE id=1")
                db.execute('DELETE FROM traffic_baseline')
            envfile=Path(tmp)/'etc/beeny-panel/panel.env'
            unit=Path(tmp)/'etc/systemd/system/beeny-panel.service'
            unit.parent.mkdir(parents=True);unit.write_text('original legacy unit')
            path_class=Path
            mapping={'/opt/beeny-panel':root,'/etc/openvpn':vpn,'/etc/beeny-panel/panel.env':envfile,'/etc/systemd/system/beeny-panel.service':unit}
            original_os_open=os.open
            opened=[]
            def local_open(path,*args):
                if str(path)=='/run/beeny-panel-update.lock':
                    fd=original_os_open(Path(tmp)/'update.lock',*args);opened.append(fd);return fd
                return original_os_open(path,*args)
            def command(args,**kwargs):
                if args[0]=='bash':raise subprocess.CalledProcessError(1,args)
                return subprocess.CompletedProcess(args,0)
            with patch.object(legacy,'Path',side_effect=lambda value: mapping.get(str(value),path_class(value))), patch.object(legacy.sys,'stdin',Mock(isatty=Mock(return_value=True))), patch('builtins.input',side_effect=['1','185.208.172.91','n']), patch.object(legacy.subprocess,'run',side_effect=command), patch.object(legacy.os,'open',side_effect=local_open), patch.object(legacy.os,'dup2'), patch.object(legacy.os,'set_inheritable'):
                with self.assertRaises(subprocess.CalledProcessError):legacy.main()
            for fd in opened:os.close(fd)
            self.assertFalse(envfile.exists())
            self.assertFalse((vpn/'ta.key').exists())
            self.assertEqual(unit.read_text(),'original legacy unit')
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT api_key FROM nodes WHERE id=1').fetchone()[0],'old-local-key')
                self.assertEqual(db.execute('SELECT api_key FROM nodes WHERE id=2').fetchone()[0],'remote-private-key')
                self.assertEqual(db.execute('SELECT node_id FROM user_nodes').fetchone()[0],2)
            self.assertTrue(list((root/'backups').glob('legacy-*/beeny.db')))
            (vpn/'ta.key').write_text('different-material')
            with self.assertRaises(ValueError):legacy.inspect_install(root,vpn)

    def test_public_host_validation(self):
        for text in ('127.0.0.1','192.168.1.1','localhost','vpn.example.com;rm','https://vpn.example.com'):
            with patch('builtins.input',return_value=text),self.assertRaises(ValueError):legacy.host_input('')
        with patch('builtins.input',return_value='vpn.example.com'):
            self.assertEqual(legacy.host_input(''),'vpn.example.com')
