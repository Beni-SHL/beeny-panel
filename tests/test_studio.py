"""New inbox privacy, coupon transactions and representative credit guarantees."""
import io,json,unittest
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel
class StudioTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    configure=fixture.CustomerFlowTests.configure
    def enable(self,balance=500000):
        local=panel.Node(name='Primary',ip='127.0.0.1',api_key=panel.PRIMARY_NODE_KEY)
        remote=panel.Node(name='Remote',ip='127.0.0.2',api_key='key')
        panel.db.session.add_all([local,remote]);panel.db.session.flush()
        panel.db.session.add(panel.resellers.Profile(user_id=self.user.id,enabled=True,base=10000,per_gb=1000,per_day=2000,per_device=40000))
        panel.db.session.add(panel.resellers.Grant(user_id=self.user.id,node_id=local.id))
        panel.db.session.add(panel.commerce.Wallet(user_id=self.user.id,balance=balance));panel.db.session.commit()
        self.node=local;self.remote=remote
    def fields(self):return dict(csrf=self.csrf(),reference='a'*32,username='reseller-child',password='Strong-child-password-123',days='30',quota='100',devices='1',node_id=str(self.node.id))
    def test_inboxes_have_separate_private_detail_and_owner_can_delete(self):
        csrf=self.csrf();root='/panel/c/'+self.token+'/tickets'
        self.client.post(root,data={'csrf':csrf,'subject':'Connection','message':'Please help'})
        row=panel.support.Ticket.query.one();url=root+'/'+str(row.id)
        self.assertEqual(self.client.get(url).status_code,200)
        other=panel.support.Ticket(user_id=self.other.id,username=self.other.username,subject='Private');panel.db.session.add(other);panel.db.session.commit()
        self.assertEqual(self.client.get(root+'/'+str(other.id)).status_code,404)
        self.assertIn(('tickets/'+str(row.id)).encode(),self.client.get(root).data)
        self.admin();self.assertEqual(self.client.get('/panel/tickets/'+str(row.id)).status_code,200)
        self.assertEqual(self.client.post('/panel/tickets/'+str(row.id)+'/delete').status_code,302)
        self.assertIsNone(panel.db.session.get(panel.support.Ticket,row.id));self.assertEqual(panel.support.Message.query.filter_by(ticket_id=row.id).count(),0)
    def test_coupon_preview_does_not_reserve_and_receipt_uses_discount(self):
        self.configure();csrf=self.csrf();coupon=panel.commerce.Coupon(code='SAVE20',percent=20,limit=1,expires='2099-01-01');panel.db.session.add(coupon);panel.db.session.commit()
        root='/panel/c/'+self.token+'/renew';data=dict(csrf=csrf,plan_id='monthly',coupon='SAVE20')
        result=self.client.post(root+'/quote',data=data);self.assertEqual(result.status_code,200);self.assertEqual(result.json['price'],200000);self.assertEqual(coupon.used,0)
        data.update(name='Customer',contact='Phone',card_id='primary',receipt=(io.BytesIO(fixture.jpeg()),'receipt.jpg'))
        self.assertEqual(self.client.post(root,data=data).status_code,302)
        self.assertEqual(json.loads(self.features.RenewalRequest.query.one().plan)['price'],200000);self.assertEqual(coupon.used,1)
    def test_invalid_coupon_leaves_no_receipt_or_reservation(self):
        self.configure();csrf=self.csrf();before=set(self.features.storage.glob('*'))
        response=self.client.post('/panel/c/'+self.token+'/renew',data=dict(csrf=csrf,plan_id='monthly',coupon='BAD',name='Customer',contact='Phone',receipt=(io.BytesIO(fixture.jpeg()),'receipt.jpg')))
        self.assertEqual(response.status_code,302);self.assertEqual(self.features.RenewalRequest.query.count(),0);self.assertEqual(set(self.features.storage.glob('*')),before)
    def test_reseller_success_debits_once_and_preserves_original_account(self):
        self.enable();data=self.fields();before=(self.user.traffic_usage,self.user.traffic_limit,self.user.expire_date)
        root='/panel/c/'+self.token+'/reseller'
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(root,data=data).status_code,302)
            self.assertEqual(self.client.post(root,data=data).status_code,302)
        order=panel.resellers.Order.query.one();child=panel.db.session.get(panel.User,order.user_id)
        self.assertEqual(order.state,'completed');self.assertEqual(order.amount,170000)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,330000)
        self.assertEqual(panel.commerce.Entry.query.count(),1);self.assertEqual(panel.commerce.Invoice.query.count(),1);self.assertEqual(child.reseller_id,self.user.id)
        self.assertEqual(child.status,'active');self.assertFalse(child.customer_paused)
        self.assertEqual((self.user.traffic_usage,self.user.traffic_limit,self.user.expire_date),before)
        self.assertNotEqual(panel.db.session.get(self.features.CustomerProfile,child.id).password_hash,data['password'])
        self.assertEqual(self.client.get(root).status_code,200)
    def test_reseller_rejects_ungranted_node_tampered_price_and_insufficient_balance(self):
        self.enable(balance=1);data=self.fields();root='/panel/c/'+self.token+'/reseller'
        with patch('resellers.subprocess.run') as proc:
            data['node_id']=str(self.remote.id);self.assertEqual(self.client.post(root,data=data).status_code,403)
            data.update(node_id=str(self.node.id),price='1');self.assertEqual(self.client.post(root,data=data).status_code,409)
            proc.assert_not_called()
        self.assertEqual(panel.resellers.Order.query.count(),0);self.assertEqual(panel.User.query.count(),2)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,1)
    def test_failed_provision_is_disabled_and_retry_never_charges_twice(self):
        self.enable();data=self.fields();root='/panel/c/'+self.token+'/reseller'
        with patch('app.sync_primary_access',side_effect=RuntimeError('Failed')):
            self.assertEqual(self.client.post(root,data=data).status_code,302)
        order=panel.resellers.Order.query.one();child=panel.db.session.get(panel.User,order.user_id)
        self.assertEqual(order.state,'pending');self.assertEqual(child.status,'disabled');self.assertTrue(child.customer_paused)
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(root,data=dict(csrf=data['csrf'],action='retry',order_id=order.id)).status_code,302)
        self.assertEqual(order.state,'completed');self.assertEqual(panel.commerce.Entry.query.count(),1)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,330000)
    def test_owner_refund_pending_order_once_and_never_refunds_completed(self):
        self.enable();data=self.fields();root='/panel/c/'+self.token+'/reseller'
        with patch('app.sync_primary_access',side_effect=RuntimeError('Failed')):self.client.post(root,data=data)
        order=panel.resellers.Order.query.one();self.admin();url='/panel/settings/resellers';fields=dict(action='refund',order_id=order.id,csrf=data['csrf'])
        self.assertEqual(self.client.post(url,data=fields).status_code,302)
        self.assertEqual(self.client.post(url,data=fields).status_code,409)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
        self.assertEqual(order.state,'cancelled');self.assertEqual(panel.commerce.Entry.query.count(),2)
    def test_disabled_reseller_csrf_and_cross_account_download(self):
        self.enable();data=self.fields();root='/panel/c/'+self.token+'/reseller'
        self.assertEqual(self.client.post(root,data={k:v for k,v in data.items() if k!='csrf'}).status_code,400)
        self.assertEqual(self.client.get(root+'/users/'+str(self.other.id)+'/download').status_code,404)
        p=panel.db.session.get(panel.resellers.Profile,self.user.id);p.enabled=False;panel.db.session.commit()
        self.assertEqual(self.client.get(root).status_code,403)
        self.assertEqual(self.client.get('/panel/settings/resellers').status_code,302)
    def test_non_owner_cannot_manage_representatives_or_clear_audit(self):
        self.admin();admin=panel.Admin.query.first();admin.role='finance';panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/settings/resellers').status_code,403)
        self.assertEqual(self.client.post('/panel/settings/audit/clear').status_code,403)

    def test_completed_order_is_not_refundable_and_revoked_grant_blocks_retry(self):
        self.enable();data=self.fields();root='/panel/c/'+self.token+'/reseller'
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):self.client.post(root,data=data)
        order=panel.resellers.Order.query.one();self.admin()
        self.assertEqual(self.client.post('/panel/settings/resellers',data=dict(action='refund',order_id=order.id,csrf=data['csrf'])).status_code,409)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,330000)
    def test_deleted_representative_cannot_transfer_permissions_to_reused_id(self):
        self.enable();uid=self.user.id
        self.features.delete_customer(uid);panel.db.session.commit()
        self.assertIsNone(panel.db.session.get(panel.resellers.Profile,uid))
        self.assertEqual(panel.resellers.Grant.query.filter_by(user_id=uid).count(),0)

    def test_grant_revoked_during_provision_never_activates_account(self):
        self.enable();data=self.fields();root='/panel/c/'+self.token+'/reseller'
        def revoke(*args,**kwargs):
            panel.resellers.Grant.query.filter_by(user_id=self.user.id,node_id=self.node.id).delete();panel.db.session.commit()
        with patch('resellers.subprocess.run',side_effect=revoke),patch('app.sync_primary_access'):
            self.assertEqual(self.client.post(root,data=data).status_code,302)
        order=panel.resellers.Order.query.one();child=panel.db.session.get(panel.User,order.user_id)
        self.assertEqual(order.state,'pending');self.assertEqual(child.status,'disabled');self.assertTrue(child.customer_paused)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,330000)
        with patch('resellers.subprocess.run') as proc:
            self.client.post(root,data=dict(csrf=data['csrf'],action='retry',order_id=order.id));proc.assert_not_called()
        self.assertEqual(panel.commerce.Entry.query.count(),1)
