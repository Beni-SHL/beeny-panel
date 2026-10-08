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
from werkzeug.security import generate_password_hash, check_password_hash

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
    def test_create_account_with_optional_customer_password(self):
        node = panel.Node(name='Primary', ip='127.0.0.1', api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node)
        panel.db.session.commit()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(panel.Admin.query.first().id)
            session['_fresh'] = True
        fields = dict(username='new-customer', protocol='openvpn', max_devices='1',
                      traffic_limit='100', nodes=str(node.id), portal_password='Secure-password-12345')
        with patch('app.subprocess.run'), patch('app.sync_primary_access'):
            response = self.client.post('/panel/users/add', data=fields)
        self.assertEqual(response.status_code, 302)
        user = panel.User.query.filter_by(username='new-customer').one()
        profile = panel.db.session.get(self.features.CustomerProfile, user.id)
        self.assertEqual(profile.login_username, 'new-customer')
        self.assertTrue(check_password_hash(profile.password_hash, fields['portal_password']))
        self.assertNotEqual(profile.password_hash, fields['portal_password'])
        self.assertTrue(profile.auth_version)

    def test_short_customer_password_rejected_before_certificate_creation(self):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(panel.Admin.query.first().id)
            session['_fresh'] = True
        with patch('app.subprocess.run') as certificate:
            response = self.client.post('/panel/users/add', data=dict(
                username='new-customer', protocol='openvpn', portal_password='short'))
        self.assertEqual(response.status_code, 400)
        certificate.assert_not_called()
        self.assertIsNone(panel.User.query.filter_by(username='new-customer').first())

    def test_larger_photo_is_cleaned_and_oversize_rejected(self):
        data = jpeg() + b'\0' * (8 * 1024 * 1024)
        self.assertLess(len(clean_image(data, avatar=True)), 100000)
        csrf = self.csrf()
        response = self.client.post('/panel/c/'+self.token+'/avatar', data={
            'csrf': csrf, 'avatar': (io.BytesIO(data), 'large-photo.jpg')})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.features.CustomerProfile.query.one().avatar)
        with self.assertRaises(ValueError):
            clean_image(b'\0' * (20 * 1024 * 1024 + 1))

    def test_avatar_choice_requires_login_csrf_and_valid_selection(self):
        url = '/panel/c/'+self.token+'/avatar/select'
        self.assertEqual(self.client.post(url, data={'avatar_choice':'7'}).status_code, 302)
        csrf = self.csrf()
        self.assertEqual(self.client.post(url, data={'avatar_choice':'7'}).status_code, 400)
        for bad in ('0', '21', '../7', 'abc', ''):
            self.assertEqual(self.client.post(url, data={'csrf':csrf,'avatar_choice':bad}).status_code, 400)
        self.assertEqual(self.client.post(url, data={'csrf':csrf,'avatar_choice':'7'}).status_code, 302)
        profile = self.features.CustomerProfile.query.one()
        self.assertEqual(profile.avatar_choice, 7)
        self.client.get('/panel/c/'+self.token)
        self.assertEqual(profile.avatar_choice, 7)
        self.assertEqual(self.client.post('/panel/c/'+'B'*43+'/avatar/select', data={'csrf':csrf,'avatar_choice':'8'}).status_code, 404)
        self.assertEqual(profile.avatar_choice, 7)

    def test_avatar_choice_replaces_photo_and_preserves_customer_credentials(self):
        csrf = self.csrf()
        self.client.post('/panel/c/'+self.token+'/avatar',data={'csrf':csrf,'avatar':(io.BytesIO(jpeg()),'a.jpg')})
        profile = self.features.CustomerProfile.query.one()
        old_file = Path(TEMP.name)/'customer_uploads'/profile.avatar
        password_hash, version = profile.password_hash, profile.auth_version
        self.assertTrue(old_file.exists())
        self.client.post('/panel/c/'+self.token+'/avatar/select',data={'csrf':csrf,'avatar_choice':'20'})
        self.assertIsNone(profile.avatar)
        self.assertFalse(old_file.exists())
        self.assertEqual(profile.avatar_choice, 20)
        self.assertEqual(profile.password_hash, password_hash)
        self.assertEqual(profile.auth_version, version)
        self.client.post('/panel/c/'+self.token+'/avatar',data={'csrf':csrf,'avatar':(io.BytesIO(jpeg()),'b.jpg')})
        self.assertTrue(profile.avatar)
        self.assertEqual(profile.avatar_choice, 20)

    def test_customer_pause_cannot_undo_admin_disable_expiry_or_quota(self):
        csrf = self.csrf()
        url = '/panel/c/'+self.token+'/pause'
        with patch('app.sync_primary_access'), patch('app.kick_user_globally'):
            self.assertEqual(self.client.post(url, data={'csrf':csrf,'paused':'1'}).status_code,302)
            self.assertTrue(self.user.customer_paused)
            self.assertEqual(self.user.status,'active')
            for status, expiry, usage in [('disabled','2027-01-01',25),('active','2020-01-01',25),('active','2027-01-01',100)]:
                self.user.status, self.user.expire_date, self.user.traffic_usage = status, expiry, usage
                panel.db.session.commit()
                self.client.post(url, data={'csrf':csrf,'paused':'0'})
                self.assertTrue(self.user.customer_paused)
            self.user.status,self.user.expire_date,self.user.traffic_usage='active','2027-01-01',25
            panel.db.session.commit()
            self.client.post(url, data={'csrf':csrf,'paused':'0'})
            self.assertFalse(self.user.customer_paused)
            self.assertEqual(self.user.status,'active')
        self.assertEqual(self.client.post(url,data={'paused':'1'}).status_code,400)

    def test_approval_applies_plan_once_and_retains_usage_and_personal_pause(self):
        self.configure()
        self.user.customer_paused=True
        panel.db.session.commit()
        row=self.features.create_request(self.user,DEFAULT_PLANS[0]['id'],jpeg(),'Customer','contact')
        # Plan identifiers are read from the saved defaults.
        self.admin()
        csrf=self.csrf()
        plan=json.loads(row.plan)
        from renewal import extend_expiry
        expiry=extend_expiry(self.user.expire_date,plan['days'])
        before=self.user.traffic_limit
        with patch('app.sync_primary_access'),patch('app.kick_user_globally'):
            response=self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'csrf':csrf,'action':'completed'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.user.traffic_limit,before+plan['quota'])
        self.assertEqual(self.user.expire_date,expiry)
        self.assertEqual(self.user.traffic_usage,25)
        self.assertTrue(self.user.customer_paused)
        self.assertEqual(row.status,'completed')
        self.assertEqual(self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'csrf':csrf,'action':'completed'}).status_code,409)
        self.assertEqual(self.user.traffic_limit,before+plan['quota'])
        self.assertTrue(panel.experience.Notification.query.filter_by(user_id=self.user.id,title='تمدید شما انجام شد').first())

    def test_notification_isolation_read_and_admin_feed(self):
        self.configure()
        row=self.features.create_request(self.user,DEFAULT_PLANS[0]['id'],jpeg(),'Customer','contact')
        csrf=self.csrf()
        panel.experience.notify(self.other.id,'PRIVATE-OTHER','SECRET-OTHER')
        panel.db.session.commit()
        url='/panel/c/'+self.token+'/notifications'
        response=self.client.get(url)
        data=response.get_json()
        self.assertGreater(data['unread'],0)
        self.assertNotIn('SECRET-OTHER',response.get_data(as_text=True))
        self.assertEqual(self.client.post(url+'/read',data={'upto':data['latest_id']}).status_code,400)
        self.assertEqual(self.client.post(url+'/read',data={'csrf':csrf,'upto':data['latest_id']}).status_code,200)
        self.assertEqual(self.client.get(url).get_json()['unread'],0)
        self.assertEqual(self.client.get('/panel/notifications').status_code,302)
        self.admin()
        feed=self.client.get('/panel/notifications').get_json()
        self.assertGreater(feed['unread'],0)
        self.client.post('/panel/notifications/read',data={'csrf':csrf,'upto':feed['latest_id']})
        self.assertEqual(self.client.get('/panel/notifications').get_json()['unread'],0)

    def test_request_delete_removes_receipt_and_stops_delivery(self):
        self.configure()
        row=self.features.create_request(self.user,DEFAULT_PLANS[0]['id'],jpeg(),'Customer','contact')
        filename=self.features.storage/row.receipt
        request_id=row.id
        url='/panel/renewals/'+str(request_id)+'/delete'
        self.assertEqual(self.client.post(url).status_code,302)
        csrf=self.csrf();self.admin()
        self.assertEqual(self.client.post(url).status_code,400)
        self.assertEqual(self.client.post(url,data={'csrf':csrf}).status_code,302)
        self.assertFalse(filename.exists())
        self.assertIsNone(panel.db.session.get(self.features.RenewalRequest,request_id))

    @patch('customer_features.requests.post')
    def test_multiple_admin_delivery_retries_only_failed_recipient(self,post):
        self.configure()
        self.features.set_setting('admin_chat_ids','222222,333333')
        panel.db.session.commit()
        row=self.features.create_request(self.user,DEFAULT_PLANS[0]['id'],jpeg(),'Customer','contact')
        row.email_state='sent';panel.db.session.commit()
        success=Mock(status_code=200);success.json.return_value={'ok':True,'result':{}}
        failure=Mock(status_code=500)
        post.side_effect=[success,failure,success]
        self.features.deliver_notifications()
        self.assertEqual(json.loads(row.telegram_sent_ids),['123456','333333'])
        row.next_attempt=__import__('datetime').datetime.utcnow();panel.db.session.commit()
        post.reset_mock();post.side_effect=None;post.return_value=success
        self.features.deliver_notifications()
        self.assertEqual(post.call_count,1)
        self.assertEqual(post.call_args.kwargs['data']['chat_id'],'222222')
        self.assertEqual(row.telegram_state,'sent')

    @patch('customer_features.requests.post')
    def test_customer_account_notifications_deliver_only_to_valid_binding(self,post):
        from datetime import datetime
        self.configure()
        self.features.TelegramAccount.query.delete()
        link=panel.db.session.get(panel.AccountLink,self.user.id)
        panel.db.session.add(self.features.TelegramAccount(chat_id=99999,user_id=self.user.id,link_hash=link.token_hash))
        panel.experience.notify(self.user.id,'Updated','Account renewed')
        panel.db.session.commit()
        response=Mock(status_code=200);response.json.return_value={'ok':True,'result':{}}
        post.return_value=response
        panel.experience.worker_cycle()
        self.assertTrue(post.called)
        for call in post.call_args_list:
            self.assertEqual(call.kwargs['data']['chat_id'],99999)
        post.reset_mock()
        panel.experience.worker_cycle()
        post.assert_not_called()

    def test_cards_discounts_and_recipient_settings_are_validated(self):
        self.admin()
        self.client.get('/panel/settings/customer')
        with self.client.session_transaction() as session:
            csrf=session['_customer_csrf']
        fields=dict(csrf=csrf,bank_name='Primary Bank',card_holder='Primary Holder',card_number='1234567812345678',
                    card_color='emerald',admin_chat_id='123456',admin_chat_ids='222222, 333333',
                    smtp_port='465',smtp_security='ssl',extra_bank_name='Blue Bank',extra_card_holder='Other Holder',
                    extra_card_number='1111222233334444',extra_card_color='blue')
        for plan in DEFAULT_PLANS:
            for key in ('title','days','devices','quota','price'):
                fields[plan['id']+'_'+key]=str(plan[key])
            fields[plan['id']+'_badge']='Sale'
            fields[plan['id']+'_original_price']=str(plan['price']+100000)
        response=self.client.post('/panel/settings/customer',data=fields)
        self.assertEqual(response.status_code,302)
        settings=self.features.settings()
        self.assertEqual(len(settings['bank_cards']),2)
        self.assertEqual(settings['bank_cards'][1]['number'],'1111222233334444')
        self.assertEqual(settings['plans'][0]['badge'],'Sale')
        self.assertEqual(settings['admin_chat_ids'],'222222,333333')
        fields['extra_card_number']='bad'
        self.client.post('/panel/settings/customer',data=fields)
        self.assertEqual(self.features.settings()['bank_cards'],settings['bank_cards'])
        self.csrf()
        self.assertEqual(self.client.get('/panel/c/'+self.token).status_code,200)

    def test_low_balance_warnings_deduplicate_and_renewal_starts_new_cycle(self):
        from datetime import date,timedelta
        self.user.traffic_usage=95
        self.user.expire_date=(date.today()+timedelta(days=2)).isoformat()
        panel.db.session.commit()
        panel.experience.worker_cycle(force_scan=True)
        query=panel.experience.Notification.query.filter_by(user_id=self.user.id)
        first=query.count()
        panel.experience.worker_cycle(force_scan=True)
        self.assertEqual(query.count(),first)
        self.user.traffic_usage=0
        panel.db.session.commit()
        self.user.traffic_usage=95
        panel.db.session.commit()
        before=query.count()
        panel.experience.worker_cycle(force_scan=True)
        self.assertGreater(query.count(),before)

    def test_user_search_alphabetical_order_and_batch_limit(self):
        self.admin()
        panel.db.session.add(panel.User(username='ALPHA',status='active'))
        panel.db.session.commit()
        data=self.client.get('/panel/api/users/search?sort=name_asc&per_page=100000').get_json()
        self.assertEqual(data['users'][0]['username'],'ALPHA')
        self.assertIn('customer_paused',data['users'][0])
        self.assertEqual(self.client.get('/panel/users').status_code,200)

    def test_pending_pause_retries_remote_and_reports_unconfirmed_node(self):
        csrf=self.csrf()
        node=panel.Node(name='Remote',ip='192.0.2.1:6200',api_key='fake')
        panel.db.session.add(node);panel.db.session.flush()
        panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        with patch('app.sync_primary_access'),patch('app.kick_user_globally'),patch('cluster.set_user_state_on_node',return_value=(False,'Unavailable')):
            self.client.post('/panel/c/'+self.token+'/pause',data={'csrf':csrf,'paused':'1'})
        self.assertTrue(self.user.customer_paused)
        self.assertTrue(self.user.pause_sync_pending)
        with patch('app.sync_primary_access'),patch('app.kick_user_globally'),patch('cluster.set_user_state_on_node',return_value=(True,'')) as state:
            panel.experience.worker_cycle(force_scan=True)
            self.assertEqual(state.call_args.args[-1],False)
        self.assertFalse(self.user.pause_sync_pending)

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
