import sqlite3
import tempfile
from pathlib import Path
import unittest

from scripts.repair_local_access import repair


class LocalAccessRepairTests(unittest.TestCase):
    def test_startup_enable_preserves_custom_ccd_directives(self):
        from vpn_sessions import enable_ccd
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'client'
            path.write_text('disable\nifconfig-push 10.8.0.2 255.255.255.0\n')
            enable_ccd(path)
            self.assertEqual(path.read_text(),'ifconfig-push 10.8.0.2 255.255.255.0\n')
            enable_ccd(path)
            self.assertEqual(path.read_text(),'ifconfig-push 10.8.0.2 255.255.255.0\n')
            path.write_text('disable\n')
            enable_ccd(path)
            self.assertFalse(path.exists())

    def test_repair_preserves_quota_directives_and_legitimate_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database, ccd, backup = root/'panel.db', root/'ccd', root/'backup'
            ccd.mkdir()
            with sqlite3.connect(database) as db:
                db.executescript('''
                    CREATE TABLE user(id INTEGER PRIMARY KEY, username TEXT, status TEXT,
                        customer_paused INTEGER, expire_date TEXT, traffic_limit INTEGER,
                        traffic_usage REAL, traffic_used INTEGER);
                    CREATE TABLE nodes(id INTEGER PRIMARY KEY, api_key TEXT);
                    CREATE TABLE user_nodes(user_id INTEGER, node_id INTEGER);
                    CREATE TABLE account_devices(user_id INTEGER, common_name TEXT, blocked INTEGER);
                    INSERT INTO nodes VALUES(1,'__beeny_local_primary__'),(9,'remote');
                ''')
                for uid, name, status, paused, expiry, limit, used, node in (
                    (1,'valid','active',0,'2099-01-01',100,25,1),
                    (2,'manual','disabled',0,'2099-01-01',100,25,1),
                    (3,'paused','active',1,'2099-01-01',100,25,1),
                    (4,'expired','active',0,'2000-01-01',100,25,1),
                    (5,'quota','active',0,'2099-01-01',20,25,1),
                    (6,'remote','active',0,'2099-01-01',100,25,9),
                    (7,'bad-date','active',0,'broken-date',100,25,1)):
                    db.execute('INSERT INTO user VALUES(?,?,?,?,?,?,?,?)',
                               (uid,name,status,paused,expiry,limit,used,used*1073741824))
                    db.execute('INSERT INTO user_nodes VALUES(?,?)', (uid,node))
                    (ccd/name).write_text('disable\n; Preserve this\nifconfig-push 10.8.0.2 255.255.255.0\n')
                db.execute("INSERT INTO account_devices VALUES(1,'d_allowed',0),(1,'d_blocked',1)")
            for name in ('d_allowed','d_blocked'):
                (ccd/name).write_text('disable\n')
            before = database.read_bytes()
            self.assertEqual(repair(database,ccd,backup), ['valid','d_allowed'])
            self.assertFalse(backup.exists())
            self.assertTrue((ccd/'valid').read_text().startswith('disable'))
            self.assertEqual(repair(database,ccd,backup,True), ['valid','d_allowed'])
            self.assertNotIn('disable', (ccd/'valid').read_text())
            self.assertIn('ifconfig-push', (ccd/'valid').read_text())
            self.assertTrue((backup/'valid').read_text().startswith('disable'))
            for name in ('manual','paused','expired','quota','remote','bad-date','d_blocked'):
                self.assertTrue((ccd/name).read_text().startswith('disable'))
            self.assertEqual(repair(database,ccd,backup,True), [])
            self.assertEqual(database.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
