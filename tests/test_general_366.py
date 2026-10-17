import unittest
from unittest.mock import patch
from werkzeug.security import check_password_hash
import test_customer as fixture
from test_customer import panel
class GeneralSettingsTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_credentials_keep_login_path_and_do_not_restart(self):
        self.admin()
        password='  new-password-with-spaces  '
        with patch('app.privileged_call') as helper, patch('privileged_server.dispatch') as dispatch:
            response=self.client.post('/panel/api/panel/settings',json={'username':'admin','password':password,'current_password':'admin-test-password-123','panel_path':'/panel'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['success'])
        self.assertEqual(response.json['redirect'],'/panel/login')
        self.assertFalse(response.json['restarting'])
        helper.assert_not_called();dispatch.assert_not_called()
        self.assertTrue(check_password_hash(panel.Admin.query.first().password,password))
    def test_general_renders_real_security_links(self):
        self.admin()
        response=self.client.get('/panel/settings/general')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'/panel/settings/admins',response.data)
        self.assertNotIn(b'reloadConfig()',response.data)

    def test_catalog_editor_rejects_stale_save_and_creates_plan(self):
        import re
        self.admin()
        response=self.client.get('/panel/settings/plans/new')
        self.assertEqual(response.status_code,200)
        version=re.search(rb'name="version" value="([a-f0-9]+)"',response.data).group(1).decode()
        data=dict(version=version,title='Test plan',days='30',quota='100',devices='1',price='200000',original_price='0',quota_mode='metered',throttle_down_kbps='2000',throttle_up_kbps='2000')
        with self.client.session_transaction() as session:data['csrf']=session['_customer_csrf']
        result=self.client.post('/panel/settings/plans/new',data=data)
        self.assertEqual(result.status_code,200,result.data)
        self.assertTrue(result.json['success'])
        self.assertEqual(self.client.post('/panel/settings/plans/new',data=data).status_code,409)

    def test_settings_pages_render_without_external_font_imports(self):
        self.admin()
        for name in ('nodes','general','ssl','system','backup','openvpn'):
            response=self.client.get('/panel/settings/'+name)
            self.assertEqual(response.status_code,200,name)
            self.assertNotIn(b'fonts.googleapis.com',response.data,name)

    def test_node_list_does_not_probe_network(self):
        self.admin()
        with patch('app.requests.get') as probe:
            response=self.client.get('/panel/settings/nodes')
        self.assertEqual(response.status_code,200)
        probe.assert_not_called()

    def test_admin_language_persists_and_does_not_translate_usernames(self):
        self.admin()
        admin=panel.Admin.query.first();admin.username='Settings';panel.db.session.commit()
        result=self.client.post('/panel/api/admin/language',data={'language':'fa'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(panel.Admin.query.first().language,'fa')
        response=self.client.get('/panel/settings/general')
        self.assertIn('تنظیمات عمومی'.encode(),response.data)
        self.assertIn(b'dir="rtl"',response.data)
        self.assertIn(b'value="Settings"',response.data)
        self.assertEqual(self.client.post('/panel/api/admin/language',data={'language':'xx'}).status_code,400)

    def test_payment_settings_ajax_preserves_catalog_and_reports_errors(self):
        self.admin()
        features=panel.customer_features
        import json
        plans=features.settings()['plans']
        plans[0]['price']=345678
        raw=json.dumps(plans,ensure_ascii=False)
        features.set_setting('plans',raw);panel.db.session.commit()
        with self.client.session_transaction() as session:csrf=session['_customer_csrf']
        headers={'X-Requested-With':'XMLHttpRequest'}
        response=self.client.post('/panel/settings/customer',data={'csrf':csrf},headers=headers)
        self.assertEqual(response.status_code,200,response.data)
        self.assertTrue(response.json['success'])
        self.assertEqual(features.get_setting('plans'),raw)
        response=self.client.post('/panel/settings/customer',data={'csrf':csrf,'smtp_port':'not-a-port'},headers=headers)
        self.assertEqual(response.status_code,400)
        self.assertFalse(response.json['success'])
        self.assertEqual(features.get_setting('plans'),raw)
