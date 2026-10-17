import json,unittest,secrets
from unittest.mock import patch
import test_representative_credit as fixture
from test_customer import panel,jpeg
class RepresentativeCatalogTests(unittest.TestCase):
    setUp=fixture.RepresentativeCreditTests.setUp
    tearDown=fixture.RepresentativeCreditTests.tearDown
    csrf=fixture.RepresentativeCreditTests.csrf
    configure=fixture.RepresentativeCreditTests.configure
    enable=fixture.RepresentativeCreditTests.enable
    admin=fixture.RepresentativeCreditTests.admin
    prepare=fixture.RepresentativeCreditTests.prepare
    create=fixture.RepresentativeCreditTests.create
    def tariff(self):
        self.prepare();self.catalog=panel.representative_catalog
        row=self.catalog.CustomPolicy(reseller_id=self.user.id,enabled=True,base=10000,per_gb=1000,per_day=2000,per_device=40000,max_percent=50,sale_percent=25)
        self.db.session.add(row);self.db.session.commit();return row
    def test_custom_creation_books_base_and_ignores_client_price(self):
        self.tariff()
        response=self.create(plan_id='custom',custom_days='30',custom_quota='100',custom_devices='2',price='1',commission_base='1')
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.credit.Account.query.one().debt,210000)
        memo=self.credit.Margin.query.one();self.assertEqual((memo.base_amount,memo.sale_amount),(210000,262500))
        child=panel.User.query.filter_by(username='credit-child').one();self.assertEqual((child.traffic_limit,child.max_devices),(100,2))
    def test_custom_quote_is_scoped_and_validated(self):
        row=self.tariff();url=self.path+'/quote';data={'csrf':self.csrf_token,'custom_days':'30','custom_quota':'100','custom_devices':'2'}
        response=self.client.post(url,data=data);self.assertEqual(response.status_code,200);self.assertEqual(response.json['price'],262500)
        data['custom_quota']='-1';self.assertEqual(self.client.post(url,data=data).status_code,400)
        row.enabled=False;self.db.session.commit();data['custom_quota']='100';self.assertEqual(self.client.post(url,data=data).status_code,400)
    def test_representative_markup_is_bounded_by_owner(self):
        row=self.tariff();url=self.path+'/custom-markup'
        self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'sale_percent':'51'}).status_code,400);self.assertEqual(row.sale_percent,25)
        self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'sale_percent':'40'}).status_code,200);self.assertEqual(row.sale_percent,40)
        self.credit.Account.query.one().locked=True;self.db.session.commit();self.assertEqual(self.client.post(url,data={'csrf':self.csrf_token,'sale_percent':'1'}).status_code,403)
    def test_owner_adds_plan_to_existing_catalog_and_selected_representative(self):
        self.prepare();self.admin();uid=self.user.id
        fields={'csrf':self.csrf_token,'action':'add_plan','reseller_id':uid,'reference':'e'*32,'title':'پلن جدید','title_en':'New plan','days':45,'quota':150,'devices':2,'price':230000,'maximum':330000,'quota_mode':'metered'}
        before=len(self.features.settings()['plans']);url='/panel/settings/representative-credit/catalog'
        self.assertEqual(self.client.post(url,data=fields).status_code,302)
        self.assertEqual(len(self.features.settings()['plans']),before+1)
        pid='p-'+'e'*20;rate=self.db.session.get(panel.commissions.Rate,(uid,pid));self.assertEqual((rate.base_price,rate.maximum,rate.sale_price),(230000,330000,230000))
        self.assertEqual(self.client.post(url,data=fields).status_code,302);self.assertEqual(len(self.features.settings()['plans']),before+1)
        self.assertEqual(self.create(plan_id=pid).status_code,302);self.assertEqual(self.credit.Account.query.one().debt,230000)
    def test_owner_language_defaults_english_and_switches_only_this_section(self):
        self.prepare();self.admin();url='/panel/settings/representative-credit'
        page=self.client.get(url).get_data(as_text=True);self.assertIn('Representative credit &amp; management',page)
        response=self.client.post(url+'/language',data={'csrf':self.csrf_token,'language':'fa','tab':'prices','reseller_id':self.user.id})
        self.assertEqual(response.status_code,302)
        page=self.client.get(response.location).get_data(as_text=True);self.assertIn('اعتبار و مدیریت نمایندگی',page);self.assertIn('dir="rtl" lang="fa"',page)
        with self.client.session_transaction() as session:self.assertNotIn('customer_language',session)
    def test_support_keeps_representative_navigation_for_list_new_and_thread(self):
        self.prepare();root='/panel/c/'+self.token+'/tickets'
        response=self.client.post(root,data={'csrf':self.csrf_token,'subject':'Help','message':'Please help with an account'})
        self.assertEqual(response.status_code,302)
        for url in [root,root+'/new',response.location]:
            page=self.client.get(url).get_data(as_text=True)
            self.assertIn('shell-nav rep-nav',page)
            self.assertIn('/reseller/credit/debt',page)
            self.assertNotIn('href="/panel/c/'+self.token+'#configs"',page)
    def test_customer_custom_renewal_uses_representative_base_and_retail(self):
        self.tariff();self.create(plan_id='custom',custom_days='30',custom_quota='100',custom_devices='2')
        child=panel.User.query.filter_by(username='credit-child').one()
        plan=self.catalog.customer_quote(child,'30','100','2');selected=panel.commissions.customer_plan(child,plan)
        self.assertEqual((selected['price'],selected['commission_base']),(262500,210000))
        cfg=panel.commissions.customer_settings(child,self.features.settings());self.assertTrue(cfg['custom_pricing']['enabled'])
        row=self.features.create_request(child,'custom',jpeg(),'Customer','Contact',custom={'days':'30','quota':'100','devices':'2'},card_id='primary')
        self.assertEqual(json.loads(row.plan)['commission_amount'],52500)
    def test_successful_credit_creation_queues_named_manager_alert_once(self):
        self.prepare();self.create();self.create()
        alerts=panel.commissions.Alert.query.filter_by(reference='rep-account:'+'c'*32).all()
        self.assertEqual(len(alerts),1);self.assertIn(self.user.username,alerts[0].body);self.assertIn('credit-child',alerts[0].body)
        cfg=self.features.settings();self.features.set_setting('admin_chat_id','123456');self.db.session.commit()
        with patch.object(self.features,'telegram',return_value={}) as telegram:
            panel.commissions.deliver_alerts();panel.commissions.deliver_alerts()
            self.assertEqual(telegram.call_count,1)
            self.assertIn(self.user.username,telegram.call_args.args[1]['text'])
    def test_failed_provision_does_not_emit_success_notification(self):
        self.prepare()
        with patch('resellers.subprocess.run',side_effect=RuntimeError('failed')),patch('app.sync_primary_access'):
            self.client.post(self.path,data={'csrf':self.csrf_token,'action':'create','reference':'c'*32,'username':'credit-child','password':'Safe-password-123','plan_id':'monthly','node_id':self.node.id})
        self.assertEqual(panel.commissions.Alert.query.filter_by(reference='rep-account:'+'c'*32).count(),0)
    def test_support_error_keeps_representative_menu(self):
        self.prepare();response=self.client.get('/panel/c/'+self.token+'/tickets/99999')
        self.assertEqual(response.status_code,404)
        page=response.get_data(as_text=True);self.assertIn('shell-nav rep-nav',page)
        self.assertNotIn('href="/panel/c/'+self.token+'#configs"',page)
    def test_customer_settings_save_keeps_added_catalog_plan(self):
        self.prepare();self.admin();url='/panel/settings/representative-credit/catalog'
        self.client.post(url,data={'csrf':self.csrf_token,'action':'add_plan','reseller_id':self.user.id,'reference':'e'*32,'title':'Extra','title_en':'Extra','days':45,'quota':150,'devices':2,'price':230000,'maximum':330000})
        plans=self.features.settings()['plans'];pid='p-'+'e'*20
        fields={'csrf':self.csrf_token,'pricing_base':0,'pricing_per_gb':0,'pricing_per_day':0,'pricing_per_device':0}
        for plan in plans:
            for key in ['title','title_en','days','quota','devices','price','quota_mode','throttle_down_kbps','throttle_up_kbps']:
                fields[plan['id']+'_'+key]=plan.get(key,'')
        fields[pid+'_price']=240000
        response=self.client.post('/panel/settings/customer',data=fields)
        self.assertEqual(response.status_code,302)
        stored=next(p for p in self.features.settings()['plans'] if p['id']==pid)
        self.assertEqual(stored['price'],240000)
        self.assertEqual(len(self.features.settings()['plans']),len(plans))
