import io,json,unittest,secrets
from unittest.mock import patch
from datetime import datetime
from werkzeug.exceptions import HTTPException
import test_customer as fixture
from test_customer import panel
import test_commissions as commission_fixture
import test_balepay_flow as bale_fixture

class RepresentativeCreditTests(unittest.TestCase):
    setUp=commission_fixture.CommissionTests.setUp
    tearDown=commission_fixture.CommissionTests.tearDown
    csrf=commission_fixture.CommissionTests.csrf
    configure=commission_fixture.CommissionTests.configure
    enable=commission_fixture.CommissionTests.enable
    admin=commission_fixture.CommissionTests.admin
    signed_confirm=bale_fixture.BalePayFlowTests.signed_confirm
    def prepare(self):
        commission_fixture.CommissionTests.prepare(self);self.credit=panel.representative_credit
        self.db.session.add(self.credit.Account(reseller_id=self.user.id,enabled=True,credit_limit=1000000,debt=0))
        self.db.session.get(panel.commerce.Wallet,self.user.id).balance=0
        self.db.session.commit();self.path='/panel/c/'+self.token+'/reseller/credit'
    def create(self,**kw):
        data=dict(csrf=self.csrf_token,action='create',reference='c'*32,username='credit-child',password='Private-credit-password-123',plan_id='monthly',node_id=self.node.id)
        data.update(kw)
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):return self.client.post(self.path,data=data)
    def debt_request(self,amount=200000,reference='d'*32):
        row=self.features.RenewalRequest(user_id=self.user.id,username=self.user.username,source='reseller_debt',receipt='',billing_reference=reference,plan=json.dumps(dict(id='reseller-debt',kind='reseller_debt',price=amount,days=0,quota=0,devices=0,title='Debt')),email_state='skipped',telegram_state='skipped')
        self.db.session.add(row);self.db.session.commit();return row
    def approve(self,row):
        with panel.app.test_request_context(),patch.object(panel.experience,'sync_access',return_value=[]):panel.experience.approve_renewal(row)
    def earning(self,amount=50000,state='available',reference='renewal-profit'):
        row=self.c.Earning(reference=reference,reseller_id=self.user.id,user_id=self.other.id,username=self.other.username,amount=amount,sale_amount=250000,base_amount=200000,snapshot='{}',state=state)
        self.db.session.add(row);self.db.session.commit();return row
    def test_initial_credit_is_not_cash_and_creation_books_only_base_once(self):
        self.prepare();before=panel.commerce.Wallet.query.count()
        self.assertEqual(self.create().status_code,302);self.assertEqual(self.create().status_code,302)
        a=self.credit.Account.query.one();self.assertEqual(a.debt,200000)
        self.assertEqual(panel.commerce.Wallet.query.count(),before)
        self.assertEqual(self.c.Earning.query.count(),0);self.assertEqual(panel.commerce.Invoice.query.count(),0)
        m=self.credit.Margin.query.one();self.assertEqual((m.base_amount,m.sale_amount,m.state),(200000,250000,'completed'))
        self.assertEqual(self.credit.Entry.query.filter_by(kind='issue').count(),1)
        child=panel.User.query.filter_by(username='credit-child').one();self.assertTrue(self.features.CustomerProfile.query.filter_by(user_id=child.id).one().password_hash)
        self.assertEqual(self.client.get(self.path).status_code,200)
    def test_credit_limit_and_scoped_node_enforced_without_cash_debit(self):
        self.prepare();a=self.credit.Account.query.one();a.credit_limit=100000;self.db.session.commit()
        self.assertEqual(self.create().status_code,409);self.assertEqual(a.debt,0)
        self.assertEqual(self.create(node_id=self.remote.id).status_code,403)
        self.assertEqual(self.credit.Margin.query.count(),0)
    def test_failed_provision_reserves_debt_and_retry_never_charges_again(self):
        self.prepare()
        with patch('resellers.subprocess.run',side_effect=RuntimeError('fail')),patch('app.sync_primary_access'):
            data=dict(csrf=self.csrf_token,action='create',reference='c'*32,username='credit-child',password='Private-credit-password-123',plan_id='monthly',node_id=self.node.id)
            self.assertEqual(self.client.post(self.path,data=data).status_code,302)
        self.assertEqual(self.credit.Margin.query.one().state,'pending');self.assertEqual(self.credit.Account.query.one().debt,200000)
        order=panel.resellers.Order.query.one()
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(self.path,data={'csrf':self.csrf_token,'reference':'e'*32,'action':'retry','order_id':order.id}).status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,200000);self.assertEqual(self.credit.Margin.query.one().state,'completed')
    def test_verified_debt_payment_restores_credit_without_renewing_representative(self):
        self.prepare();self.create();before=(self.user.expire_date,self.user.traffic_limit,self.user.traffic_usage)
        row=self.debt_request();self.approve(row)
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual((self.user.expire_date,self.user.traffic_limit,self.user.traffic_usage),before)
        with self.assertRaises(HTTPException):self.approve(row)
        self.assertEqual(self.credit.Entry.query.filter_by(kind='payment').count(),1)
    def test_partial_repayment_keeps_financial_restrictions_then_releases_only_financial(self):
        self.prepare();self.create();a=self.credit.Account.query.one();a.locked=True;a.suspended=True;a.locked_reason='financial';a.suspended_reason='other';self.db.session.commit()
        self.approve(self.debt_request(100000));self.assertTrue(a.locked);self.assertTrue(a.suspended);self.assertEqual(a.debt,100000)
        self.approve(self.debt_request(100000,'e'*32));self.assertFalse(a.locked);self.assertTrue(a.suspended);self.assertEqual(a.debt,0)
    def test_full_payment_releases_financial_suspension_without_overriding_child_flags(self):
        self.prepare();self.create();child=panel.User.query.filter_by(username='credit-child').one();child.customer_paused=True;child.status='disabled'
        a=self.credit.Account.query.one();a.suspended=True;a.locked=True;self.db.session.commit()
        self.approve(self.debt_request());self.assertFalse(a.suspended);self.assertFalse(a.locked)
        self.assertEqual(child.status,'disabled');self.assertTrue(child.customer_paused)
    def test_offset_is_atomic_idempotent_and_reduces_withdrawable_income(self):
        self.prepare();self.create();e=self.earning(70000)
        data={'csrf':self.csrf_token,'action':'offset','reference':'f'*32,'amount':'40000'}
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(self.path,data=data).status_code,302);self.assertEqual(self.client.post(self.path,data=data).status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,160000);self.assertEqual(e.offset_used,40000)
        self.assertEqual(self.c.sums(self.user.id)['available'],30000)
        self.assertEqual(self.client.post(self.private,data={'csrf':self.csrf_token,'action':'settlement','reference':'a'*32,'destination':'1234567890123456'}).status_code,302)
        self.assertEqual(self.c.Settlement.query.one().amount,30000)
        self.assertEqual(self.client.post(self.path,data={**data,'reference':'b'*32,'amount':'1'}).status_code,409)
    def test_held_commission_cannot_be_used_and_negative_clawback_limits_income(self):
        self.prepare();self.create();self.earning(70000,'held')
        self.assertEqual(self.client.post(self.path,data={'csrf':self.csrf_token,'action':'offset','reference':'f'*32,'amount':'1'}).status_code,409)
        self.earning(50000,'available','good');self.earning(-20000,'available','clawback')
        self.assertEqual(self.client.post(self.path,data={'csrf':self.csrf_token,'action':'offset','reference':'a'*32,'amount':'40000'}).status_code,409)
    def test_overpayment_after_parallel_settlement_goes_to_cash_wallet_once(self):
        self.prepare();self.create();row=self.debt_request();a=self.credit.Account.query.one();a.debt=50000;self.db.session.commit();self.approve(row)
        self.assertEqual(a.debt,0);self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,150000)
        with self.assertRaises(HTTPException):self.approve(row)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,150000)
    def test_lock_blocks_creation_but_allows_customer_renewal_prices(self):
        self.prepare();self.create();child=panel.User.query.filter_by(username='credit-child').one();a=self.credit.Account.query.one();a.locked=True;self.db.session.commit()
        self.assertEqual(self.create(reference='e'*32,username='another-child').status_code,403)
        plan=self.c.customer_plan(child,dict(self.features.settings()['plans'][0]));self.assertEqual(plan['price'],250000)
        self.assertFalse(self.credit.suspended(child))
    def test_suspension_denies_primary_access_and_survives_customer_unpause(self):
        self.prepare();self.create();child=panel.User.query.filter_by(username='credit-child').one();a=self.credit.Account.query.one();a.suspended=True;self.db.session.commit()
        with patch('app.sync_primary_access') as sync,patch('vpn_sessions.local_sessions',return_value=[]),patch.object(panel.speed_policy,'sync',return_value=[]):
            panel.experience.sync_access(child);sync.assert_called_with(child,False)
        self.assertEqual(child.status,'active')
        with self.assertRaises(ValueError):self.c.customer_plan(child,dict(self.features.settings()['plans'][0]))
    def test_debt_receipt_telegram_review_uses_private_signed_scope(self):
        self.prepare();self.create();row=self.debt_request();row.receipt='receipt.jpg';self.db.session.commit()
        key=self.features.receipt_keyboard(row,'123456');self.assertTrue(key)
        self.features.set_setting('admin_chat_id','123456');self.db.session.commit()
        action=self.features.receipt_action(row,'123456','yes')
        with patch('customer_features.requests.post') as post,patch.object(panel.experience,'sync_access',return_value=[]):
            post.return_value.status_code=200;post.return_value.json.return_value={'ok':True,'result':{}}
            self.features.process_update({'callback_query':{'id':'test','data':action,'from':{'id':123456},'message':{'chat':{'id':123456,'type':'private'}}}})
        self.assertEqual(self.credit.Account.query.one().debt,0)
    def test_debt_receipt_upload_and_rejection_do_not_change_credit(self):
        self.prepare();self.create();response=self.client.post(self.path,data={'csrf':self.csrf_token,'reference':'a'*32,'action':'receipt','amount':'200000','card_id':'primary','receipt':(io.BytesIO(fixture.jpeg()),'receipt.jpg')})
        self.assertEqual(response.status_code,302)
        row=self.features.RenewalRequest.query.one();self.assertEqual(row.source,'reseller_debt');self.assertEqual(self.features.ReceiptGrant.query.count(),0)
        self.admin();self.assertEqual(self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'rejected'}).status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,200000)
    @patch.dict('os.environ',{'BEENY_BALEPAY_SECRET':'x'*40,'BEENY_BALEPAY_WORDPRESS_URL':'https://payment.example.com'})
    def test_bale_debt_payment_uses_existing_signed_order_and_is_idempotent(self):
        self.prepare();self.create()
        response=self.client.post('/panel/c/'+self.token+'/balepay/debt/start',data={'csrf':self.csrf_token,'amount':'200000'})
        self.assertEqual(response.status_code,303);order=panel.balepay_orders.query.one()
        self.assertEqual(self.signed_confirm(order).status_code,200);self.assertEqual(self.signed_confirm(order).status_code,200)
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(self.features.RenewalRequest.query.one().source,'reseller_debt')
    def test_statement_is_scoped_frozen_and_csv_is_private(self):
        self.prepare();self.create();self.earning()
        response=self.client.post(self.path+'/statements?period=week',data={'csrf':self.csrf_token,'reference':'a'*32})
        self.assertEqual(response.status_code,302);row=self.credit.Statement.query.one();original=row.payload
        self.assertEqual(self.client.get(response.location).status_code,200)
        self.assertEqual(self.client.get(response.location+'?format=csv').status_code,200)
        a=self.credit.Account.query.one();a.debt=0;self.db.session.commit();self.assertEqual(row.payload,original)
        self.assertEqual(json.loads(row.payload)['current_debt'],200000)
        self.assertEqual(self.client.get('/panel/c/'+'B'*43+'/reseller/credit/statements/'+str(row.id)).status_code,404)
    def test_owner_registration_and_separate_login_are_password_protected(self):
        self.prepare();self.admin()
        response=self.client.post('/panel/settings/representative-credit',data={'csrf':self.csrf_token,'action':'register','username':'pro-representative','password':'Private-representative-password','credit_limit':'500000','nodes':[self.node.id]})
        self.assertEqual(response.status_code,302);u=panel.User.query.filter_by(username='pro-representative').one()
        a=self.db.session.get(self.credit.Account,u.id);self.assertEqual(a.credit_limit,500000);self.assertEqual(a.debt,0)
        self.assertEqual(self.client.get('/panel/settings/representative-credit').status_code,200)
        with self.client.session_transaction() as sess:sess.pop('customer_auth',None)
        self.assertEqual(self.client.get('/panel/representatives/login').status_code,200)
        self.assertEqual(self.client.post('/panel/representatives/login',data={'csrf':self.csrf_token,'username':u.username,'password':'wrong'}).status_code,401)
        response=self.client.post('/panel/representatives/login',data={'csrf':self.csrf_token,'username':u.username,'password':'Private-representative-password'})
        self.assertEqual(response.status_code,302);self.assertIn('/reseller/credit',response.location)
        self.assertEqual(self.client.get(response.location).status_code,200)
    def test_owner_controls_and_lower_limit_rejection(self):
        self.prepare();self.create();self.admin()
        url='/panel/settings/representative-credit'
        self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'action':'configure','reseller_id':self.user.id,'credit_limit':'100000','enabled':'1'}).status_code,400)
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'action':'suspend','reseller_id':self.user.id,'reason':'other'}).status_code,302)
        self.assertEqual(self.credit.Account.query.one().suspended_reason,'other')
        self.assertEqual(self.credit.Account.query.one().debt,200000)
    def test_cash_wallet_payment_is_not_new_income_and_cannot_double_spend(self):
        self.prepare();self.create();wallet=self.db.session.get(panel.commerce.Wallet,self.user.id);wallet.balance=100000;self.db.session.commit()
        data={'csrf':self.csrf_token,'action':'cash_offset','reference':'b'*32,'amount':'70000'}
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(self.path,data=data).status_code,302);self.assertEqual(self.client.post(self.path,data=data).status_code,302)
        self.assertEqual(wallet.balance,30000);self.assertEqual(self.credit.Account.query.one().debt,130000)
        self.assertEqual(self.c.Earning.query.count(),0)
        self.assertEqual(self.client.post(self.path,data={**data,'reference':'e'*32,'amount':'40000'}).status_code,409)
        self.assertEqual(wallet.balance,30000);self.assertEqual(self.credit.Account.query.one().debt,130000)
    def test_cancellation_after_repayment_credits_cash_without_losing_paid_money(self):
        self.prepare()
        with patch('resellers.subprocess.run',side_effect=RuntimeError('fail')),patch('app.sync_primary_access'):
            self.client.post(self.path,data={'csrf':self.csrf_token,'action':'create','reference':'c'*32,'username':'credit-child','password':'Private-credit-password-123','plan_id':'monthly','node_id':self.node.id})
        row=self.debt_request();self.approve(row);self.admin();order=panel.resellers.Order.query.one()
        response=self.client.post('/panel/settings/resellers',data={'csrf':self.csrf_token,'action':'refund','order_id':order.id})
        self.assertEqual(response.status_code,302);self.assertEqual(order.state,'cancelled')
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,200000)
        self.assertEqual(self.client.post('/panel/settings/resellers',data={'csrf':self.csrf_token,'action':'refund','order_id':order.id}).status_code,409)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,200000)
    def test_refund_after_income_offset_claws_back_used_income_and_preserves_debt(self):
        self.prepare();self.create();e=self.earning(70000)
        with patch.object(panel.experience,'sync_access',return_value=[]):
            self.client.post(self.path,data={'csrf':self.csrf_token,'action':'offset','reference':'f'*32,'amount':'40000'})
        self.admin()
        with patch.object(panel.experience,'sync_access',return_value=[]):
            response=self.client.post('/panel/settings/commissions',data={'csrf':self.csrf_token,'action':'refund','earning_id':e.id,'payment_reference':'bank-refund-123','reason':'Actual refund completed'})
        self.assertEqual(response.status_code,302);self.assertEqual(e.state,'reversed')
        self.assertEqual(self.c.sums(self.user.id)['available'],-40000)
        self.assertEqual(self.credit.Account.query.one().debt,160000)
    def test_login_rate_limit_and_owner_only_registration(self):
        self.prepare();url='/panel/representatives/login'
        for _ in range(10):self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'username':'missing','password':'wrong'}).status_code,401)
        self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'username':'missing','password':'wrong'}).status_code,429)
        self.assertEqual(self.client.get('/panel/settings/representative-credit').status_code,302)
    def test_credit_model_opt_in_does_not_reset_old_wallet_or_commissions(self):
        self.prepare();self.admin();wallet=self.db.session.get(panel.commerce.Wallet,self.user.id);wallet.balance=90000;e=self.earning(70000)
        response=self.client.post('/panel/settings/representative-credit',data={'csrf':self.csrf_token,'action':'configure','reseller_id':self.user.id,'credit_limit':'2000000','enabled':'1'})
        self.assertEqual(response.status_code,302);self.assertEqual(wallet.balance,90000);self.assertEqual(e.amount,70000);self.assertEqual(e.state,'available')
    def test_additive_offset_migration_preserves_original_money_and_status(self):
        from sqlalchemy import text
        from migrations import upgrade
        self.prepare()
        self.db.session.execute(text('DROP TABLE commission_earnings'));self.db.session.execute(text("CREATE TABLE commission_earnings (id INTEGER PRIMARY KEY, reference TEXT, reseller_id INTEGER, user_id INTEGER, username TEXT, amount BIGINT, sale_amount BIGINT, base_amount BIGINT, snapshot TEXT, state TEXT, settlement_id INTEGER, created_at DATETIME)"))
        self.db.session.execute(text("INSERT INTO commission_earnings VALUES (7,'legacy',1,2,'Legacy',50000,250000,200000,'{}','available',NULL,'2026-10-01')"));self.db.session.commit()
        upgrade(self.db);upgrade(self.db)
        row=self.db.session.execute(text('SELECT amount,state,offset_used FROM commission_earnings WHERE id=7')).one()
        self.assertEqual(tuple(row),(50000,'available',0))
    def test_simultaneous_offsets_cannot_spend_the_same_commission(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.prepare();self.create();self.earning(70000)
        cookie=self.client.get_cookie('session').value;barrier=Barrier(2);path=self.path;csrf=self.csrf_token
        def pay(i):
            client=panel.app.test_client();client.set_cookie('session',cookie);barrier.wait()
            return client.post(path,data={'csrf':csrf,'action':'offset','reference':str(i)*32,'amount':'50000'}).status_code
        with patch.object(panel.experience,'sync_access',return_value=[]),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(pay,[1,2]))
        self.db.session.expire_all()
        self.assertEqual(sorted(results),[302,409])
        self.assertEqual(self.credit.Account.query.one().debt,150000)
        self.assertEqual(self.c.sums(self.user.id)['available'],20000)
        self.assertEqual(self.credit.Entry.query.filter_by(kind='offset').count(),1)
    def test_simultaneous_creation_cannot_overdraw_initial_credit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.prepare();a=self.credit.Account.query.one();a.credit_limit=200000;self.db.session.commit()
        cookie=self.client.get_cookie('session').value;barrier=Barrier(2);path=self.path;csrf=self.csrf_token;nid=self.node.id
        def issue(i):
            client=panel.app.test_client();client.set_cookie('session',cookie);barrier.wait()
            return client.post(path,data={'csrf':csrf,'action':'create','reference':str(i)*32,'username':'credit-'+str(i),'password':'Private-credit-password-123','plan_id':'monthly','node_id':nid}).status_code
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(issue,[1,2]))
        self.db.session.expire_all();self.assertEqual(sorted(results),[302,409])
        self.assertEqual(self.credit.Account.query.one().debt,200000);self.assertEqual(self.credit.Margin.query.count(),1)
    def test_owner_can_issue_period_statement_and_rep_cannot_read_another(self):
        self.prepare();self.create();self.admin()
        response=self.client.post('/panel/settings/representative-credit/'+str(self.user.id)+'/statements?period=month',data={'csrf':self.csrf_token,'reference':'b'*32})
        self.assertEqual(response.status_code,302);row=self.credit.Statement.query.one()
        self.assertEqual(json.loads(row.payload)['initial_orders'][0]['base'],200000)
        self.assertEqual(self.client.get(response.location).status_code,200)
        self.assertEqual(self.client.get('/panel/settings/representative-credit?reseller_id='+str(self.user.id)).status_code,200)
        self.assertEqual(self.client.get('/panel/representatives/login').status_code,200)
    def test_refund_report_does_not_count_clawback_as_a_second_income_reversal(self):
        self.prepare();self.create();e=self.earning(70000)
        with patch.object(panel.experience,'sync_access',return_value=[]):self.client.post(self.path,data={'csrf':self.csrf_token,'action':'offset','reference':'f'*32,'amount':'40000'})
        self.admin()
        with patch.object(panel.experience,'sync_access',return_value=[]):self.client.post('/panel/settings/commissions',data={'csrf':self.csrf_token,'action':'refund','earning_id':e.id,'payment_reference':'bank-refund-123','reason':'Actual refund completed'})
        response=self.client.post(self.path+'/statements?period=month',data={'csrf':self.csrf_token,'reference':'b'*32})
        self.assertEqual(response.status_code,302);data=json.loads(self.credit.Statement.query.one().payload)
        self.assertEqual(data['renewal_margin'],0);self.assertEqual(data['commission_refunds'],70000)
        self.assertEqual(data['available_income'],-40000);self.assertEqual(data['offset'],40000)
    def test_owner_audit_does_not_commit_a_failed_debt_approval(self):
        self.prepare();self.create();row=self.debt_request();a=self.credit.Account.query.one();a.debt=50000
        wallet=self.db.session.get(panel.commerce.Wallet,self.user.id);wallet.balance=10000000000;self.db.session.commit();self.admin()
        response=self.client.post('/panel/renewals/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'completed'})
        self.assertEqual(response.status_code,409);self.db.session.expire_all()
        self.assertEqual(row.status,'pending');self.assertEqual(a.debt,50000);self.assertEqual(wallet.balance,10000000000)
        self.assertEqual(self.credit.Entry.query.filter_by(kind='payment').count(),0)
    def test_failed_owner_statement_cannot_leave_an_empty_snapshot(self):
        self.prepare();self.admin()
        response=self.client.post('/panel/settings/representative-credit/'+str(self.user.id)+'/statements?period=custom&from=2026-10-13&to=2020-01-01',data={'csrf':self.csrf_token,'reference':'a'*32})
        self.assertEqual(response.status_code,400);self.assertEqual(self.credit.Statement.query.count(),0)
    def test_credit_conversion_requires_resolving_existing_paid_sales(self):
        self.prepare();a=self.credit.Account.query.one();a.enabled=False;self.db.session.commit()
        self.assertEqual(commission_fixture.CommissionTests.submit(self).status_code,302)
        self.admin();response=self.client.post('/panel/settings/representative-credit',data={'csrf':self.csrf_token,'action':'configure','reseller_id':self.user.id,'enabled':'1','credit_limit':'1000000'})
        self.assertEqual(response.status_code,409);self.db.session.expire_all();self.assertFalse(a.enabled)
    def test_stale_working_credit_order_recovers_without_reborrowing(self):
        from datetime import timedelta
        self.prepare()
        with patch('resellers.subprocess.run',side_effect=RuntimeError('fail')),patch('app.sync_primary_access'):
            self.client.post(self.path,data={'csrf':self.csrf_token,'action':'create','reference':'c'*32,'username':'credit-child','password':'Private-credit-password-123','plan_id':'monthly','node_id':self.node.id})
        order=panel.resellers.Order.query.one();order.state='working';order.updated_at=datetime.utcnow()-timedelta(minutes=6);self.db.session.commit()
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):self.credit.cycle()
        self.assertEqual(order.state,'completed');self.assertEqual(self.credit.Account.query.one().debt,200000)
        self.assertEqual(self.credit.Entry.query.filter_by(kind='issue').count(),1)
