"""Representative preset pricing and wallet renewals obey server grants and balances."""
import json,unittest
from unittest.mock import patch
from datetime import datetime,timedelta
import test_studio as studio_fixture
from test_customer import panel

class RepresentativePlanTests(unittest.TestCase):
    setUp=studio_fixture.StudioTests.setUp
    tearDown=studio_fixture.StudioTests.tearDown
    csrf=studio_fixture.StudioTests.csrf
    admin=studio_fixture.StudioTests.admin
    configure=studio_fixture.StudioTests.configure
    enable=studio_fixture.StudioTests.enable
    fields=studio_fixture.StudioTests.fields
    def create(self):
        self.enable(balance=2000000)
        data=self.fields();data.update(plan_id='monthly',price='1',quota='99999',days='3650',devices='20')
        self.root='/panel/c/'+self.token+'/reseller'
        with patch('resellers.subprocess.run'),patch('app.sync_primary_access'),patch.object(panel.experience,'sync_access',return_value=[]):
            self.assertEqual(self.client.post(self.root,data=data).status_code,302)
        self.order=panel.resellers.Order.query.one()
        self.child=panel.db.session.get(panel.User,self.order.user_id)
        self.data=data
    def renew(self,**changes):
        fields=dict(action='renew',reference='b'*32,csrf=self.data['csrf'],user_id=self.child.id,plan_id='monthly',price='1',quota='99999')
        fields.update(changes)
        with patch.object(panel.experience,'sync_access',return_value=[]):return self.client.post(self.root,data=fields)
    def test_preset_ignores_all_forged_price_and_limit_fields(self):
        self.create()
        self.assertEqual((self.child.traffic_limit,self.child.max_devices),(100,1))
        self.assertEqual(self.child.expire_date,(datetime.utcnow().date()+timedelta(days=30)).isoformat())
        self.assertEqual(self.order.amount,250000)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,1750000)
        snapshot=json.loads(self.order.snapshot);self.assertEqual(snapshot['id'],'monthly')
    def test_preset_renewal_preserves_consumption_pause_and_charges_once(self):
        self.create();child=self.child
        child.traffic_usage=42.125;child.traffic_used=45231374336;child.last_session_bytes=50000;child.customer_paused=True
        panel.db.session.commit();before=(child.traffic_usage,child.traffic_used,child.last_session_bytes)
        self.assertEqual(self.renew().status_code,302)
        self.assertEqual(self.renew().status_code,302)
        self.assertEqual(child.traffic_limit,200);self.assertEqual(child.expire_date,(datetime.utcnow().date()+timedelta(days=60)).isoformat())
        self.assertEqual((child.traffic_usage,child.traffic_used,child.last_session_bytes),before);self.assertTrue(child.customer_paused)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,1500000)
        self.assertEqual(panel.resellers.Renewal.query.count(),1);self.assertEqual(panel.commerce.Entry.query.count(),2);self.assertEqual(panel.commerce.Invoice.query.count(),2)
    def test_insufficient_wallet_cannot_change_account_or_create_invoice(self):
        self.create();wallet=panel.db.session.get(panel.commerce.Wallet,self.user.id);wallet.balance=1;panel.db.session.commit()
        before=(self.child.expire_date,self.child.traffic_limit,self.child.max_devices)
        self.assertEqual(self.renew().status_code,409)
        self.assertEqual((self.child.expire_date,self.child.traffic_limit,self.child.max_devices),before)
        self.assertEqual(wallet.balance,1);self.assertEqual(panel.resellers.Renewal.query.count(),0);self.assertEqual(panel.commerce.Invoice.query.count(),1)
    def test_renewal_rejects_other_accounts_manager_blocks_and_revoked_nodes(self):
        self.create()
        self.assertEqual(self.renew(user_id=self.other.id).status_code,404)
        self.child.status='disabled';panel.db.session.commit();self.assertEqual(self.renew().status_code,409)
        self.child.status='active';panel.db.session.commit()
        panel.resellers.Grant.query.filter_by(user_id=self.user.id).delete();panel.db.session.commit()
        self.assertEqual(self.renew().status_code,403)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,1750000)
        self.assertEqual(panel.resellers.Renewal.query.count(),0)
    def test_invalid_plan_and_csrf_are_rejected_without_charge(self):
        self.create();self.assertEqual(self.renew(plan_id='forged').status_code,400);self.assertEqual(self.renew(csrf='wrong').status_code,400)
        self.assertEqual(self.renew(plan_id='custom',days='0',quota='100',devices='1').status_code,400)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,1750000)
    def test_custom_renewal_uses_representative_rates_and_records_snapshot(self):
        self.create();self.assertEqual(self.renew(plan_id='custom',days='10',quota='20',devices='2').status_code,302)
        row=panel.resellers.Renewal.query.one();self.assertEqual(row.amount,90000)
        self.assertEqual(self.child.traffic_limit,120);self.assertEqual(self.child.max_devices,2)
        self.assertEqual(json.loads(row.snapshot)['rates']['per_gb'],1000)
    def test_all_assigned_nodes_must_be_granted(self):
        self.create();panel.db.session.add(panel.UserNode(user_id=self.child.id,node_id=self.remote.id));panel.db.session.commit()
        self.assertEqual(self.renew().status_code,403);self.assertEqual(panel.resellers.Renewal.query.count(),0)
    def test_deleted_customer_cannot_inherit_renewal_history(self):
        self.create();self.renew();uid=self.user.id;self.features.delete_customer(uid);panel.db.session.commit()
        self.assertEqual(panel.resellers.Renewal.query.filter_by(reseller_id=uid).count(),0)
    def test_new_ticket_page_is_private_and_inbox_has_no_compose_form(self):
        self.csrf();root='/panel/c/'+self.token+'/tickets'
        self.assertEqual(self.client.get(root+'/new').status_code,200)
        inbox=self.client.get(root).data
        self.assertNotIn(b'<textarea',inbox);self.assertIn(b'/tickets/new',inbox)
        anonymous=panel.app.test_client();self.assertEqual(anonymous.get(root+'/new').status_code,302)
    def test_rotated_link_is_not_advertised_as_valid(self):
        self.create();link=panel.db.session.get(panel.AccountLink,self.child.id);link.token_hash='d'*64;panel.db.session.commit()
        result=self.client.get(self.root).data
        self.assertNotIn(self.order.portal_token.encode(),result)
    def test_all_representative_routes_require_login_and_old_session_is_revoked(self):
        self.create();anonymous=panel.app.test_client()
        for route in (self.root,self.root+'/users/'+str(self.child.id)+'/download','/panel/c/'+self.token+'/tickets/1'):
            self.assertEqual(anonymous.get(route).status_code,302)
        self.assertEqual(anonymous.post(self.root,data=self.data).status_code,302)
        self.assertEqual(anonymous.post('/panel/c/'+self.token+'/renew/quote',data=self.data).status_code,302)
        self.features.CustomerProfile.query.filter_by(user_id=self.user.id).one().auth_version='new-version'
        panel.db.session.commit();self.assertEqual(self.client.get(self.root).status_code,302)

if __name__=='__main__':unittest.main()

class RepresentativeListTests(unittest.TestCase):
    setUp=RepresentativePlanTests.setUp
    tearDown=RepresentativePlanTests.tearDown
    csrf=RepresentativePlanTests.csrf
    admin=RepresentativePlanTests.admin
    configure=RepresentativePlanTests.configure
    enable=RepresentativePlanTests.enable
    fields=RepresentativePlanTests.fields
    create=RepresentativePlanTests.create
    # Do not repeat inherited pricing cases in this focused list suite.
    def test_list_search_pagination_and_expandable_details(self):
        self.create()
        for index in range(15):
            panel.db.session.add(panel.resellers.Order(reference=f'{index:032x}',reseller_id=self.user.id,user_id=-100-index,node_id=self.node.id,username=f'archive{index:02}',amount=250000,snapshot='{}',state='completed',portal_token='B'*43))
        panel.db.session.commit()
        body=self.client.get(self.root).data
        self.assertEqual(body.count(b'class="reseller-row-detail"'),12)
        self.assertIn(b'page=2',body)
        second=self.client.get(self.root+'?page=2').data
        self.assertEqual(second.count(b'class="reseller-row-detail"'),4)
        searched=self.client.get(self.root+'?q=archive03').data
        self.assertEqual(searched.count(b'class="reseller-row-detail"'),1)
        self.assertNotIn(b'archive04',searched)
        self.assertEqual(self.client.get(self.root+'?q=%25').data.count(b'class="reseller-row-detail"'),0)

    def test_delete_is_owned_csrf_protected_and_preserves_history(self):
        self.create();uid=self.child.id;balance=panel.db.session.get(panel.commerce.Wallet,self.user.id).balance
        url=self.root+'/users/'+str(uid)+'/delete'
        self.assertEqual(self.client.post(url,data={'csrf':'bad'}).status_code,400)
        self.assertEqual(self.client.post(self.root+'/users/'+str(self.other.id)+'/delete',data={'csrf':self.data['csrf']}).status_code,404)
        with patch.object(panel.experience,'sync_access',return_value=[]),patch('cluster.delete_user_on_node'):
            self.assertEqual(self.client.post(url,data={'csrf':self.data['csrf']}).status_code,302)
        self.assertIsNone(panel.db.session.get(panel.User,uid))
        self.assertIsNone(panel.db.session.get(panel.AccountLink,uid))
        self.assertIsNotNone(panel.db.session.get(panel.devices.RetiredUsername,self.order.username))
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,balance)
        self.assertEqual(panel.resellers.Order.query.one().user_id,-uid)
        self.assertEqual(panel.commerce.Entry.query.count(),1)

    def test_node_failure_keeps_blocked_account_for_retry(self):
        self.create();uid=self.child.id
        with patch.object(panel.experience,'sync_access',return_value=['Primary']):
            response=self.client.post(self.root+'/users/'+str(uid)+'/delete',data={'csrf':self.data['csrf']})
        self.assertEqual(response.status_code,409)
        self.assertEqual(panel.db.session.get(panel.User,uid).status,'disabled')
        self.assertIsNotNone(panel.db.session.get(panel.AccountLink,uid))


class RepresentativeAdminTests(unittest.TestCase):
    setUp=RepresentativePlanTests.setUp
    tearDown=RepresentativePlanTests.tearDown
    csrf=RepresentativePlanTests.csrf
    admin=RepresentativePlanTests.admin
    configure=RepresentativePlanTests.configure
    enable=RepresentativePlanTests.enable
    fields=RepresentativePlanTests.fields
    create=RepresentativePlanTests.create
    def test_lock_unlock_and_removal_review_preserve_wallet_children_and_history(self):
        self.create();uid=self.child.id;balance=panel.db.session.get(panel.commerce.Wallet,self.user.id).balance
        self.admin()
        with self.client.session_transaction() as saved:csrf=saved['_customer_csrf']
        post=lambda action:self.client.post('/panel/settings/resellers',data={'csrf':csrf,'user_id':self.user.id,'action':action})
        self.assertEqual(post('lock').status_code,302)
        self.assertFalse(panel.db.session.get(panel.resellers.Profile,self.user.id).enabled)
        self.assertEqual(panel.db.session.get(panel.User,uid).status,'active')
        self.assertEqual(post('unlock').status_code,302)
        self.assertTrue(panel.db.session.get(panel.resellers.Profile,self.user.id).enabled)
        removal=post('delete_representative')
        self.assertEqual(removal.status_code,302)
        self.assertIn(f'/representatives/{self.user.id}/remove',removal.location)
        self.assertIsNotNone(panel.db.session.get(panel.resellers.Profile,self.user.id))
        self.assertEqual(panel.db.session.get(panel.User,uid).reseller_id,self.user.id)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,balance)
        self.assertEqual(panel.resellers.Order.query.count(),1)
