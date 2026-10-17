"""Delivery privacy, navigation, financial cancellation and archive boundaries."""
import json,secrets,unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash,check_password_hash
import test_representative_credit as fixture
from test_customer import panel

class RepresentativeExperienceTests(unittest.TestCase):
    setUp=fixture.RepresentativeCreditTests.setUp
    tearDown=fixture.RepresentativeCreditTests.tearDown
    csrf=fixture.RepresentativeCreditTests.csrf
    configure=fixture.RepresentativeCreditTests.configure
    enable=fixture.RepresentativeCreditTests.enable
    admin=fixture.RepresentativeCreditTests.admin
    prepare=fixture.RepresentativeCreditTests.prepare
    create=fixture.RepresentativeCreditTests.create
    earning=fixture.RepresentativeCreditTests.earning
    debt_request=fixture.RepresentativeCreditTests.debt_request
    approve=fixture.RepresentativeCreditTests.approve
    def ready(self):
        self.prepare();self.assertEqual(self.create().status_code,302)
        self.child=panel.User.query.filter_by(username='credit-child').one()
        self.a=panel.representative_actions
        self.childpath='/panel/c/'+self.token+'/reseller/users/'+str(self.child.id)
    def cancel(self):return self.client.post(self.childpath+'/cancel',data={'csrf':self.csrf_token,'reason':'Customer no longer wants this service'})
    def review(self,errors=None,action='approve'):
        self.admin();row=self.a.Cancellation.query.one()
        with patch.object(panel.experience,'sync_access',return_value=errors or []):
            return self.client.post('/panel/settings/representative-credit/cancellations/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':action,'review_note':'Reviewed usage and actual refund','customer_refund_reference':'CUSTOMER-RETURN-1'})
    def test_new_credentials_are_encrypted_and_copy_needs_no_password_input(self):
        self.ready();row=self.a.Credential.query.one()
        self.assertNotIn('Private-credit-password',row.encrypted)
        self.assertEqual(self.client.post(self.childpath+'/delivery',data={'csrf':self.csrf_token}).status_code,200)
        response=self.client.post(self.childpath+'/delivery',data={'csrf':self.csrf_token})
        self.assertIn('Private-credit-password-123',response.json['text'])
        self.assertIn('no-store',response.headers['Cache-Control'])
        page=self.client.get(self.path+'/accounts').get_data(as_text=True)
        self.assertNotIn('Private-credit-password-123',page)
        self.assertNotIn('data-current-password',page)
    def test_automatic_password_generation_without_client_password(self):
        self.prepare();self.assertEqual(self.create(password='').status_code,302)
        child=panel.User.query.filter_by(username='credit-child').one()
        url='/panel/c/'+self.token+'/reseller/users/'+str(child.id)+'/delivery'
        response=self.client.post(url,data={'csrf':self.csrf_token})
        self.assertEqual(response.status_code,200)
        password=response.json['text'].split('رمز ورود: ')[1].split('\n')[0]
        self.assertGreaterEqual(len(password),18)
        self.assertTrue(check_password_hash(self.db.session.get(self.features.CustomerProfile,child.id).password_hash,password))
    def test_legacy_or_changed_password_requires_explicit_reset(self):
        self.ready();profile=self.db.session.get(self.features.CustomerProfile,self.child.id)
        profile.password_hash=generate_password_hash('Customer-changed-password-123');old_version=profile.auth_version;self.db.session.commit()
        response=self.client.post(self.childpath+'/delivery',data={'csrf':self.csrf_token})
        self.assertEqual(response.status_code,409);self.assertTrue(response.json['reset_required'])
        self.assertTrue(check_password_hash(profile.password_hash,'Customer-changed-password-123'))
        response=self.client.post(self.childpath+'/delivery',data={'csrf':self.csrf_token,'reset':'1'})
        self.assertEqual(response.status_code,200);self.assertNotEqual(profile.auth_version,old_version)
        self.assertNotIn('Customer-changed-password',response.json['text'])
    def test_copy_requires_csrf_and_scope(self):
        self.ready();self.assertEqual(self.client.post(self.childpath+'/delivery').status_code,400)
        self.assertEqual(self.client.post('/panel/c/'+self.token+'/reseller/users/'+str(self.other.id)+'/delivery',data={'csrf':self.csrf_token}).status_code,404)
    def test_each_section_renders_and_debt_is_not_under_creation(self):
        self.ready()
        for section in ['overview','create','accounts','debt','income','prices','reports','cancellations']:
            response=self.client.get(self.path+'/'+section)
            self.assertEqual(response.status_code,200,section)
        overview=self.client.get(self.path).get_data(as_text=True)
        self.assertIn('icons/wave.svg',overview);self.assertIn('data-rep-counter',overview)
        creation=self.client.get(self.path+'/create').get_data(as_text=True)
        self.assertIn('partner-sales',creation);self.assertNotIn('id="debt-payment"',creation)
        self.assertEqual(self.client.get(self.path+'/invalid').status_code,404)
    def test_price_ajax_reuses_bounds_and_returns_json(self):
        self.prepare();url='/panel/c/'+self.token+'/reseller/commission'
        fields={'csrf':self.csrf_token,'action':'price','plan_id':'monthly','price':290000}
        response=self.client.post(url,data=fields,headers={'X-Requested-With':'XMLHttpRequest'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.json['ok'])
        self.assertEqual(self.db.session.get(self.c.Rate,(self.user.id,'monthly')).sale_price,290000)
        fields['price']=1
        self.assertEqual(self.client.post(url,data=fields,headers={'X-Requested-With':'XMLHttpRequest'}).status_code,400)
    def test_unified_admin_all_tabs_render_and_old_menus_removed(self):
        self.ready();self.admin()
        for tab in ['overview','register','manage','prices','nodes','receipts','payouts','orders','cancellations','reports']:
            response=self.client.get('/panel/settings/representative-credit?tab='+tab+'&reseller_id='+str(self.user.id))
            self.assertEqual(response.status_code,200,tab)
        page=response.get_data(as_text=True)
        self.assertIn('Representative credit &amp; management',page)
        self.assertNotIn('> Representatives</a>',page);self.assertNotIn('> Commissions</a>',page)
    def test_cancellation_request_is_scoped_and_does_not_move_money(self):
        self.ready();self.assertEqual(self.cancel().status_code,302);self.assertEqual(self.cancel().status_code,302)
        self.assertEqual(self.a.Cancellation.query.count(),1)
        self.assertEqual(self.credit.Account.query.one().debt,200000)
        self.assertEqual(self.credit.Margin.query.one().state,'completed')
        self.assertEqual(self.client.post('/panel/c/'+self.token+'/reseller/users/'+str(self.other.id)+'/cancel',data={'csrf':self.csrf_token,'reason':'Invalid account'}).status_code,404)
    def test_approved_full_cancellation_returns_base_once_and_keeps_renewal_income(self):
        self.ready();e=self.earning();self.cancel();before=(self.child.traffic_usage,self.child.expire_date)
        self.assertEqual(self.review().status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(self.credit.Margin.query.one().state,'refunded')
        self.assertEqual(e.state,'available');self.assertEqual(e.amount,50000)
        self.assertEqual(self.a.Cancellation.query.one().state,'completed')
        self.assertEqual((self.child.traffic_usage,self.child.expire_date),before)
        self.assertEqual(self.child.status,'disabled');self.assertIsNotNone(self.db.session.get(panel.User,self.child.id))
        self.assertEqual(self.review().status_code,302)
        self.assertEqual(self.credit.Entry.query.filter_by(kind='cancel').count(),1)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,0)
    def test_cancellation_after_principal_repaid_goes_to_cash_without_double_credit(self):
        self.ready();self.approve(self.debt_request());self.cancel();self.review()
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(self.credit.Account.query.one().credit_limit,1000000)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,200000)
        self.review();self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,200000)
    def test_financial_reversal_waits_for_confirmed_node_block(self):
        self.ready();self.cancel();self.review(errors=['England'])
        self.assertEqual(self.a.Cancellation.query.one().state,'applying')
        self.assertEqual(self.credit.Account.query.one().debt,200000)
        self.assertTrue(self.a.blocked(self.child))
        with patch.object(panel.experience,'sync_access',return_value=[]):self.a.cycle()
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(self.a.Cancellation.query.one().state,'completed')
    def test_pending_payment_and_cash_wallet_prevent_cancellation(self):
        self.ready();row=self.features.RenewalRequest(user_id=self.child.id,username=self.child.username,source='portal',plan='{}',receipt='',billing_reference=secrets.token_hex(16));self.db.session.add(row);self.db.session.commit()
        self.assertEqual(self.cancel().status_code,409);self.assertEqual(self.a.Cancellation.query.count(),0)
        row.status='rejected';self.db.session.add(panel.commerce.Wallet(user_id=self.child.id,balance=1000));self.db.session.commit()
        self.assertEqual(self.cancel().status_code,409)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.child.id).balance,1000)
    def test_archive_keeps_debt_profit_and_history_and_denies_direct_delete(self):
        self.ready()
        self.assertEqual(self.client.post(self.childpath+'/delete',data={'csrf':self.csrf_token}).status_code,409)
        with patch.object(panel.experience,'sync_access',return_value=[]):response=self.client.post(self.childpath+'/archive',data={'csrf':self.csrf_token})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,200000)
        self.assertEqual(self.credit.Margin.query.one().state,'completed')
        self.assertEqual(panel.resellers.Order.query.one().state,'archived')
        self.assertTrue(self.a.blocked(self.child))
    def test_rejected_cancellation_keeps_account_and_balance(self):
        self.ready();self.cancel();self.review(action='reject')
        self.assertEqual(self.child.status,'active');self.assertEqual(self.credit.Account.query.one().debt,200000)
        self.assertEqual(self.a.Cancellation.query.one().state,'rejected')
    def test_report_reversal_keeps_fulfilled_sale_and_zeroes_net_margin(self):
        self.ready();self.cancel();self.review();self.admin()
        self.client.post('/panel/settings/representative-credit/'+str(self.user.id)+'/statements',data={'csrf':self.csrf_token,'reference':'f'*32})
        statement=self.credit.Statement.query.one();report=json.loads(statement.payload)
        self.assertEqual(report['initial_count'],1)
        self.assertEqual(report['initial_margin'],0)
        self.assertEqual(report['initial_refunds'],250000)
    def test_owner_pending_order_cancellation_reuses_original_handler(self):
        self.prepare()
        with patch('resellers.subprocess.run',side_effect=RuntimeError('fail')),patch('app.sync_primary_access'):
            self.client.post(self.path,data={'csrf':self.csrf_token,'action':'create','reference':'c'*32,'username':'credit-child','password':'Private-credit-password-123','plan_id':'monthly','node_id':self.node.id})
        self.admin();order=panel.resellers.Order.query.one()
        response=self.client.post('/panel/settings/representative-credit?tab=orders',data={'csrf':self.csrf_token,'action':'pending_refund','order_id':order.id})
        self.assertEqual(response.status_code,302);self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(order.state,'cancelled')
    def test_repayment_and_withdrawal_history_is_scoped_and_paginated(self):
        self.ready();self.earning();self.debt_request(reference='d'*32)
        response=self.client.post('/panel/c/'+self.token+'/reseller/commission',data={'csrf':self.csrf_token,'action':'settlement','reference':'e'*32,'destination':'IR-private-bank-account'})
        self.assertEqual(response.status_code,302);self.assertTrue(response.location.endswith('/credit/income'))
        self.assertIn('درخواست‌های برداشت و تسویه شما',self.client.get(self.path+'/income').get_data(as_text=True))
        self.assertIn('IR-private-bank-account',self.client.get(self.path+'/income').get_data(as_text=True))
        debt=self.client.get(self.path+'/debt').get_data(as_text=True)
        self.assertIn('درخواست‌های واریز بدهی شما',debt);self.assertIn('200,000',debt)
        for i in range(13):
            self.db.session.add(self.features.RenewalRequest(user_id=self.user.id,username=self.user.username,source='reseller_debt',status='rejected',plan=json.dumps({'price':1000}),receipt='',billing_reference=secrets.token_hex(16)))
        self.db.session.commit();page=self.client.get(self.path+'/debt?page=2')
        self.assertEqual(page.status_code,200);self.assertIn('2 / 2',page.get_data(as_text=True))
    def test_private_debt_receipt_cannot_be_read_by_other_representative(self):
        from test_customer import jpeg
        self.ready();filename=self.features.store_image(jpeg());row=self.debt_request();row.receipt=filename;self.db.session.commit()
        response=self.client.get(self.path+'/payments/'+str(row.id)+'/receipt')
        self.assertEqual(response.status_code,200);self.assertIn('no-store',response.headers['Cache-Control'])
        row.user_id=self.other.id;self.db.session.commit()
        self.assertEqual(self.client.get(self.path+'/payments/'+str(row.id)+'/receipt').status_code,404)
    def test_online_debt_history_excludes_customer_purchases(self):
        self.ready()
        self.db.session.add(panel.balepay_orders(id='x'*32,user_id=self.user.id,plan_json=json.dumps({'kind':'reseller_debt'}),amount_irr=2000000,status='pending'))
        self.db.session.add(panel.balepay_orders(id='y'*32,user_id=self.user.id,plan_json=json.dumps({'kind':'subscription'}),amount_irr=2500000,status='pending'))
        self.db.session.commit();page=self.client.get(self.path+'/debt').get_data(as_text=True)
        self.assertIn('XXXXXXXX',page);self.assertNotIn('YYYYYYYY',page)
    def test_unresolved_online_payment_blocks_cancellation(self):
        self.ready();self.db.session.add(panel.balepay_orders(id='x'*32,user_id=self.child.id,plan_json='{}',amount_irr=2500000,status='superseded'));self.db.session.commit()
        self.assertEqual(self.cancel().status_code,409)
        self.assertEqual(self.credit.Account.query.one().debt,200000)
    def test_simultaneous_approvals_cannot_return_credit_twice(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.ready();self.cancel();self.admin()
        cid=self.a.Cancellation.query.one().id;cookie=self.client.get_cookie('session').value;barrier=Barrier(2);csrf=self.csrf_token
        def verify(i):
            client=panel.app.test_client();client.set_cookie('session',cookie);barrier.wait()
            return client.post('/panel/settings/representative-credit/cancellations/'+str(cid)+'/review',data={'csrf':csrf,'action':'approve','customer_refund_reference':'BANK-RETURN-1'}).status_code
        with patch.object(panel.experience,'sync_access',return_value=[]),ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(verify,[1,2]))
        self.assertIn(302,results);self.assertTrue(all(code in {302,409} for code in results),results)
        self.db.session.expire_all()
        self.assertEqual(self.credit.Account.query.one().debt,0)
        self.assertEqual(self.credit.Entry.query.filter_by(kind='cancel').count(),1)
        self.assertEqual(self.db.session.get(panel.commerce.Wallet,self.user.id).balance,0)
    def test_node_mask_blocks_archive_even_if_status_is_manually_changed(self):
        self.ready()
        with patch.object(panel.experience,'sync_access',return_value=[]):self.client.post(self.childpath+'/archive',data={'csrf':self.csrf_token})
        self.child.status='active';self.child.customer_paused=False;self.db.session.commit()
        with patch('app.sync_primary_access') as primary,patch('app.kick_user_globally'),patch('vpn_sessions.local_sessions',return_value=[]),patch.object(panel.speed_policy,'sync',return_value=[]):panel.experience.sync_access(self.child)
        self.assertFalse(primary.call_args.args[1])
    def test_unified_owner_price_policy_reuses_existing_validation(self):
        self.ready();self.admin()
        # Configured fixture has a single monthly plan.
        fields={'csrf':self.csrf_token,'action':'policy','reseller_id':self.user.id,'enabled':'1','minimum':20000,'base_monthly':220000,'max_monthly':350000,'plan_monthly':'1'}
        for plan in self.features.settings()['plans']:
            if plan['id']!='monthly':fields.update({'base_'+plan['id']:plan['price'],'max_'+plan['id']:plan['price']*2,'plan_'+plan['id']:'1'})
        response=self.client.post('/panel/settings/representative-credit?tab=prices',data=fields)
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.db.session.get(self.c.Rate,(self.user.id,'monthly')).base_price,220000)
    def test_pending_cancellation_denies_new_payment_and_preserves_wallet(self):
        from test_customer import jpeg
        self.ready();self.cancel()
        with self.assertRaises(ValueError):self.features.create_request(self.child,'monthly',jpeg(),'Name','Contact')
        self.assertEqual(self.features.RenewalRequest.query.filter_by(user_id=self.child.id).count(),0)
    def test_partial_sale_cancellation_reverses_proportion_and_retains_net_margin(self):
        self.ready();self.cancel();self.admin();row=self.a.Cancellation.query.one()
        with patch.object(panel.experience,'sync_access',return_value=[]):
            response=self.client.post('/panel/settings/representative-credit/cancellations/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'approve','refund_percent':'50','customer_refund_reference':'PARTIAL-RETURN-1'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,100000)
        self.assertEqual((row.base_refund,row.sale_refund,row.refund_percent),(100000,125000,50))
        self.assertEqual(self.credit.Margin.query.one().state,'partially_refunded')
        self.assertEqual(self.child.status,'disabled')
        response=self.client.post('/panel/settings/representative-credit/'+str(self.user.id)+'/statements',data={'csrf':self.csrf_token,'reference':'f'*32})
        self.assertEqual(response.status_code,302)
        self.assertEqual(json.loads(self.credit.Statement.query.one().payload)['initial_margin'],25000)
    def test_cancellation_outside_limits_requires_explicit_owner_exception(self):
        self.ready();self.child.traffic_usage=2;self.db.session.commit();self.cancel();self.admin();row=self.a.Cancellation.query.one()
        url='/panel/settings/representative-credit/cancellations/'+str(row.id)+'/review'
        values={'csrf':self.csrf_token,'action':'approve','customer_refund_reference':'OUTSIDE-LIMITS-1'}
        self.assertEqual(self.client.post(url,data=values).status_code,409)
        self.assertEqual(self.credit.Account.query.one().debt,200000);self.assertEqual(row.state,'pending')
        values.update(override='1',review_note='Owner verified the actual full refund')
        with patch.object(panel.experience,'sync_access',return_value=[]):self.assertEqual(self.client.post(url,data=values).status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,0)
    def test_owner_can_set_cancellation_limits(self):
        self.ready();self.admin()
        response=self.client.post('/panel/settings/representative-credit?tab=cancellations',data={'csrf':self.csrf_token,'action':'cancellation_policy','max_hours':24,'max_usage_gb':'0.25'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.features.get_setting('credit_cancel_max_hours'), '24')
        self.assertEqual(self.features.get_setting('credit_cancel_max_usage_gb'), '0.25')
    def test_one_refund_transfer_cannot_cancel_two_sales(self):
        self.ready();self.create(username='credit-child-two',reference='a'*32)
        other=panel.User.query.filter_by(username='credit-child-two').one()
        self.cancel();self.review()
        self.client.post('/panel/c/'+self.token+'/reseller/users/'+str(other.id)+'/cancel',data={'csrf':self.csrf_token,'reason':'Another cancellation'})
        row=self.a.Cancellation.query.filter_by(user_id=other.id).one()
        with patch.object(panel.experience,'sync_access',return_value=[]):
            response=self.client.post('/panel/settings/representative-credit/cancellations/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'approve','customer_refund_reference':'CUSTOMER-RETURN-1'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.credit.Account.query.one().debt,200000)
        self.assertEqual(row.state,'pending');self.assertEqual(other.status,'active')
    def test_english_representative_sections_render_with_correct_direction(self):
        self.ready()
        with self.client.session_transaction() as session:session['customer_language']='en'
        for section in ['overview','create','accounts','debt','income','prices','reports','cancellations']:
            response=self.client.get(self.path+'/'+section)
            self.assertEqual(response.status_code,200,section)
            self.assertIn('<html lang="en" dir="ltr">',response.get_data(as_text=True))
    def test_additive_tables_preserve_existing_credit_and_earnings(self):
        from migrations import upgrade
        self.ready();earning=self.earning()
        before=(self.credit.Account.query.one().debt,earning.amount,self.child.traffic_usage)
        upgrade(self.db)
        self.assertEqual((self.credit.Account.query.one().debt,earning.amount,self.child.traffic_usage),before)
        self.assertEqual(self.a.Credential.query.count(),1)
    def test_unified_legacy_sale_review_keeps_original_approval_flow(self):
        fixture.commission_fixture.CommissionTests.prepare(self)
        self.assertEqual(fixture.commission_fixture.CommissionTests.submit(self).status_code,302)
        row=self.c.Sale.query.one();self.admin()
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):
            response=self.client.post('/panel/settings/representative-credit/sales/'+str(row.id)+'/review',data={'csrf':self.csrf_token,'action':'approve'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(row.state,'completed')
        self.assertEqual(self.c.Earning.query.one().amount,50000)
        self.assertIn('commission-child',self.client.get('/panel/settings/representative-credit?tab=orders').get_data(as_text=True))
