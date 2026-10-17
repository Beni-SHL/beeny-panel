import unittest,time,base64
from unittest.mock import patch,Mock
from flask import g
from werkzeug.security import generate_password_hash
import test_customer as fixture
from test_customer import panel
from security import totp

class SecurityTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin

    def test_admin_login_requires_csrf_and_throttles_wrong_credentials(self):
        self.assertEqual(self.client.post('/panel/login',data={'username':'admin','password':'wrong'}).status_code,400)
        self.client.get('/panel/login')
        with self.client.session_transaction() as session: token=session['_customer_csrf']
        for _ in range(5):self.client.post('/panel/login',data={'csrf':token,'username':'admin','password':'wrong'})
        admin=panel.Admin.query.first();admin.password=generate_password_hash('valid-password-123');panel.db.session.commit()
        self.client.post('/panel/login',data={'csrf':token,'username':'admin','password':'valid-password-123'})
        g.pop('_login_user',None)
        self.assertEqual(self.client.get('/panel/users').status_code,302)

    def test_legacy_get_mutations_are_rejected_and_missing_post_csrf_is_rejected(self):
        self.admin()
        self.assertEqual(self.client.get('/panel/users/delete/'+str(self.user.id)).status_code,405)
        self.assertEqual(self.client.post('/panel/users/delete/'+str(self.user.id),headers={'X-CSRF-Token':''}).status_code,400)
        self.assertIsNotNone(panel.db.session.get(panel.User,self.user.id))

    def test_viewer_cannot_modify_settings_users_or_download_backup(self):
        self.admin();admin=panel.Admin.query.first();admin.role='viewer';panel.db.session.commit();g.pop('_login_user',None)
        self.assertEqual(self.client.get('/panel/users').status_code,200)
        self.assertEqual(self.client.post('/panel/api/reset/panel').status_code,403)
        self.assertEqual(self.client.get('/panel/api/backup/list').status_code,403)
        self.assertEqual(self.client.get('/panel/settings/security').status_code,200)

    def test_seller_only_sees_their_accounts(self):
        self.admin();admin=panel.Admin.query.first();admin.role='seller';self.user.owner_id=admin.id;panel.db.session.commit();g.pop('_login_user',None)
        result=self.client.get('/panel/api/users/search?batch=100').get_json()
        self.assertIn('customer-one',str(result));self.assertNotIn('customer-two',str(result))
        g.pop('_login_user',None)
        self.assertEqual(self.client.get('/panel/users/edit/'+str(self.other.id)).status_code,404)

    def test_totp_rfc_vector_and_setup_recovery(self):
        self.assertEqual(totp(base64.b32encode(b'12345678901234567890').decode(),1),'287082')
        self.admin();self.client.get('/panel/settings/security')
        with self.client.session_transaction() as session: secret=session['totp_setup']
        code=totp(secret,int(time.time()/30))
        response=self.client.post('/panel/settings/security',data={'action':'enable','current_password':'admin-test-password-123','code':code})
        self.assertEqual(response.status_code,200)
        admin=panel.Admin.query.first();self.assertNotIn(secret,admin.totp_secret)
        self.assertEqual(len(__import__('json').loads(admin.recovery_codes)),8)

    def test_service_restart_failures_are_not_reported_as_success(self):
        self.admin()
        with patch('app.subprocess.run',side_effect=__import__('subprocess').CalledProcessError(1,'systemctl')):
            self.assertFalse(self.client.post('/panel/api/vpn/restart').get_json()['success'])
        self.assertEqual(self.client.post('/panel/api/system/restart/ssh').status_code,503)

    def test_audit_redacts_password_changes(self):
        self.admin();admin=panel.Admin.query.first()
        response=self.client.post('/panel/settings/admins',data={'username':'new-manager','password':'New-secret-password-123','role':'viewer'})
        self.assertEqual(response.status_code,302)
        rows=panel.security.Audit.query.all()
        self.assertTrue(rows)
        self.assertNotIn('New-secret-password-123',str([row.details for row in rows]))
