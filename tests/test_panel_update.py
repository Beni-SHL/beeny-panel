import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import panel_update as updater
import test_customer as fixture
panel=fixture.panel

class UpdateWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.patches=[patch.object(updater,'ROOT',self.root),patch.object(updater,'installed',return_value='3.7.4')]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def release(self,**changes):
        data=dict(commit='a'*40,version='3.7.5',checked_at=time.time(),available=True)
        data.update(changes);updater.save('release.json',data)
    def test_fixed_commit_version_check(self):
        with patch.object(updater,'fetch',side_effect=[json.dumps(dict(sha='b'*40)).encode(),b'3.7.5\n']) as fetch:
            result=updater.check()
        self.assertTrue(result['release']['available'])
        self.assertEqual(fetch.call_args_list[1].args[0],'https://raw.githubusercontent.com/Beni-SHL/beeny-panel/'+'b'*40+'/VERSION')
    def test_invalid_or_older_versions_never_queue(self):
        for data in ['main','a'*39,'a'*40+'; reboot',None]:
            with self.subTest(data=data),self.assertRaises(ValueError):updater.queue(data)
        self.release(version='3.7.3')
        with self.assertRaisesRegex(ValueError,'No newer'):updater.queue('a'*40)
    def test_expired_check_and_duplicate_install_rejected(self):
        self.release(checked_at=time.time()-1801)
        with self.assertRaisesRegex(ValueError,'expired'):updater.queue('a'*40)
        self.release()
        with patch.object(updater.subprocess,'run') as run:
            first=updater.queue('a'*40)
            self.assertEqual(first['job']['state'],'queued')
            self.assertIn('/usr/bin/python3',run.call_args.args[0])
            with self.assertRaisesRegex(ValueError,'already running'):updater.queue('a'*40)
            self.assertEqual(run.call_count,1)
    def test_worker_start_failure_has_terminal_status(self):
        self.release()
        with patch.object(updater.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'systemd-run')):
            with self.assertRaises(subprocess.CalledProcessError):updater.queue('a'*40)
        self.assertEqual(updater.status()['job']['state'],'failed')
    def test_fetch_failure_does_not_run_installer(self):
        self.release()
        with patch.object(updater.subprocess,'run'):job=updater.queue('a'*40)['job']
        with patch.object(updater.os,'geteuid',return_value=0),patch.object(updater.subprocess,'run',side_effect=OSError('offline')) as run:
            with self.assertRaises(OSError):updater.execute(job['id'])
        self.assertEqual(updater.status()['job']['state'],'failed')
        self.assertEqual(run.call_count,1)
        self.assertFalse((self.root/('update-'+job['id']+'.log')).exists())
    def test_verified_release_completes_after_installer_health_check(self):
        self.release()
        with patch.object(updater.subprocess,'run'):job=updater.queue('a'*40)['job']
        with patch.object(updater.os,'geteuid',return_value=0),patch.object(updater,'installed',return_value='3.7.4') as current:
            def process(args,**kwargs):
                if args[0]=='git':
                    checkout=Path(args[args.index('-C')+1]);(checkout/'VERSION').write_text('3.7.5')
                    return subprocess.CompletedProcess(args,0,stdout='a'*40+'\n')
                self.assertEqual(args[0],'bash')
                self.assertTrue(args[1].endswith('/scripts/update_panel.sh'))
                current.return_value='3.7.5'
                return subprocess.CompletedProcess(args,0)
            with patch.object(updater.subprocess,'run',side_effect=process):updater.execute(job['id'])
        self.assertEqual(updater.read('job.json')['state'],'completed')

    def test_changed_commit_is_not_applied(self):
        self.release()
        with patch.object(updater.subprocess,'run'):job=updater.queue('a'*40)['job']
        with patch.object(updater.os,'geteuid',return_value=0),patch.object(updater.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='b'*40)) as run:
            with self.assertRaisesRegex(ValueError,'does not match'):updater.execute(job['id'])
        self.assertEqual(updater.status()['job']['state'],'failed')
        self.assertFalse(any(c.args[0][0]=='bash' for c in run.call_args_list))

class UpdateAccessTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_owner_page_and_csrf(self):
        self.admin()
        self.assertEqual(self.client.get('/panel/settings/update').status_code,200)
        with patch('privileged_server.dispatch',return_value=dict(success=True,installed='3.7.4',release=None,job=None)):
            result=self.client.post('/panel/api/settings/update',json={'action':'status'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        self.client.environ_base.pop('HTTP_X_CSRF_TOKEN',None)
        self.assertEqual(self.client.post('/panel/api/settings/update',json={'action':'install','commit':'a'*40}).status_code,400)
    def test_viewer_cannot_check_or_install(self):
        self.admin();panel.Admin.query.first().role='viewer';panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/settings/update').status_code,403)
        with patch('privileged_server.dispatch') as dispatch:
            for action in ['status','check','install']:
                self.assertEqual(self.client.post('/panel/api/settings/update',json={'action':action}).status_code,403)
            dispatch.assert_not_called()
