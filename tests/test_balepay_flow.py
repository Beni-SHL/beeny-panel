import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch
import test_customer as fixture

panel = fixture.panel


class BalePayFlowTests(unittest.TestCase):
    setUp = fixture.CustomerFlowTests.setUp
    tearDown = fixture.CustomerFlowTests.tearDown
    csrf = fixture.CustomerFlowTests.csrf
    admin = fixture.CustomerFlowTests.admin

    def start(self):
        return self.client.post('/panel/c/'+self.token+'/balepay/start', data={'csrf':self.csrf(), 'plan_id':fixture.DEFAULT_PLANS[0]['id']})

    def signed_confirm(self, order):
        path='/panel/api/balepay/confirm'
        body=json.dumps({'order_id':order.id,'payment_id':'verified-test-transaction','amount_irr':order.amount_irr,'currency':'IRR'})
        stamp=str(int(time.time()))
        signature=hmac.new(b'x'*40, '\n'.join(['POST',path,stamp,body]).encode(),hashlib.sha256).hexdigest()
        return self.client.post(path,data=body,content_type='application/json',headers={'X-Beeny-Timestamp':stamp,'X-Beeny-Signature':signature})

    @patch.dict('os.environ', {'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_abandoned_checkout_can_start_new_order_and_late_payment_is_idempotent(self):
        self.assertEqual(self.start().status_code,303)
        first=panel.balepay_orders.query.one()
        self.assertEqual(self.start().status_code,303)
        panel.db.session.refresh(first)
        self.assertEqual(first.status,'superseded')
        self.assertEqual(panel.balepay_orders.query.count(),2)
        def approve(row):
            row.status='completed'
            panel.db.session.commit()
        with patch.object(panel.experience,'approve_renewal',side_effect=approve) as approval:
            self.assertEqual(self.signed_confirm(first).status_code,200)
            self.assertEqual(self.signed_confirm(first).status_code,200)
            self.assertEqual(approval.call_count,1)
        self.assertEqual(self.features.RenewalRequest.query.count(),1)

    @patch.dict('os.environ', {'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_manager_sees_order_and_staff_cannot_access_either_settings_route(self):
        self.assertEqual(self.start().status_code,303)
        self.admin()
        response=self.client.get('/panel/payments/balepay')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'customer-one',response.data)
        admin=panel.Admin.query.first();admin.role='staff';panel.db.session.commit()
        from flask import g
        g.pop('_login_user',None)
        for path in ('/panel/payments/balepay','/panel/settings/balepay','/panel/settings/customer?tab=balepay'):
            self.assertEqual(self.client.get(path).status_code,403)

    def test_common_payment_settings_form_saves_with_shared_csrf(self):
        self.admin()
        url='/panel/settings/customer?tab=balepay'
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'customer-admin', response.data)
        self.assertIn(b'action="/panel/settings/customer?tab=balepay"', response.data)
        with self.client.session_transaction() as session:
            csrf=session['_customer_csrf']
        response=self.client.post(url, data={'csrf':csrf,'wordpress_url':'https://checkout.example.com','shared_secret':'test-shared-secret-'+'a'*32,'enabled':'1'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.location.endswith('/settings/customer?tab=balepay'))
        from sqlalchemy import text
        row=panel.db.session.execute(text('SELECT wordpress_url, encrypted_secret FROM balepay_gateway_config')).one()
        self.assertEqual(row[0],'https://checkout.example.com')
        self.assertNotIn('test-shared-secret',row[1])
        self.assertEqual(self.user.status,'active')
        self.assertEqual(self.user.traffic_usage,25)
        self.assertEqual(self.client.post(url,data={'csrf':'wrong','wordpress_url':'https://other.example.com'}).status_code,403)

    @patch.dict('os.environ', {'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_test_mode_snapshot_cannot_activate_real_account(self):
        from unittest.mock import patch as mock_patch
        self.assertEqual(self.start().status_code,303)
        order=panel.balepay_orders.query.one()
        plan=json.loads(order.plan_json)
        plan['payment_test_mode']=True
        order.plan_json=json.dumps(plan)
        panel.db.session.commit()
        with mock_patch.object(panel.experience,'approve_renewal') as approval:
            self.assertEqual(self.signed_confirm(order).status_code,409)
            approval.assert_not_called()
        self.assertEqual(self.user.traffic_usage,25)
        self.assertEqual(self.user.status,'active')
        self.assertEqual(self.features.RenewalRequest.query.count(),0)

    def test_gateway_is_adjacent_to_pricing_in_shared_toolbar(self):
        self.admin()
        import re
        html=self.client.get('/panel/settings/customer').get_data(as_text=True)
        nav=re.search(r'<nav class="customer-payment-tabs"[^>]*>(.*?)</nav>',html,re.S)
        self.assertIsNotNone(nav)
        labels=[__import__('html').unescape(v) for v in re.findall(r'<span>([^<]+)</span>',nav.group(1))]
        self.assertEqual(labels,['Cards & contacts','Plans & pricing','BalePay'])
        html=self.client.get('/panel/settings/customer?tab=balepay').get_data(as_text=True)
        nav=re.search(r'<nav class="customer-payment-tabs"[^>]*>(.*?)</nav>',html,re.S).group(1)
        self.assertRegex(nav,r'aria-current="page"[^>]*>.*?<span>BalePay</span>')

    @patch.dict('os.environ', {'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_disabled_gateway_hides_banner_and_rejects_checkout(self):
        self.csrf()
        portal='/panel/c/'+self.token
        response=self.client.get(portal)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'class="bale-online-banner',response.data)
        self.admin()
        with self.client.session_transaction() as session:
            csrf=session['_customer_csrf']
        response=self.client.post('/panel/settings/customer?tab=balepay',data={
            'csrf':csrf,'wordpress_url':'https://payment.example.com'})
        self.assertEqual(response.status_code,302)
        response=self.client.get(portal)
        self.assertEqual(response.status_code,200)
        self.assertNotIn(b'class="bale-online-banner',response.data)
        self.assertNotIn(b'class="bale-online-button"',response.data)
        self.assertEqual(self.start().status_code,503)
        self.assertEqual(panel.balepay_orders.query.count(),0)

    @patch.dict('os.environ', {'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_wallet_online_payment_credits_once_without_changing_service(self):
        csrf=self.csrf();url='/panel/c/'+self.token+'/balepay/wallet/start'
        before=(self.user.expire_date,self.user.traffic_limit,self.user.traffic_usage)
        self.assertEqual(self.client.post(url,data={'csrf':csrf,'amount':'250000','coupon':'IGNORED'}).status_code,303)
        order=panel.balepay_orders.query.one()
        self.assertEqual(order.amount_irr,2500000)
        self.assertEqual(self.signed_confirm(order).status_code,200)
        self.assertEqual(self.signed_confirm(order).status_code,200)
        wallet=panel.db.session.get(panel.commerce.Wallet,self.user.id)
        self.assertEqual(wallet.balance,250000)
        self.assertEqual(panel.commerce.Entry.query.count(),1)
        self.assertEqual(panel.commerce.Invoice.query.count(),0)
        self.assertEqual(self.features.RenewalRequest.query.one().source,'wallet_topup')
        self.assertEqual((self.user.expire_date,self.user.traffic_limit,self.user.traffic_usage),before)

    @patch.dict('os.environ', {'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_wallet_payment_amount_validation_and_disabled_gateway(self):
        csrf=self.csrf();url='/panel/c/'+self.token+'/balepay/wallet/start'
        for amount in ('-1','999','100000001','not-a-number'):
            self.assertEqual(self.client.post(url,data={'csrf':csrf,'amount':amount}).status_code,400)
        self.assertEqual(panel.balepay_orders.query.count(),0)
        self.assertEqual(self.client.post(url,data={'csrf':'wrong','amount':'1000'}).status_code,400)

    def test_owner_coupon_switch_hides_shared_fields_and_rejects_codes(self):
        self.csrf();self.admin()
        with self.client.session_transaction() as session:csrf=session['_customer_csrf']
        url='/panel/settings/sales/coupon-visibility'
        self.assertEqual(self.client.post(url,data={'csrf':csrf}).status_code,302)
        self.assertFalse(self.features.settings()['coupons_enabled'])
        portal=self.client.get('/panel/c/'+self.token).data
        self.assertNotIn(b'class="coupon-field"',portal)
        self.assertNotIn(b'name="coupon"',self.client.get('/panel/c/'+self.token+'/wallet').data)
        with self.assertRaises(ValueError):panel.commerce.discount(dict(price=1000),'CODE')
        self.assertEqual(self.client.post(url,data={'csrf':csrf,'enabled':'1'}).status_code,302)
        self.assertIn(b'class="coupon-field"',self.client.get('/panel/c/'+self.token).data)

    def test_renewal_layout_and_conditional_speed_warning(self):
        self.csrf();url='/panel/c/'+self.token
        self.assertNotIn(b'speed-status-card',self.client.get(url).data)
        self.user.quota_mode='fair_use';self.user.traffic_usage=101
        panel.db.session.commit()
        self.assertIn(b'speed-status-card',self.client.get(url).data)
