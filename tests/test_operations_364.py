import json,unittest,tempfile,importlib.util
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from sales_engine import category
from terminal_traffic import merge_events,read_events,acknowledge
from session_limits import enforce
from admission import node_token
import test_customer as fixture
from test_customer import panel

class FinanceAndAdmissionTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def node(self):
        node=panel.Node(name='Main',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node);panel.db.session.commit();return node
    def sale(self,**extra):
        node=self.node();self.admin()
        fields=dict(username='direct-new',protocol='openvpn',nodes=str(node.id),sale_mode='catalog',sale_plan='single',sale_payment='unpaid',max_devices='99',traffic_limit='999',expire_days='999')
        fields.update(extra)
        # Pick a real, server-side catalog plan, independent of its title.
        if fields['sale_plan']=='single':fields['sale_plan']=panel.customer_features.settings()['plans'][0]['id']
        with patch('app.subprocess.run'),patch('app.sync_primary_access'):
            return self.client.post('/panel/users/add',data=fields)
    def test_catalog_sale_uses_server_terms_and_records_unpaid_invoice(self):
        response=self.sale();self.assertEqual(response.status_code,302)
        row=panel.commerce.Invoice.query.one();user=panel.User.query.filter_by(username='direct-new').one()
        plan=panel.customer_features.settings()['plans'][0]
        self.assertEqual((row.amount,user.traffic_limit,user.max_devices),(plan['price'],plan['quota'],plan['devices']))
        self.assertEqual(row.payment_state,'unpaid');self.assertEqual(panel.sales_engine.Receipt.query.count(),0)
        body=self.client.get('/panel/settings/sales');self.assertEqual(body.status_code,200);self.assertIn(b'1 invoices',body.data)
    def test_manual_formula_and_paid_reference_only_once(self):
        panel.customer_features.set_setting('custom_pricing',json.dumps(dict(enabled=True,base=10000,per_day=2000,per_gb=1000,per_device=5000)));panel.db.session.commit()
        response=self.sale(sale_mode='manual',expire_days='30',traffic_limit='100',max_devices='2',sale_payment='paid',sale_bank_reference='bank-unique-001')
        self.assertEqual(response.status_code,302)
        row=panel.commerce.Invoice.query.one();self.assertEqual(row.amount,175000)
        self.assertEqual(panel.sales_engine.Receipt.query.one().amount,175000)
        csrf=self.client.get('/panel/settings/sales').status_code
        with self.client.session_transaction() as session:token=session['_customer_csrf']
        response=self.client.post('/panel/settings/sales/invoices/'+str(row.id)+'/paid',data={'csrf':token,'bank_reference':'bank-unique-001'})
        self.assertEqual(response.status_code,302);self.assertEqual(panel.sales_engine.Receipt.query.count(),1)
    def test_invalid_custom_tariff_never_provisions(self):
        self.admin();node=self.node()
        with patch('app.subprocess.run') as run:
            response=self.client.post('/panel/users/add',data=dict(username='not-built',protocol='openvpn',nodes=str(node.id),sale_mode='manual',expire_days='30',traffic_limit='100',max_devices='1'))
        self.assertEqual(response.status_code,400);run.assert_not_called();self.assertEqual(panel.commerce.Invoice.query.count(),0)
    def test_retained_approved_receipt_backfill_idempotent_and_wallet_not_double_cash(self):
        R=panel.customer_features.RenewalRequest
        for ref,source in [('paid-reference','web'),('wallet-reference','wallet')]:
            panel.db.session.add(R(user_id=self.user.id,username=self.user.username,source=source,status='completed',billing_reference=ref,plan=json.dumps(dict(price=250000)),receipt='',reviewed_at=datetime.utcnow()))
        panel.db.session.commit();panel.sales_engine.backfill();panel.sales_engine.backfill()
        self.assertEqual(panel.sales_engine.Receipt.query.count(),1)
        self.assertEqual(panel.sales_engine.Receipt.query.one().amount,250000)
    def test_scoped_admin_cannot_read_or_edit_another_node_account(self):
        self.admin();admin=panel.Admin.query.first();admin.role='support';admin.node_scope=True
        a=self.node();b=panel.Node(name='Other',ip='192.0.2.2',api_key='other-node');panel.db.session.add(b);panel.db.session.flush()
        panel.db.session.add(panel.security.AdminNodeGrant(admin_id=admin.id,node_id=a.id))
        panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=b.id));panel.db.session.commit()
        from flask import g
        g.pop('_login_user',None)
        response=self.client.get('/panel/users/view/'+str(self.user.id))
        self.assertEqual(response.status_code,404)
        g.pop('_login_user',None)
        self.assertEqual(self.client.get('/panel/settings/sales').status_code,403)
    def test_global_admission_rejects_extra_and_releases_on_disconnect(self):
        a=self.node();b=panel.Node(name='England',ip='192.0.2.2',api_key='other-node');panel.db.session.add(b);panel.db.session.flush()
        for node in (a,b):
            panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.add(panel.admission.Snapshot(node_id=node.id,checked_at=datetime.utcnow()))
        self.user.max_devices=1;panel.db.session.commit()
        def call(node,peer,action='connect',secret=None):
            return self.client.post('/panel/api/vpn/admission',json=dict(node_id=node.id,name=self.user.username,address=peer,since='1792000000',action=action),headers={'Authorization':'Bearer '+(secret or node_token(panel.app.secret_key,node.id))})
        self.assertEqual(call(a,'192.0.2.40:5000').status_code,200)
        self.assertEqual(call(a,'192.0.2.40:5000').status_code,200)
        self.assertEqual(call(b,'192.0.2.41:5000').status_code,403)
        self.assertEqual(call(a,'192.0.2.40:5000','disconnect').status_code,200)
        self.assertEqual(call(b,'192.0.2.41:5000').status_code,200)
        self.assertEqual(call(b,'192.0.2.42:5000',secret='invalid').status_code,403)
    def test_stale_node_or_disabled_account_cannot_admit(self):
        node=self.node();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        headers={'Authorization':'Bearer '+node_token(panel.app.secret_key,node.id)}
        data=dict(node_id=node.id,name=self.user.username,address='192.0.2.42:5000',since='1792000000',action='connect')
        self.assertEqual(self.client.post('/panel/api/vpn/admission',json=data,headers=headers).status_code,503)
        self.user.status='disabled';panel.db.session.commit()
        self.assertEqual(self.client.post('/panel/api/vpn/admission',json=data,headers=headers).status_code,403)

class PureOperationsTests(unittest.TestCase):
    def test_legacy_sales_classification(self):
        self.assertEqual(category({'representative_id':9}),'representative')
        self.assertEqual(category({},'reseller-renew:abc'),'representative')
        self.assertEqual(category({'commission_reseller':False}),'direct')
    def test_terminal_total_reuses_sample_key_and_ack_is_confined(self):
        sample='alice|192.0.2.1:5000|100|7'
        events=[dict(username='alice',address='192.0.2.1:5000',since='100',received=1000,sent=2000)]
        merged,terminal=merge_events([],events,[sample]);self.assertEqual(merged[0][1],sample);self.assertEqual(merged[0][2:4],(1000,2000));self.assertEqual(terminal,{sample})
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/('a'*64+'.json');p.write_text(json.dumps(events[0]))
            self.assertEqual(len(read_events(Path(root))),1)
            with self.assertRaises(ValueError):acknowledge(['../bad'],Path(root))
            self.assertTrue(p.exists());acknowledge(['a'*64],Path(root));self.assertFalse(p.exists())
    def test_only_newest_excess_session_is_disconnected(self):
        node=SimpleNamespace(id=1);rows=[dict(id=str(i),fingerprint='a'*64,connected_epoch=i) for i in (1,2,3)]
        kill=Mock();self.assertEqual(enforce(SimpleNamespace(max_devices=2),[node],['alice'],lambda n:True,lambda name:rows,kill),[])
        kill.assert_called_once_with('alice','3','a'*64)
    def test_core_preview_preserves_keys_and_refuses_hook_overwrite(self):
        path=Path(__file__).resolve().parents[1]/'scripts/configure_vpn_core.py';spec=importlib.util.spec_from_file_location('core364',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.configure('port 110\nproto tcp\nkey /etc/openvpn/server.key\nmanagement 127.0.0.1 7505\n',admission=True)
        for text in ['disable-dco','crl-verify','block-ipv6','key /etc/openvpn/server.key','management /run/openvpn/','client-connect']:self.assertIn(text,result)
        with self.assertRaises(ValueError):module.configure('client-connect /existing/hook\n')

class AdditionalRegressionTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_startup_speed_failure_never_disables_valid_customer(self):
        node=panel.Node(name='Main',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        with patch.object(panel.speed_policy,'sync',return_value=['Main']),patch('app.sync_primary_access') as access:
            panel.reconcile_primary_access()
        access.assert_called_once_with(self.user,True);self.assertEqual(self.user.status,'active');self.assertTrue(self.user.pause_sync_pending)
    def test_expired_account_propagates_persistent_block_to_remote_node(self):
        node=panel.Node(name='England',ip='192.0.2.2',host='https://node.example.com',api_key='remote-key');panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));self.user.status='disabled';self.user.expire_date='2020-01-01';panel.db.session.commit()
        with patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',return_value=[]),patch('cluster.set_user_state_on_node',return_value=(True,'')) as state:
            panel.disable_user_globally(self.user)
        state.assert_called_once_with(node,self.user.username,False)
    def test_negative_cash_month_keeps_refund_visible_and_no_new_sales(self):
        from financial_reporting import report
        self.admin();panel.sales_engine.receipt('seed',self.user.id,'direct',100,'manual')
        panel.db.session.add(panel.commissions.Refund(amount=150,payment_reference='bank-refund-unique',reason='Verified refund',admin_id=panel.Admin.query.first().id));panel.db.session.commit()
        with panel.app.test_request_context():
            from flask_login import login_user
            login_user(panel.Admin.query.first())
            rows=report(panel.db,panel.commerce.Invoice.query,panel.commerce.Invoice,panel.sales_engine.Receipt,panel.commissions,panel.customer_features,datetime.utcnow())
        self.assertEqual((rows[-1]['cash'],rows[-1]['refund'],rows[-1]['total']),(100,150,-50));self.assertGreater(rows[-1]['total_height'],0)

class CertificateIndexTests(unittest.TestCase):
    def test_revocation_covers_old_renewed_serials_but_not_similar_names(self):
        path=Path(__file__).resolve().parents[1]/'scripts/vpn_maintenance.py';spec=importlib.util.spec_from_file_location('pki364',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        lines='V\t291001000000Z\t\t01\tunknown\t/CN=alice\nV\t291001000000Z\t\t02\tunknown\t/CN=alice\nV\t291001000000Z\t\t03\tunknown\t/CN=alice2\n'
        rows=[row.split('\t') for row in module.revoke_all_serials(lines,'alice').splitlines()]
        self.assertEqual([row[0] for row in rows],['R','R','V']);self.assertTrue(rows[0][2].endswith('Z'))
