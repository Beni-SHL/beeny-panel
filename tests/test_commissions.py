"""Money and provisioning boundaries for single-level commission selling."""
import io,json,hashlib,secrets,unittest
from unittest.mock import patch
from datetime import datetime,timedelta
from werkzeug.security import check_password_hash
import test_customer as fixture
import test_studio as studio
from test_customer import panel

class CommissionTests(unittest.TestCase):
    setUp=studio.StudioTests.setUp
    tearDown=studio.StudioTests.tearDown
    csrf=studio.StudioTests.csrf
    configure=studio.StudioTests.configure
    admin=studio.StudioTests.admin
    enable=studio.StudioTests.enable
    def prepare(self):
        self.configure();self.enable();self.c=panel.commissions;self.db=panel.db
        notifier=patch.object(self.features,'telegram',return_value={});notifier.start();self.addCleanup(notifier.stop)
        self.db.session.add(self.c.Policy(reseller_id=self.user.id,enabled=True,invite='I'*43,minimum=10000))
        self.db.session.add(self.c.Rate(reseller_id=self.user.id,plan_id='monthly',base_price=200000,maximum=350000,sale_price=250000))
        self.db.session.commit();self.shop='/panel/r/'+'I'*43
        self.private='/panel/c/'+self.token+'/reseller/commission';self.csrf_token=self.csrf()
    def submit(self,**changes):
        values=dict(csrf=self.csrf_token,reference='b'*32,plan_id='monthly',node_id=self.node.id,username='commission-child',password='Strong-private-password-123',name='Buyer',contact='Phone',card_id='primary',price='1',receipt=(io.BytesIO(fixture.jpeg()),'receipt.jpg'))
        values.update(changes)
        return self.client.post(self.shop,data=values)
    def approve(self):
        self.sale=self.c.Sale.query.one();self.admin()
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):
            return self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'})
    def test_sale_snapshots_price_hashes_password_and_waits_for_approval(self):
        self.prepare();self.assertEqual(self.submit().status_code,302)
        sale=self.c.Sale.query.one();plan=json.loads(sale.plan)
        self.assertEqual((plan['price'],plan['commission_base'],plan['commission_amount']),(250000,200000,50000))
        self.assertTrue(check_password_hash(sale.password_hash,'Strong-private-password-123'))
        self.assertIsNone(panel.User.query.filter_by(username='commission-child').first())
        self.assertEqual(self.c.Earning.query.count(),0);self.assertEqual(panel.commerce.Entry.query.count(),0)
        self.assertEqual(self.submit().status_code,302);self.assertEqual(self.c.Sale.query.count(),1)
        self.assertEqual(self.client.get('/panel/r/order/'+sale.tracking).status_code,200)
    def test_approval_provisions_and_books_once_without_debiting_wallet(self):
        self.prepare();self.submit();self.assertEqual(self.approve().status_code,302)
        self.assertEqual(self.approve().status_code,302)
        self.assertEqual(self.sale.state,'completed');self.assertEqual(self.sale.password_hash,'')
        child=panel.User.query.filter_by(username='commission-child').one();self.assertEqual(child.reseller_id,self.user.id)
        self.assertEqual((child.traffic_limit,child.status),(100,'active'))
        earning=self.c.Earning.query.one();self.assertEqual((earning.amount,earning.state),(50000,'available'))
        self.assertEqual(panel.commerce.Invoice.query.count(),1);self.assertEqual(panel.commerce.Entry.query.count(),0)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
    def test_failed_node_never_creates_commission_and_can_retry(self):
        self.prepare();self.submit();self.sale=self.c.Sale.query.one();self.admin()
        with patch('app.sync_primary_access',side_effect=RuntimeError('failed')):
            self.assertEqual(self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'}).status_code,302)
        self.assertEqual(self.sale.state,'provisioning');self.assertEqual(self.c.Earning.query.count(),0)
        self.assertEqual(self.db.session.get(panel.User,self.sale.user_id).status,'disabled')
        self.assertEqual(self.approve().status_code,302);self.assertEqual(self.c.Earning.query.count(),1)
    def test_access_confirmation_failure_holds_commission_until_reconciliation(self):
        self.prepare();self.submit();self.sale=self.c.Sale.query.one();self.admin()
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=['Remote']):
            self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'})
        self.assertEqual(self.sale.state,'provisioning');self.assertEqual(self.c.Earning.query.count(),0)
        with patch.object(panel.experience,'sync_access',return_value=[]):self.c.cycle()
        self.assertEqual(self.sale.state,'completed');self.assertEqual(self.c.Earning.query.one().state,'available')
    def test_locked_and_revoked_grant_block_sale_or_approval(self):
        self.prepare();self.submit();self.admin();self.sale=self.c.Sale.query.one()
        self.db.session.get(panel.resellers.Profile,self.user.id).enabled=False;self.db.session.commit()
        self.assertEqual(self.client.get(self.shop).status_code,404)
        self.assertEqual(self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'}).status_code,409)
        self.assertEqual(self.c.Earning.query.count(),0)
    def test_tampered_node_plan_and_csrf_do_not_register_sale(self):
        self.prepare()
        self.assertEqual(self.submit(node_id=self.remote.id).status_code,400)
        self.assertEqual(self.submit(plan_id='custom').status_code,400)
        self.assertEqual(self.submit(csrf='bad').status_code,400)
        self.assertEqual(self.c.Sale.query.count(),0)
    def test_exact_duplicate_receipt_rejected_across_sales_and_ordinary_renewals(self):
        self.prepare();self.submit()
        self.assertEqual(self.submit(reference='d'*32,username='another-child').status_code,409)
        before=set(self.features.storage.glob('*'))
        with self.assertRaises(ValueError):self.features.create_request(self.other,'monthly',fixture.jpeg(),'Buyer','Phone')
        self.assertEqual(set(self.features.storage.glob('*')),before)
        self.assertEqual(self.c.Sale.query.count(),1)
    def test_price_bounds_and_immutable_snapshots(self):
        self.prepare();self.submit();sale=self.c.Sale.query.one()
        self.assertEqual(self.client.post(self.private,data={'csrf':self.csrf_token,'action':'price','plan_id':'monthly','price':'1'}).status_code,400)
        self.assertEqual(self.client.post(self.private,data={'csrf':self.csrf_token,'action':'price','plan_id':'monthly','price':'350001'}).status_code,400)
        self.assertEqual(self.client.post(self.private,data={'csrf':self.csrf_token,'action':'price','plan_id':'monthly','price':'300000'}).status_code,302)
        self.assertEqual(json.loads(sale.plan)['price'],250000)
        self.other.reseller_id=self.user.id;self.db.session.add(panel.UserNode(user_id=self.other.id,node_id=self.node.id));self.db.session.commit()
        with panel.app.test_request_context():
            plan=self.c.customer_plan(self.other,self.features.settings()['plans'][0]);self.assertEqual(plan['price'],300000)
    def settled_earning(self,state='available'):
        self.prepare();self.submit();self.approve();self.earning=self.c.Earning.query.one()
        self.csrf();self.client.environ_base.pop('HTTP_X_CSRF_TOKEN',None)
        self.earning.state=state;self.db.session.commit()
    def request_settlement(self,ref='e'*32):
        return self.client.post(self.private,data={'csrf':self.csrf_token,'action':'settlement','reference':ref,'destination':'1234567812345678 · Partner'})
    def test_settlement_reserves_once_and_rejection_releases_credit(self):
        self.settled_earning();self.assertEqual(self.request_settlement().status_code,302)
        self.assertEqual(self.request_settlement().status_code,302)
        row=self.c.Settlement.query.one();self.assertEqual((row.amount,self.earning.state),(50000,'reserved'))
        self.assertEqual(self.request_settlement('f'*32).status_code,409)
        self.admin();result=self.client.post('/panel/settings/commissions',data={'csrf':self.csrf_token,'action':'reject_settlement','settlement_id':row.id})
        self.assertEqual(result.status_code,302);self.assertEqual(self.earning.state,'available')
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
    def test_payment_receipt_private_and_settlement_paid_once(self):
        self.settled_earning();self.request_settlement();row=self.c.Settlement.query.one();self.admin()
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(120,80),'#12bbcc').save(image,'JPEG');image.seek(0)
        result=self.client.post('/panel/settings/commissions',data={'csrf':self.csrf_token,'action':'pay','settlement_id':row.id,'payment_reference':'BANK-TRANSFER-1','receipt':(image,'paid.jpg')})
        self.assertEqual(result.status_code,302);self.assertEqual((row.state,self.earning.state),('paid','settled'))
        self.assertEqual(self.client.get('/panel/settings/commissions/settlements/'+str(row.id)+'/receipt').status_code,200)
        anon=panel.app.test_client();self.assertEqual(anon.get(self.private+'/settlements/'+str(row.id)+'/receipt').status_code,302)
        self.assertEqual(self.client.post('/panel/settings/commissions',data={'csrf':self.csrf_token,'action':'pay','settlement_id':row.id}).status_code,409)
    def test_refund_paid_commission_creates_debt_once_and_preserves_history(self):
        self.settled_earning(state='settled');self.admin()
        values={'csrf':self.csrf_token,'action':'refund','earning_id':self.earning.id,'payment_reference':'REFUND-1','reason':'Customer full refund'}
        with patch.object(panel.experience,'sync_access',return_value=[]):self.assertEqual(self.client.post('/panel/settings/commissions',data=values).status_code,302)
        self.assertEqual(self.client.post('/panel/settings/commissions',data=values).status_code,409)
        self.assertEqual(self.c.Refund.query.count(),1);self.assertEqual(self.c.Earning.query.count(),2)
        self.assertEqual(self.c.sums(self.user.id)['available'],-50000)
        self.assertEqual(panel.commerce.Invoice.query.count(),1)
        report=self.client.get('/panel/settings/sales');self.assertEqual(report.status_code,200);self.assertIn(b'Refunded',report.data)
        self.assertEqual(self.db.session.get(panel.User,self.sale.user_id).status,'disabled')
    def test_renewal_uses_rep_price_and_records_commission_only_once(self):
        self.prepare();self.other.reseller_id=self.user.id;self.db.session.add(panel.UserNode(user_id=self.other.id,node_id=self.node.id));self.db.session.commit()
        # Different image from storefront fixture so the payment is independent.
        row=self.features.create_request(self.other,'monthly',fixture.jpeg(),'Buyer','Phone')
        self.assertEqual(json.loads(row.plan)['commission_amount'],50000)
        self.admin();grant=self.db.session.get(self.features.ReceiptGrant,row.id);before=grant.base_limit if grant else self.other.traffic_limit
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.other.pause_sync_pending=False;self.other.speed_sync_pending=False
            self.assertEqual(self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'completed'}).status_code,302)
        self.assertEqual(self.other.traffic_limit,before+100);self.assertEqual(self.c.Earning.query.count(),1)
        self.assertEqual(self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'completed'}).status_code,409)
        self.assertEqual(self.c.Earning.query.count(),1)
    def test_commission_coupon_and_unapproved_plan_cannot_discount_manager_base(self):
        self.prepare();self.other.reseller_id=self.user.id;self.db.session.add(panel.UserNode(user_id=self.other.id,node_id=self.node.id));self.db.session.commit()
        with self.assertRaises(ValueError):self.features.create_request(self.other,'monthly',fixture.jpeg(),'Buyer','Phone',coupon='SAVE20')
        with self.assertRaises(ValueError):self.features.create_request(self.other,'custom',fixture.jpeg(),'Buyer','Phone',custom={'days':'30','quota':'100','devices':'1'})
        self.assertEqual(self.features.RenewalRequest.query.count(),0)
    def test_finance_scope_locked_history_and_legacy_modes_preserved(self):
        self.prepare();self.assertEqual(self.client.get(self.private).status_code,200)
        self.assertEqual(self.client.get('/panel/c/'+self.token+'/reseller').location,self.private)
        self.db.session.get(panel.resellers.Profile,self.user.id).enabled=False;self.db.session.commit()
        self.assertEqual(self.client.get(self.private).status_code,200)
        self.assertEqual(self.client.post(self.private,data={'csrf':self.csrf_token,'action':'price','plan_id':'monthly','price':'250000'}).status_code,403)
        self.admin();owner=panel.Admin.query.first();owner.role='finance';self.db.session.commit()
        self.assertEqual(self.client.get('/panel/settings/commissions').status_code,403)
        self.assertEqual(self.client.get('/panel/settings/commissions/sales').status_code,403)
    def test_deleted_identity_cannot_inherit_commissions(self):
        self.settled_earning();uid=self.user.id;self.features.delete_customer(uid);self.db.session.commit()
        self.assertIsNone(self.db.session.get(self.c.Policy,uid));self.assertEqual(self.c.Earning.query.filter_by(reseller_id=uid).count(),0)
        self.assertEqual(self.c.Earning.query.one().reseller_id,-uid)

    def test_failed_paid_sale_refund_stops_retry_without_wallet_or_earning(self):
        self.prepare();self.submit();self.sale=self.c.Sale.query.one();self.admin()
        with patch('app.sync_primary_access',side_effect=RuntimeError('failed')):
            self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'})
        fields=dict(csrf=self.csrf_token,action='refund_failed',payment_reference='FAILED-REFUND-1',reason='Provision did not complete')
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data=fields).status_code,302)
        self.assertEqual(self.sale.state,'refunded');self.assertEqual(self.c.Refund.query.count(),1)
        self.assertEqual(self.c.Earning.query.count(),0);self.assertEqual(panel.resellers.Order.query.one().state,'cancelled')
        self.c.cycle();self.assertEqual(self.c.Earning.query.count(),0)
        self.assertEqual(self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data=fields).status_code,409)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
    def test_reserved_commission_cannot_be_refunded_until_settlement_rejected(self):
        self.settled_earning();self.request_settlement();self.admin()
        with patch.object(panel.experience,'sync_access',return_value=[]):
            result=self.client.post('/panel/settings/commissions',data=dict(csrf=self.csrf_token,action='refund',earning_id=self.earning.id,payment_reference='RESERVED-REFUND',reason='Customer refund'))
        self.assertEqual(result.status_code,409);self.assertEqual(self.earning.state,'reserved');self.assertEqual(self.c.Refund.query.count(),0)
    def test_database_prevents_two_pending_settlements_and_positive_duplicate_sale_names(self):
        from sqlalchemy.exc import IntegrityError
        self.settled_earning();self.request_settlement()
        self.db.session.add(self.c.Settlement(reference='9'*32,reseller_id=self.user.id,amount=50000,destination='Another bank account'))
        with self.assertRaises(IntegrityError):self.db.session.commit()
        self.db.session.rollback();self.assertEqual(self.c.Settlement.query.count(),1)
        self.assertEqual(self.c.Earning.query.one().state,'reserved')
    def test_admin_notification_retries_only_unsent_recipients(self):
        self.prepare();self.features.set_setting('admin_chat_ids','111,222');self.db.session.commit();self.submit()
        calls=[]
        def telegram(method,data):
            calls.append(data['chat_id'])
            if data['chat_id']=='222':raise RuntimeError('network failure')
        with patch.object(self.features,'telegram',side_effect=telegram):self.c.deliver_alerts()
        alert=self.c.Alert.query.one();self.assertEqual(json.loads(alert.sent),['123456','111']);self.assertFalse(alert.completed)
        alert.next_attempt=datetime.utcnow()-timedelta(seconds=1);self.db.session.commit()
        with patch.object(self.features,'telegram',return_value={}) as sender:self.c.deliver_alerts()
        self.assertEqual(sender.call_count,1);self.assertEqual(sender.call_args.args[1]['chat_id'],'222')
        self.assertTrue(alert.completed)
    def test_prepaid_cancel_cannot_credit_a_commission_sale(self):
        self.prepare();self.submit();self.sale=self.c.Sale.query.one();self.admin()
        with patch('app.sync_primary_access',side_effect=RuntimeError('failed')):
            self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'})
        order=panel.resellers.Order.query.one()
        self.assertEqual(self.client.post('/panel/settings/resellers',data=dict(csrf=self.csrf_token,action='refund',order_id=order.id)).status_code,409)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
    def test_rotated_profile_link_is_not_exposed_to_representative(self):
        self.prepare();self.submit();self.approve();order=panel.resellers.Order.query.one()
        self.db.session.get(panel.AccountLink,order.user_id).token_hash='d'*64;self.db.session.commit();self.csrf()
        result=self.client.get(self.private)
        self.assertNotIn(order.portal_token.encode(),result.data)
    def test_policy_creation_and_pending_mode_switch_guard(self):
        self.prepare();self.submit();self.admin()
        fields=dict(csrf=self.csrf_token,action='policy',reseller_id=self.user.id,minimum=10000)
        for plan in self.features.settings()['plans']:
            fields['base_'+plan['id']]=plan['price'];fields['max_'+plan['id']]=plan['price']+50000
        self.assertEqual(self.client.post('/panel/settings/commissions',data=fields).status_code,409)
        self.assertTrue(self.db.session.get(self.c.Policy,self.user.id).enabled)

    def test_completed_order_with_unconfirmed_access_can_be_refunded(self):
        self.prepare();self.submit();self.sale=self.c.Sale.query.one();self.admin()
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=['Remote']):
            self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data={'csrf':self.csrf_token,'action':'approve'})
        self.assertEqual(panel.resellers.Order.query.one().state,'completed');self.assertEqual(self.sale.state,'provisioning')
        fields=dict(csrf=self.csrf_token,action='refund_failed',payment_reference='UNCONFIRMED-REFUND',reason='Access confirmation failed')
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post('/panel/settings/commissions/sales/'+str(self.sale.id),data=fields).status_code,302)
        self.assertEqual(self.sale.state,'refunded');self.assertEqual(self.c.Earning.query.count(),0)
        self.assertEqual(self.c.Refund.query.count(),1);self.assertEqual(panel.resellers.Order.query.one().state,'cancelled')
