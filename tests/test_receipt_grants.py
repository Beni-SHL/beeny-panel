import hashlib,hmac,json,time,unittest
from datetime import datetime,timedelta
from unittest.mock import patch
import test_customer as fixture
panel=fixture.panel

class ReceiptGrantTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    configure=fixture.CustomerFlowTests.configure
    admin=fixture.CustomerFlowTests.admin

    def receipt(self):
        self.configure()
        return self.features.create_request(self.user,fixture.DEFAULT_PLANS[0]['id'],fixture.jpeg(),'Customer','contact')

    def callback(self,row,action='yes',chat=123456,signature_chat=None):
        expires=int(time.time())+3600
        value=f'{row.id}:{action}:{expires}:{signature_chat or chat}'
        signature=hmac.new(panel.app.secret_key.encode(),value.encode(),hashlib.sha256).hexdigest()[:24]
        return {'callback_query':{'id':'test-callback','from':{'id':chat,'is_bot':False},'message':{'chat':{'id':chat,'type':'private'}},'data':f'br:{row.id}:{action}:{expires}:{signature}'}}

    @patch.object(panel.experience,'sync_access',return_value=[])
    def test_gift_is_temporary_and_paid_approval_replaces_it_once(self,sync):
        row=self.receipt();grant=panel.db.session.get(self.features.ReceiptGrant,row.id)
        self.assertTrue(grant.active);self.assertEqual(self.user.traffic_limit,105)
        self.assertAlmostEqual((grant.expires_at-grant.created_at).total_seconds(),86400,delta=2)
        self.assertEqual(self.user.traffic_usage,25)
        with panel.app.test_request_context():panel.experience.approve_renewal(row)
        panel.db.session.refresh(grant)
        self.assertFalse(grant.active);self.assertEqual(grant.state,'approved')
        self.assertEqual(self.user.traffic_limit,200)
        self.assertEqual(self.user.expire_date,'2027-01-31')
        self.assertEqual(self.user.traffic_usage,25)
        with panel.app.test_request_context():
            from werkzeug.exceptions import Conflict
            with self.assertRaises(Conflict):panel.experience.approve_renewal(row)
        self.assertEqual(self.user.traffic_limit,200)

    def test_rejection_revokes_gift_without_resetting_consumption(self):
        row=self.receipt();self.user.traffic_usage=28;panel.db.session.commit()
        self.admin()
        with self.client.session_transaction() as session:csrf=session['_customer_csrf']
        response=self.client.post(f'/panel/renewals/{row.id}/review',data={'csrf':csrf,'action':'rejected'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.user.traffic_limit,105);self.assertEqual(self.user.traffic_usage,28)
        self.assertEqual(self.user.expire_date,'2027-01-01')
        self.assertFalse(panel.db.session.get(self.features.ReceiptGrant,row.id).active)

    def test_expiry_and_admin_edits_are_preserved(self):
        row=self.receipt();grant=panel.db.session.get(self.features.ReceiptGrant,row.id)
        self.user.traffic_limit=250;grant.expires_at=datetime.utcnow()-timedelta(seconds=1);panel.db.session.commit()
        self.features.expire_receipt_grants()
        self.assertEqual(self.user.traffic_limit,250);self.assertFalse(grant.active)
        self.features.expire_receipt_grants();self.assertEqual(self.user.traffic_limit,250)

    def test_exhausted_expired_account_gift_ends_at_five_gb(self):
        self.user.traffic_limit=10;self.user.traffic_usage=12.3;self.user.expire_date='2020-01-01';panel.db.session.commit()
        row=self.receipt();grant=panel.db.session.get(self.features.ReceiptGrant,row.id)
        self.assertTrue(grant.temporary_only);self.assertEqual(self.user.traffic_limit,18)
        self.user.traffic_usage=17.3;panel.db.session.commit();self.features.expire_receipt_grants()
        self.assertFalse(grant.active);self.assertEqual(self.user.traffic_limit,18)
        self.assertEqual(self.user.expire_date,'2020-01-01');self.assertEqual(self.user.traffic_usage,17.3)

    def test_disabled_paused_and_unlimited_accounts_are_not_overridden(self):
        self.user.status='disabled';panel.db.session.commit();row=self.receipt()
        self.assertIsNone(panel.db.session.get(self.features.ReceiptGrant,row.id))
        self.assertEqual(self.user.status,'disabled')
        # No legacy disabled account is reactivated to obtain a grant.
        self.assertEqual(self.user.traffic_limit,100)

    def test_cooldown_claim_is_not_reset_by_rejection(self):
        row=self.receipt();self.features.finish_receipt_grant(row,'rejected');row.status='rejected';panel.db.session.commit()
        # A fresh valid receipt with different pixels may be submitted, but not a second gift.
        import io
        from PIL import Image
        output=io.BytesIO();Image.new('RGB',(120,80),'blue').save(output,'JPEG')
        another=self.features.create_request(self.user,fixture.DEFAULT_PLANS[0]['id'],output.getvalue(),'Customer','contact')
        self.assertIsNone(panel.db.session.get(self.features.ReceiptGrant,another.id))

    @patch('customer_features.requests.post')
    @patch.object(panel.experience,'sync_access',return_value=[])
    def test_signed_telegram_approval_is_scoped_and_idempotent(self,sync,post):
        post.return_value.status_code=200
        post.return_value.json.return_value={'ok':True,'result':True}
        row=self.receipt()
        self.features.process_update(self.callback(row,chat=999,signature_chat=123456))
        self.assertEqual(row.status,'pending')
        self.features.process_update(self.callback(row,'ask'))
        self.assertEqual(row.status,'pending')
        self.features.process_update(self.callback(row,'yes'))
        self.assertEqual(row.status,'completed');self.assertEqual(self.user.traffic_limit,200)
        self.features.process_update(self.callback(row,'yes'))
        self.assertEqual(self.user.traffic_limit,200)
        self.assertEqual(panel.security.Audit.query.filter_by(action='renewal.approve.telegram').count(),1)

    @patch('customer_features.requests.post')
    def test_receipt_notification_has_private_admin_review_button(self,post):
        post.return_value.status_code=200
        post.return_value.json.return_value={'ok':True,'result':True}
        row=self.receipt()
        self.features.deliver_notifications()
        sends=[call for call in post.call_args_list if 'sendDocument' in call.args[0]]
        self.assertTrue(sends)
        data=sends[0].kwargs['data']
        keyboard=json.loads(data['reply_markup'])
        self.assertTrue(keyboard['inline_keyboard'][0][0]['callback_data'].startswith(f'br:{row.id}:ask:'))

    def test_automatic_block_can_receive_grace_but_admin_disable_cannot(self):
        self.user.status='disabled';self.user.disable_reason='automatic'
        self.user.traffic_limit=10;self.user.traffic_usage=12;panel.db.session.commit()
        row=self.receipt()
        self.assertEqual(self.user.status,'active')
        self.assertIsNotNone(panel.db.session.get(self.features.ReceiptGrant,row.id))
        self.features.finish_receipt_grant(row,'rejected');panel.db.session.commit()
        self.assertEqual(self.user.status,'active');self.assertEqual(self.user.traffic_limit,17)
        self.assertEqual(self.user.expire_date,'2027-01-01')
        self.user.status='disabled';panel.db.session.commit()
        self.assertEqual(self.user.disable_reason,'admin')

    def test_existing_disabled_cause_remains_ambiguous_after_additive_migration(self):
        from sqlalchemy import text
        from migrations import upgrade
        panel.db.session.remove();panel.db.drop_all()
        with panel.db.engine.begin() as connection:
            connection.execute(text('CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT, status TEXT, traffic_limit INTEGER, traffic_usage FLOAT)'))
            connection.execute(text("INSERT INTO user VALUES (1,'legacy-disabled','disabled',100,25)"))
        upgrade(panel.db)
        row=panel.db.session.execute(text('SELECT status,disable_reason,traffic_limit,traffic_usage FROM user WHERE id=1')).one()
        self.assertEqual(tuple(row),('disabled','legacy',100,25))

    def test_day_is_added_and_first_connection_conversion_removes_only_gift_day(self):
        self.user.expire_date='30';panel.db.session.commit()
        row=self.receipt()
        self.assertEqual(self.user.expire_date,'31')
        self.user.expire_date='2027-03-31'
        self.features.receipt_counter_started(self.user,'31','2027-03-31');panel.db.session.commit()
        self.features.finish_receipt_grant(row,'rejected');panel.db.session.commit()
        self.assertEqual(self.user.expire_date,'2027-03-30')
        self.assertEqual(self.user.traffic_limit,105)
        self.assertEqual(self.user.traffic_usage,25)
