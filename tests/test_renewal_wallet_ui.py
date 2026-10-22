import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
import test_customer as fixture
from test_customer import panel

class RenewalWalletTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin

    def fields(self,balance=500000):
        csrf=self.csrf()
        panel.db.session.add(panel.commerce.Wallet(user_id=self.user.id,balance=balance));panel.db.session.commit()
        return dict(csrf=csrf,reference='wallet-renewal-test-'+('z'*24),plan_id=self.features.settings()['plans'][0]['id'])

    def test_renewal_page_wallet_button_balance_reference_and_no_receipt_required(self):
        self.fields()
        page=self.client.get('/panel/c/'+self.token)
        doc=BeautifulSoup(page.data,'html.parser');form=doc.select_one('#renewal-form');button=form.select_one('[data-renew-wallet]')
        self.assertTrue(button.has_attr('formnovalidate'))
        self.assertTrue(button['formaction'].endswith('/wallet'))
        self.assertFalse(button.has_attr('disabled'))
        self.assertIn('500,000',doc.select_one('.renew-wallet-payment small').get_text())
        self.assertGreaterEqual(len(form.select_one('[name=reference]')['value']),32)

    def test_ajax_payment_applies_once_and_repeat_returns_success_without_double_charge(self):
        fields=self.fields();price=self.features.settings()['plans'][0]['price'];url='/panel/c/'+self.token+'/wallet'
        with patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',return_value=[]):
            for _ in range(2):
                response=self.client.post(url,data=fields,headers={'X-Beeny-Wallet':'1'})
                self.assertEqual(response.status_code,200,response.data)
                self.assertTrue(response.json['success'])
                self.assertEqual(response.json['wallet_balance'],500000-price)
                self.assertIn('remaining',response.json['account'])
                self.assertTrue(response.json['redirect'].endswith('#renew'))
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000-price)
        self.assertEqual(panel.commerce.Entry.query.count(),1)
        self.assertEqual(panel.commerce.Invoice.query.count(),1)

    def test_insufficient_balance_and_invalid_csrf_never_debit(self):
        fields=self.fields(1);url='/panel/c/'+self.token+'/wallet'
        response=self.client.post(url,data=fields,headers={'X-Beeny-Wallet':'1'})
        self.assertEqual(response.status_code,409);self.assertFalse(response.json['success'])
        fields['csrf']='invalid'
        self.assertEqual(self.client.post(url,data=fields,headers={'X-Beeny-Wallet':'1'}).status_code,400)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,1)
        self.assertEqual(panel.commerce.Entry.query.count(),0)

    def test_failure_before_approval_commit_rolls_back_balance_and_request(self):
        fields=self.fields()
        with patch.object(panel.experience,'approve_renewal',side_effect=ValueError('Approval rejected')):
            response=self.client.post('/panel/c/'+self.token+'/wallet',data=fields,headers={'X-Beeny-Wallet':'1'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(panel.db.session.get(panel.commerce.Wallet,self.user.id).balance,500000)
        self.assertEqual(panel.commerce.Entry.query.count(),0)
        self.assertEqual(self.features.RenewalRequest.query.count(),0)

    def test_committed_payment_is_success_if_node_sync_later_raises(self):
        fields=self.fields();original=panel.experience.approve_renewal
        def committed_then_error(row):
            original(row)
            raise RuntimeError('Node sync failed after commit')
        with patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',return_value=[]),patch.object(panel.experience,'approve_renewal',side_effect=committed_then_error):
            response=self.client.post('/panel/c/'+self.token+'/wallet',data=fields,headers={'X-Beeny-Wallet':'1'})
        self.assertEqual(response.status_code,200,response.data)
        self.assertTrue(response.json['success'])
        self.assertEqual(panel.commerce.Entry.query.count(),1)
        self.assertEqual(panel.commerce.Invoice.query.count(),1)
