import hashlib
import io
import json
import unittest
from unittest.mock import patch
from flask import g
from werkzeug.security import generate_password_hash
import test_customer as fixture
from test_customer import panel, jpeg
from pricing import quote

# Use the established isolated DB fixture without re-running inherited tests.
class ReleaseTests(unittest.TestCase):
    setUp = fixture.CustomerFlowTests.setUp
    tearDown = fixture.CustomerFlowTests.tearDown
    csrf = fixture.CustomerFlowTests.csrf
    admin = fixture.CustomerFlowTests.admin
    configure = fixture.CustomerFlowTests.configure

    def test_clear_customer_is_private_and_new_events_remain(self):
        csrf=self.csrf()
        panel.experience.notify(self.user.id,'Mine','Private')
        panel.experience.notify(self.other.id,'Other','Private');panel.db.session.commit()
        url='/panel/c/'+self.token+'/notifications'
        latest=self.client.get(url).json['latest_id']
        self.assertEqual(self.client.post(url+'/clear',data={'csrf':csrf,'upto':latest}).status_code,200)
        self.assertEqual(self.client.get(url).json['items'],[])
        self.assertEqual(panel.experience.Notification.query.filter_by(user_id=self.other.id,cleared_at=None).count(),1)
        panel.experience.notify(self.user.id,'New','After clear');panel.db.session.commit()
        self.assertEqual(self.client.get(url).json['unread'],1)
        self.client.post('/panel/c/'+self.token+'/logout',data={'csrf':csrf})
        self.assertEqual(self.client.post(url+'/clear',data={'csrf':csrf,'upto':999999}).status_code,302)

    def test_admin_clear_is_per_admin(self):
        self.admin();self.client.get('/panel/sessions')
        with self.client.session_transaction() as session: csrf=session['_customer_csrf']
        latest=self.client.get('/panel/notifications').json['latest_id']
        self.assertEqual(self.client.post('/panel/notifications/clear',data={'csrf':csrf,'upto':latest}).status_code,200)
        self.assertEqual(self.client.get('/panel/notifications').json['items'],[])
        panel.db.session.add(panel.Admin(username='admin-two',password=generate_password_hash('another-password-123')));panel.db.session.commit()
        client=panel.app.test_client();g.pop('_login_user',None)
        client.get('/panel/login')
        with client.session_transaction() as session: csrf=session['_customer_csrf']
        client.post('/panel/login',data={'csrf':csrf,'username':'admin-two','password':'another-password-123'});g.pop('_login_user',None)
        self.assertGreater(len(client.get('/panel/notifications').json['items']),0)

    def test_admin_session_revoke_invalidates_remember_and_all_devices(self):
        admin=panel.Admin.query.first();admin.password=generate_password_hash('admin-test-password-123');panel.db.session.commit()
        first,second=panel.app.test_client(),panel.app.test_client()
        for client in (first,second):
            g.pop('_login_user',None)
            client.get('/panel/login')
            with client.session_transaction() as session: csrf=session['_customer_csrf']
            self.assertEqual(client.post('/panel/login',data={'csrf':csrf,'username':'admin','password':'admin-test-password-123','remember':'1'}).status_code,302)
        g.pop('_login_user',None);self.assertEqual(first.get('/panel/sessions').status_code,200)
        with first.session_transaction() as session: csrf=session['_customer_csrf']
        with second.session_transaction() as session: identity=session['_user_id']
        target=hashlib.sha256(identity.split(':')[1].encode()).hexdigest()
        g.pop('_login_user',None);self.assertEqual(first.post('/panel/sessions/revoke',data={'csrf':csrf,'session_id':target}).status_code,302)
        for cookie_only in (False,True):
            if cookie_only: second.delete_cookie('session')
            g.pop('_login_user',None);self.assertEqual(second.get('/panel/sessions').status_code,302)
        g.pop('_login_user',None);self.assertTrue(first.post('/panel/api/logout/all',data={'csrf':csrf}).json['success'])
        first.delete_cookie('session');g.pop('_login_user',None);self.assertEqual(first.get('/panel/sessions').status_code,302)
        self.csrf();g.pop('_login_user',None);self.assertEqual(self.client.get('/panel/sessions').status_code,302)

    def test_custom_request_server_price_snapshot_and_approval(self):
        self.configure();policy=dict(enabled=True,base=10000,per_gb=1000,per_day=2000,per_device=40000)
        self.features.set_setting('custom_pricing',json.dumps(policy));panel.db.session.commit();csrf=self.csrf()
        self.client.post('/panel/c/'+self.token+'/renew',data=dict(csrf=csrf,plan_id='custom',custom_days='30',custom_quota='100',custom_devices='2',price='1',name='Customer',contact='Phone',receipt=(io.BytesIO(jpeg()),'receipt.jpg')))
        row=self.features.RenewalRequest.query.one();self.assertEqual(json.loads(row.plan)['price'],210000)
        policy['per_gb']=9999;self.features.set_setting('custom_pricing',json.dumps(policy));panel.db.session.commit()
        self.assertEqual(json.loads(row.plan)['price'],210000)
        with patch('app.sync_primary_access'): panel.experience.approve_renewal(row)
        self.assertEqual(self.user.traffic_limit,200)

    def test_quote_rejects_invalid_or_disabled_values(self):
        policy=dict(enabled=True,base=1,per_gb=2,per_day=3,per_device=4)
        self.assertEqual(quote(policy,30,100,2)['price'],295)
        for values in [('0','100','1'),('30','-1','1'),('30','100','101'),('30.5','100','1')]:
            with self.assertRaises(ValueError): quote(policy,*values)
        policy['enabled']=False
        with self.assertRaises(ValueError): quote(policy,30,100,1)

    def test_primary_pause_verifies_disconnect_and_retries_failure(self):
        node=panel.Node(name='Primary',ip='127.0.0.1',api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit();csrf=self.csrf()
        with patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',return_value=[dict(id='7',fingerprint='f'*64)]),patch('vpn_sessions.disconnect_session') as kill:
            self.client.post('/panel/c/'+self.token+'/pause',data={'csrf':csrf,'paused':'1'})
            kill.assert_called_once_with(self.user.username,'7','f'*64)
            self.assertTrue(self.user.customer_paused);self.assertFalse(self.user.pause_sync_pending)
        with patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',side_effect=OSError('Unavailable')):
            self.client.post('/panel/c/'+self.token+'/pause',data={'csrf':csrf,'paused':'1'})
            self.assertTrue(self.user.pause_sync_pending)
        with patch('app.sync_primary_access'):
            self.client.post('/panel/c/'+self.token+'/pause',data={'csrf':csrf,'paused':'0'})
            self.assertFalse(self.user.customer_paused)

    def test_uploaded_avatar_is_webp_and_receipts_stay_jpeg(self):
        csrf=self.csrf()
        self.client.post('/panel/c/'+self.token+'/avatar',data={'csrf':csrf,'avatar':(io.BytesIO(jpeg()),'photo.jpg')})
        profile=panel.db.session.get(self.features.CustomerProfile,self.user.id)
        self.assertTrue(profile.avatar.endswith('.webp'))
        response=self.client.get('/panel/c/'+self.token+'/avatar')
        self.assertEqual(response.content_type,'image/webp')
        self.assertTrue(response.data.startswith(b'RIFF'))
