import unittest,json,io
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel
class CommerceTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    configure=fixture.CustomerFlowTests.configure
    def submit_topup(self, ref='f'*32):
        self.configure()
        csrf=self.csrf()
        return self.client.post('/panel/c/'+self.token+'/wallet',data={
            'csrf':csrf,'action':'topup','reference':ref,'amount':'250000',
            'card_id':'primary','name':'Customer','contact':'09120000000',
            'receipt':(io.BytesIO(fixture.jpeg()),'receipt.jpg')})
    def test_receipt_topup_credits_once_after_approval_without_renewing_account(self):
        before=(self.user.expire_date,self.user.traffic_limit,self.user.traffic_usage,self.user.status)
        self.assertEqual(self.submit_topup().status_code,302)
        wallet=panel.db.session.get(panel.commerce.Wallet,self.user.id)
        self.assertEqual(wallet.balance,0)
        row=self.features.RenewalRequest.query.one()
        self.assertEqual(row.source,'wallet_topup')
        self.assertTrue((self.features.storage/row.receipt).is_file())
        self.assertEqual(self.submit_topup().status_code,302)
        self.assertEqual(self.features.RenewalRequest.query.count(),1)
        self.admin()
        with self.client.session_transaction() as session: admin_csrf=session['_customer_csrf']
        url='/panel/renewals/'+str(row.id)+'/review'
        self.assertEqual(self.client.post(url,data={'action':'completed','csrf':admin_csrf}).status_code,302)
        self.assertEqual(wallet.balance,250000)
        self.assertEqual(self.client.post(url,data={'action':'completed','csrf':admin_csrf}).status_code,409)
        self.assertEqual(wallet.balance,250000)
        self.assertEqual(panel.commerce.Entry.query.count(),1)
        self.assertEqual(panel.commerce.Invoice.query.count(),0)
        self.assertEqual((self.user.expire_date,self.user.traffic_limit,self.user.traffic_usage,self.user.status),before)
        self.assertEqual(row.status,'completed')
    def test_rejected_receipt_does_not_credit_wallet(self):
        self.submit_topup()
        row=self.features.RenewalRequest.query.one()
        self.admin()
        with self.client.session_transaction() as session: admin_csrf=session['_customer_csrf']
        self.assertEqual(self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'action':'rejected','csrf':admin_csrf}).status_code,302)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,0)
        self.assertEqual(panel.commerce.Entry.query.count(),0)
    def test_separate_delivery_settings_preserve_cards_plans_and_saved_secrets(self):
        self.configure();self.admin()
        with self.client.session_transaction() as session: admin_csrf=session['_customer_csrf']
        before=self.features.settings()
        self.assertEqual(self.client.get('/panel/settings/notifications').status_code,200)
        response=self.client.post('/panel/settings/notifications',data={'csrf':admin_csrf,'bot_username':'AnotherBot','admin_chat_ids':'123456,987654','bot_token':'','smtp_password':''})
        self.assertEqual(response.status_code,302)
        after=self.features.settings()
        for key in ('bank_cards','plans','custom_pricing','card_number'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after['bot_username'],'AnotherBot')
        self.assertIn(b'Saved; leave blank to keep', self.client.get('/panel/settings/notifications').data)
    def test_wallet_debit_renewal_invoice_and_duplicate_submit(self):
        csrf=self.csrf();wallet=panel.commerce.Wallet(user_id=self.user.id,balance=500000);panel.db.session.add(wallet);panel.db.session.commit()
        base='/panel/c/'+self.token+'/wallet';ref='a'*43
        fields={'csrf':csrf,'reference':ref,'plan_id':'monthly-unlimited'}
        plan=self.features.settings()['plans'][0];fields['plan_id']=plan['id']
        with patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',return_value=[]):
            self.assertEqual(self.client.post(base,data=fields).status_code,302)
            self.assertEqual(self.client.post(base,data=fields).status_code,302)
        self.assertEqual(wallet.balance,500000-plan['price']);self.assertEqual(self.user.traffic_limit,100+plan['quota'])
        self.assertEqual(panel.commerce.Entry.query.count(),1);self.assertEqual(panel.commerce.Invoice.query.count(),1)
    def test_insufficient_funds_roll_back_coupon_reservation(self):
        csrf=self.csrf();panel.db.session.add(panel.commerce.Wallet(user_id=self.user.id,balance=1));coupon=panel.commerce.Coupon(code='SAVE20',percent=20,limit=1,expires='2027-12-31');panel.db.session.add(coupon);panel.db.session.commit()
        response=self.client.post('/panel/c/'+self.token+'/wallet',data={'csrf':csrf,'reference':'b'*43,'plan_id':self.features.settings()['plans'][0]['id'],'coupon':'SAVE20'})
        self.assertEqual(response.status_code,409);self.assertEqual(coupon.used,0);self.assertEqual(panel.commerce.Entry.query.count(),0)
    def test_admin_block_cannot_be_bypassed_by_wallet_purchase(self):
        csrf=self.csrf();self.user.status='disabled';panel.db.session.add(panel.commerce.Wallet(user_id=self.user.id,balance=500000));panel.db.session.commit()
        self.assertEqual(self.client.post('/panel/c/'+self.token+'/wallet',data={'csrf':csrf,'reference':'c'*43,'plan_id':self.features.settings()['plans'][0]['id']}).status_code,403)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
    def test_financial_adjustment_idempotent_and_requires_role(self):
        self.admin();url='/panel/users/view/'+str(self.user.id)+'/wallet';fields={'amount':'100000','reason':'Verified bank payment','reference':'d'*43}
        self.assertEqual(self.client.post(url,data=fields).status_code,302);self.client.post(url,data=fields)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,100000)
        self.assertEqual(panel.commerce.Entry.query.count(),1)
        fields.update(amount='-200000',reference='e'*43)
        self.assertEqual(self.client.post(url,data=fields).status_code,409)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,100000)
