"""Integration checks for private customer access, payments and bot linking."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch, Mock
from PIL import Image
from flask import g
from werkzeug.security import generate_password_hash

TEMP = tempfile.TemporaryDirectory()
os.environ['BEENY_SECRET_KEY'] = 'integration-test-secret-not-for-deployment'
os.environ['BEENY_INSTANCE_PATH'] = TEMP.name
os.environ['BEENY_DATABASE_URI'] = 'sqlite:///'+TEMP.name+'/customer-tests.db'
os.environ['BEENY_CONFIG_FILE'] = TEMP.name+'/config.json'
os.environ['BEENY_PUBLIC_HOST'] = 'vpn.example.com'
os.environ['BEENY_PANEL_BASE_URL'] = 'https://panel.example.com'
Path(os.environ['BEENY_CONFIG_FILE']).write_text(json.dumps({'panel_path': '/panel'}))
import app as panel
from customer_features import clean_image, DEFAULT_PLANS


def jpeg():
    output = io.BytesIO()
    Image.new('RGB', (120, 80), '#aa88dd').save(output, 'JPEG')
    return output.getvalue()


class CustomerFlowTests(unittest.TestCase):
    def setUp(self):
        self.context = panel.app.app_context()
        self.context.push()
        panel.db.drop_all()
        panel.db.create_all()
        self.user = panel.User(username='customer-one', traffic_limit=100, traffic_usage=25,
                               expire_date='2027-01-01', max_devices=2, status='active')
        self.other = panel.User(username='customer-two', traffic_limit=10, traffic_usage=1, status='active')
        panel.db.session.add_all([self.user, self.other])
        panel.db.session.flush()
        self.token = 'A'*43
        panel.db.session.add(panel.AccountLink(user_id=self.user.id, token_hash=hashlib.sha256(self.token.encode()).hexdigest()))
        panel.db.session.add(panel.Admin(username='admin', password='unused'))
        panel.db.session.commit()
        self.client = panel.app.test_client()
        self.features = panel.customer_features
        self.features.save_secrets({})
        panel.db.session.add(self.features.CustomerProfile(user_id=self.user.id, login_username="customer-one", password_hash=generate_password_hash("customer-password-123"), auth_version="test-version"))
        panel.db.session.commit()

    def test_additive_upgrade_preserves_legacy_account_and_is_idempotent(self):
        from sqlalchemy import text, inspect
        from migrations import upgrade
        panel.db.session.remove()
        panel.db.drop_all()
        with panel.db.engine.begin() as conn:
            conn.execute(text('CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(100))'))
            conn.execute(text("INSERT INTO user VALUES (7, 'legacy-account')"))
            conn.execute(text('CREATE TABLE customer_profiles (user_id INTEGER PRIMARY KEY, avatar VARCHAR(80))'))
            conn.execute(text("INSERT INTO customer_profiles VALUES (7, 'existing-avatar.jpg')"))
        upgrade(panel.db)
        upgrade(panel.db)
        self.assertEqual(panel.db.session.get(panel.User, 7).username, 'legacy-account')
        self.assertEqual(panel.db.session.get(self.features.CustomerProfile, 7).avatar, 'existing-avatar.jpg')
        self.assertIsNone(panel.db.session.get(self.features.CustomerProfile, 7).password_hash)
        self.assertIn('renewal_requests', inspect(panel.db.engine).get_table_names())

    def test_session_routes_require_customer_login_and_reject_cross_node(self):
        self.assertEqual(self.client.get('/panel/c/'+self.token+'/sessions').status_code, 302)
        csrf = self.csrf()
        node = panel.Node(name='Primary', ip='127.0.0.1', api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node)
        panel.db.session.flush()
        panel.db.session.add(panel.UserNode(user_id=self.user.id, node_id=node.id))
        panel.db.session.commit()
        with patch('vpn_sessions.local_sessions', return_value=[]) as listing:
            response = self.client.get('/panel/c/'+self.token+'/sessions')
            self.assertEqual(response.status_code, 200)
            listing.assert_called_once_with(self.user.username)
        with patch('vpn_sessions.disconnect_session') as terminate:
            response = self.client.post('/panel/c/'+self.token+'/sessions', data=dict(csrf=csrf, node=999, id='1', fingerprint='a'*64))
            self.assertEqual(response.status_code, 404)
            terminate.assert_not_called()
            response = self.client.post('/panel/c/'+self.token+'/sessions', data=dict(csrf=csrf, node=node.id, id='1', fingerprint='a'*64))
            self.assertEqual(response.status_code, 302)
            terminate.assert_called_once_with(self.user.username, '1', 'a'*64)

    def test_account_suspend_preserves_data_and_reports_unconfirmed_remote_node(self):
        csrf=self.csrf()
        self.assertEqual(self.client.post('/panel/users/view/'+str(self.user.id)+'/suspend', data=dict(csrf=csrf)).status_code, 302)
        self.admin()
        local=panel.Node(name='Primary',ip='127.0.0.1',api_key=panel.PRIMARY_NODE_KEY)
        remote=panel.Node(name='Remote node',ip='192.0.2.10',api_key='test-key')
        panel.db.session.add_all([local,remote]);panel.db.session.flush()
        panel.db.session.add_all([panel.UserNode(user_id=self.user.id,node_id=n.id) for n in (local,remote)])
        panel.db.session.commit()
        with patch('app.sync_primary_access') as apply, patch('vpn_sessions.local_sessions',return_value=[]), patch('cluster.set_user_state_on_node', return_value=(False,'Unavailable')) as remote_apply:
            response=self.client.post('/panel/users/view/'+str(self.user.id)+'/suspend',data=dict(csrf=csrf))
            self.assertEqual(response.status_code,302)
            self.assertEqual(self.user.status,'disabled')
            self.assertEqual(self.user.traffic_usage,25)
            apply.assert_called_once_with(self.user,False)
            remote_apply.assert_called_once_with(remote,self.user.username,False)
            with self.client.session_transaction() as session:
                self.assertIn('Remote node',session['_flashes'][-1][1])

    @patch('customer_features.requests.post')
    def test_bot_usage_config_and_receipt_workflow(self, post):
        self.configure()
        post.return_value=Mock(status_code=200)
        post.return_value.json.return_value={'ok':True,'result':{}}
        link=panel.db.session.get(panel.AccountLink,self.user.id)
        binding=self.features.TelegramAccount(chat_id=123,user_id=self.user.id,link_hash=link.token_hash)
        panel.db.session.add(binding);panel.db.session.commit()
        def event(text=None,photo=None):
            message=dict(chat=dict(id=123,type='private'),**{'from':dict(id=123,first_name='Customer')})
            if text is not None:message['text']=text
            if photo:message['photo']=photo
            return dict(message=message)
        self.features.process_update(event('/account'))
        self.assertIn('75.00 GB',post.call_args.kwargs['data']['text'])
        with patch('builtins.open', side_effect=FileNotFoundError):
            self.features.process_update(event('/config'))
        self.assertIn('کانفیگ در دسترس نیست',post.call_args.kwargs['data']['text'])
        node=panel.Node(name='Primary',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node);panel.db.session.flush()
        panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        original_open=open
        def certificates(path,*args,**kwargs):
            return io.StringIO('test-certificate-material') if str(path).startswith('/etc/openvpn/') else original_open(path,*args,**kwargs)
        with patch('builtins.open', side_effect=certificates):
            self.features.process_update(event('/config'))
        document=post.call_args.kwargs['files']['document']
        self.assertEqual(document[0],'customer-one.ovpn')
        self.assertIn(b'remote vpn.example.com',document[1])
        self.features.process_update(event('/renew'))
        self.features.process_update(event('۲'))
        self.assertEqual(binding.selected_plan,'duo')
        post.return_value.json.return_value={'ok':True,'result':dict(file_path='photos/receipt.jpg')}
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=None)
        response.iter_content.return_value=[jpeg()]
        with patch('customer_features.requests.get',return_value=response):
            self.features.process_update(event(photo=[dict(file_id='photo',file_size=1024)]))
        row=self.features.RenewalRequest.query.one()
        self.assertEqual(row.source,'telegram')
        self.assertEqual(json.loads(row.plan)['price'],340000)
        self.assertEqual(row.status,'pending')

    def test_legacy_first_snapshot_does_not_double_count_old_account_usage(self):
        from test_traffic import SNAPSHOT
        from unittest.mock import mock_open
        node=panel.Node(name='Main',ip='185.208.172.91',api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node);panel.db.session.flush()
        panel.db.session.add(panel.TrafficBaseline(node_id=node.id,pending=True))
        self.user.username='alice'
        self.user.traffic_used=25*1073741824
        self.user.traffic_usage=25
        panel.db.session.commit()
        with patch('builtins.open',mock_open(read_data=SNAPSHOT)):
            panel.update_openvpn_status()
        self.assertEqual(self.user.traffic_usage,25)
        self.assertEqual(panel.TrafficDaily.query.count(),0)
        self.assertFalse(panel.db.session.get(panel.TrafficBaseline,node.id).pending)
        newer=SNAPSHOT.replace('1048576,2097152','2097152,2097152')
        with patch('builtins.open',mock_open(read_data=newer)):
            panel.update_openvpn_status()
        self.assertEqual(self.user.traffic_used,25*1073741824+1048576)
        self.assertEqual(panel.TrafficDaily.query.one().bytes_total,1048576)

    def tearDown(self):
        panel.db.session.remove()
        self.context.pop()

    def csrf(self):
        self.client.get('/panel/c/'+self.token+'/login')
        with self.client.session_transaction() as session:
            token = session['_customer_csrf']
        self.client.post('/panel/c/'+self.token+'/login',data={'csrf':token,'username':'customer-one','password':'customer-password-123'})
        return token

    def configure(self):
        for key,value in {'card_number':'1234567812345678','bank_name':'Bank','card_holder':'Holder',
                          'admin_chat_id':'123456','bot_username':'TestBot', 'admin_email':'admin@example.com',
                          'smtp_host':'smtp.example.com','smtp_from':'sender@example.com'}.items():
            self.features.set_setting(key,value)
        self.features.save_secrets({'bot_token':'123456:TEST_TOKEN_PLACEHOLDER_123456'})
        panel.db.session.commit()

    def admin(self):
        g.pop('_login_user',None)
        with self.client.session_transaction() as session:
            session['_user_id'] = '1'
            session['_fresh'] = True

    def test_portal_isolation_and_csrf(self):
        self.assertEqual(self.client.get('/panel/c/'+self.token).status_code,302)
        self.assertEqual(self.client.get('/panel/c/'+self.token+'/download').status_code,302)
        self.csrf()
        response = self.client.get('/panel/c/'+self.token)
        self.assertEqual(response.status_code,200)
        self.assertIn('حجم باقی‌مانده'.encode(),response.data)
        self.assertIn(b'75.00',response.data)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(self.client.get('/panel/c/'+'B'*43).status_code,404)
        self.assertEqual(self.client.get('/panel/settings/customer').status_code,302)
        self.assertEqual(self.client.get('/panel/renewals/1/receipt').status_code,302)
        self.assertEqual(self.client.post('/panel/c/'+self.token+'/renew').status_code,400)

    def test_receipt_server_price_snapshot_pending_limit(self):
        self.configure()
        csrf = self.csrf()
        fields=dict(csrf=csrf,plan_id='monthly',price='1',name='Customer',contact='0999999999')
        response=self.client.post('/panel/c/'+self.token+'/renew',data={**fields,'receipt':(io.BytesIO(jpeg()),'evil.php')})
        self.assertEqual(response.status_code,302)
        row=self.features.RenewalRequest.query.one()
        self.assertEqual(json.loads(row.plan)['price'],250000)
        self.assertTrue(row.receipt.endswith('.jpg'))
        self.assertEqual(self.client.get('/panel/renewals/'+str(row.id)+'/receipt').status_code,302)
        self.client.post('/panel/c/'+self.token+'/renew',data={**fields,'receipt':(io.BytesIO(jpeg()),'receipt.jpg')})
        self.assertEqual(self.features.RenewalRequest.query.count(),1)
        self.features.set_setting('plans',json.dumps([{**p,'price':123} for p in DEFAULT_PLANS]))
        panel.db.session.commit()
        self.assertEqual(json.loads(row.plan)['price'],250000)
        self.admin()
        self.assertEqual(self.client.get('/panel/renewals?status=all').status_code,200)
        self.assertEqual(self.client.get('/panel/renewals/'+str(row.id)+'/receipt').status_code,200)

    def test_avatar_validation_and_private_storage(self):
        csrf=self.csrf()
        response=self.client.post('/panel/c/'+self.token+'/avatar',data={'csrf':csrf,'avatar':(io.BytesIO(b'<svg/>'),'a.svg')})
        self.assertEqual(response.status_code,302)
        self.assertIsNone(self.features.CustomerProfile.query.first().avatar)
        self.client.post('/panel/c/'+self.token+'/avatar',data={'csrf':csrf,'avatar':(io.BytesIO(jpeg()),'a.jpg')})
        profile=self.features.CustomerProfile.query.one()
        avatar=Path(TEMP.name)/'customer_uploads'/profile.avatar
        self.assertEqual(avatar.stat().st_mode & 0o777,0o600)
        with Image.open(avatar) as image:
            self.assertEqual(image.size,(320,320))
        self.assertEqual(self.client.get('/panel/c/'+self.token+'/avatar').status_code,200)
        self.assertEqual(self.client.get('/panel/c/'+'B'*43+'/avatar').status_code,404)

    @patch('customer_features.requests.post')
    def test_bot_pair_one_time_signed_link_revocation(self,post):
        self.configure()
        post.return_value=Mock(status_code=200)
        post.return_value.json.return_value={'ok':True,'result':{}}
        response=self.client.post('/panel/c/'+self.token+'/telegram',data={'csrf':self.csrf()})
        self.assertEqual(response.status_code,302)
        code=response.location.split('start=')[1]
        def event(chat,text):
            return {'message':{'chat':{'type':'private','id':chat},'from':{'id':chat},'text':text}}
        self.features.process_update(event(111,'/start '+code))
        self.assertEqual(self.features.TelegramAccount.query.one().user_id,self.user.id)
        self.features.process_update(event(222,'/start '+code))
        self.assertEqual(self.features.TelegramAccount.query.count(),1)
        self.features.process_update(event(111,'/profile'))
        signed=post.call_args.kwargs['data']['text'].split('/c/')[1]
        self.assertEqual(self.client.get('/panel/c/'+signed).status_code,200)
        link=panel.db.session.get(panel.AccountLink,self.user.id)
        link.token_hash='c'*64
        panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/c/'+signed).status_code,404)
        self.features.process_update(event(111,'/account'))
        self.assertEqual(self.features.TelegramAccount.query.count(),0)

    @patch('customer_features.smtplib.SMTP_SSL')
    @patch('customer_features.requests.post')
    def test_notification_retry_does_not_resend_delivered_channel(self,post,smtp):
        self.configure()
        smtp.return_value.__enter__.return_value.send_message.return_value=None
        post.return_value=Mock(status_code=500)
        row=self.features.create_request(self.user,'monthly',jpeg(),'Name','Phone')
        self.features.deliver_notifications()
        self.assertEqual(row.email_state,'sent')
        self.assertEqual(row.telegram_state,'failed')
        self.assertEqual(smtp.call_count,1)
        row.next_attempt=panel.datetime.utcnow()
        post.return_value.status_code=200
        post.return_value.json.return_value={'ok':True,'result':{}}
        panel.db.session.commit()
        self.features.deliver_notifications()
        self.assertEqual(row.telegram_state,'sent')
        self.assertEqual(smtp.call_count,1)

    def test_admin_settings_auth_and_secret_not_echoed(self):
        self.assertEqual(self.client.get('/panel/settings/customer').status_code,302)
        self.configure()
        self.admin()
        response=self.client.get('/panel/settings/customer')
        self.assertEqual(response.status_code,200)
        self.assertNotIn(b'TEST_TOKEN_PLACEHOLDER',response.data)
        self.assertEqual(self.client.post('/panel/settings/customer').status_code,400)

    def test_customer_login_never_authenticates_as_admin_and_logout_locks_files(self):
        csrf=self.csrf()
        self.assertEqual(self.client.get('/panel/settings/customer').status_code,302)
        with self.client.session_transaction() as session:
            self.assertNotIn('_user_id',session)
        self.client.post('/panel/c/'+self.token+'/logout',data={'csrf':csrf})
        self.assertEqual(self.client.get('/panel/c/'+self.token+'/download').status_code,302)
        response=self.client.post('/panel/c/'+self.token+'/login',data={'csrf':csrf,'username':'customer-one','password':'bad'})
        self.assertEqual(response.status_code,401)
        profile=panel.db.session.get(self.features.CustomerProfile,self.user.id)
        profile.password_hash=None
        panel.db.session.commit()
        response=self.client.get('/panel/c/'+self.token+'/login')
        self.assertIn('هنوز توسط مدیر'.encode(),response.data)
        self.assertNotIn(b'customer-one',response.data)

    def test_password_change_revokes_existing_customer_session(self):
        self.csrf()
        profile=panel.db.session.get(self.features.CustomerProfile,self.user.id)
        profile.auth_version='new-version'
        panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/c/'+self.token).status_code,302)

    def test_delete_detaches_receipts_and_bot_data(self):
        self.configure()
        row=self.features.create_request(self.user,'monthly',jpeg())
        self.features.delete_customer(self.user.id)
        panel.db.session.commit()
        self.assertEqual(row.user_id,-self.user.id)
        self.assertEqual(self.features.RenewalRequest.query.filter_by(user_id=self.user.id).count(),0)

if __name__ == '__main__':
    unittest.main()
