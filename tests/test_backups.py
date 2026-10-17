import io,json,sqlite3,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import backup_engine as backups

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.panel=root/'panel';self.vpn=root/'vpn';self.env=root/'config/panel.env'
        self.panel.mkdir();self.vpn.mkdir();self.env.parent.mkdir();self.env.write_text('SECRET=preserved')
        (self.panel/'instance').mkdir();(self.panel/'instance/avatar.webp').write_bytes(b'avatar');(self.panel/'app.py').write_text('original code')
        with sqlite3.connect(self.panel/'instance/beeny.db') as db:db.execute('CREATE TABLE admin (id INTEGER)');db.execute('INSERT INTO admin VALUES (1)')
        (self.vpn/'ca.key').write_text('private CA preserved')
        self.patch=patch.multiple(backups,PANEL=self.panel,VPN=self.vpn,ENV=self.env,BACKUPS=self.panel/'backups');self.patch.start()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_complete_snapshot_contains_data_env_code_and_vpn_and_validates(self):
        name=backups.create();path=backups.safe_file(name)
        self.assertGreater(backups.validate(path)['files'],4)
        with tarfile.open(path) as archive:
            self.assertIn('vpn/ca.key',archive.getnames());self.assertIn('env/panel.env',archive.getnames());self.assertIn('panel/instance/avatar.webp',archive.getnames())
            self.assertFalse(any('backup-signing.key' in name for name in archive.getnames()))
        stage=Path(self.temp.name)/'stage';backups.validate(path,stage)
        with sqlite3.connect(stage/'panel/instance/beeny.db') as db:self.assertEqual(db.execute('SELECT id FROM admin').fetchone()[0],1)
    def test_failed_creation_removes_incomplete_download(self):
        with patch.object(backups,'validate',side_effect=ValueError('corrupt archive')):
            with self.assertRaises(ValueError):backups.create()
        self.assertFalse(list(backups.BACKUPS.glob('*.tar.gz')))

    def test_traversal_symlink_unsigned_and_corruption_are_rejected(self):
        for name in ('../other.db','/tmp/other.db','archive.zip'):
            with self.assertRaises(ValueError):backups.safe_file(name)
        name=backups.create();source=backups.safe_file(name)
        bad=backups.safe_file('evil.tar.gz')
        with tarfile.open(bad,'w:gz') as archive:
            item=tarfile.TarInfo('../outside');item.size=4;archive.addfile(item,io.BytesIO(b'evil'))
        with self.assertRaises(ValueError):backups.validate(bad)
        with tarfile.open(source) as archive:members={i.name:archive.extractfile(i).read() for i in archive}
        members['panel/app.py']=b'forged code'
        with tarfile.open(bad,'w:gz') as archive:
            for name,data in members.items():item=tarfile.TarInfo(name);item.size=len(data);archive.addfile(item,io.BytesIO(data))
        with self.assertRaises(ValueError):backups.validate(bad)
    def test_database_snapshot_is_signed_and_modified_data_rejected(self):
        path=backups.safe_file(backups.create(full=False));backups.validate(path)
        with sqlite3.connect(path) as db:db.execute('DELETE FROM admin')
        with self.assertRaises(ValueError):backups.validate(path)
    def test_failed_restore_rolls_back_code_and_database(self):
        source=backups.create();(self.panel/'app.py').write_text('current code')
        class Result:returncode=0
        attempts=0
        def command(args,**kw):
            nonlocal attempts
            if args[:2]==['systemctl','start']:
                attempts+=1
                if attempts==1:raise RuntimeError('simulated service startup failure')
            return Result()
        with patch('subprocess.run',side_effect=command):
            with self.assertRaises(RuntimeError):backups.restore(source)
        self.assertEqual((self.panel/'app.py').read_text(),'current code')
        with sqlite3.connect(self.panel/'instance/beeny.db') as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM admin').fetchone()[0],1)
        self.assertEqual(attempts,2)

    def test_internal_vpn_symlink_is_preserved_during_restore(self):
        (self.vpn/'ta-real.key').write_text('original shared key')
        (self.vpn/'ta.key').symlink_to('ta-real.key')
        source=backups.create();(self.vpn/'ta-real.key').write_text('changed key')
        class Result:returncode=0
        with patch('subprocess.run',return_value=Result()):backups.restore(source)
        self.assertTrue((self.vpn/'ta.key').is_symlink())
        self.assertEqual((self.vpn/'ta.key').read_text(),'original shared key')
