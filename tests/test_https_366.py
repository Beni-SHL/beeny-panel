import unittest,tempfile
from pathlib import Path
from unittest.mock import patch,Mock
import https_maintenance as h
class HttpsTests(unittest.TestCase):
    def test_invalid_actions_never_run_commands(self):
        with patch.object(h,'run') as run:
            with self.assertRaises(ValueError):h.schedule('shell')
        run.assert_not_called()
    def test_manual_renewal_queued_without_force_or_vpn_restart(self):
        with patch.object(h,'config',return_value=('example.com','/usr/bin/certbot')),patch.object(h,'run') as run:
            result=h.schedule('test')
        self.assertTrue(result['queued']);args=run.call_args.args
        self.assertIn('--unit=beeny-https-manual',args)
        self.assertEqual(args[-1],'test')
        self.assertNotIn('--force-renewal',args)
    def test_failed_renewal_persists_failed_status_and_never_reloads(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(h,'ROOT',Path(tmp)),patch.object(h,'config',return_value=('example.com','certbot')),patch.object(h.subprocess,'run',side_effect=RuntimeError('private detail')):
            self.assertFalse(h.execute('renew'))
            result=(Path(tmp)/'result.json').read_text()
            self.assertIn('failed',result);self.assertNotIn('private detail',result)
    def test_test_run_does_not_reload_nginx(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(h,'ROOT',Path(tmp)),patch.object(h,'config',return_value=('example.com','certbot')),patch.object(h.subprocess,'run',return_value=Mock(returncode=0)) as run:
            self.assertTrue(h.execute('test'))
            self.assertEqual(run.call_count,1)
            self.assertIn('--dry-run',run.call_args.args[0])
