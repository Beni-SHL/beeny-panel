import unittest
from unittest.mock import patch
import test_representative_credit as fixture
from test_customer import panel
class RemovalTests(unittest.TestCase):
    setUp=fixture.RepresentativeCreditTests.setUp
    tearDown=fixture.RepresentativeCreditTests.tearDown
    csrf=fixture.RepresentativeCreditTests.csrf
    configure=fixture.RepresentativeCreditTests.configure
    enable=fixture.RepresentativeCreditTests.enable
    admin=fixture.RepresentativeCreditTests.admin
    prepare=fixture.RepresentativeCreditTests.prepare
    def test_debt_prevents_any_vpn_deletion(self):
        self.prepare();self.admin()
        account=panel.representative_credit.Account.query.first();account.debt=10;panel.db.session.commit()
        with patch('app.remove_vpn_account') as remove:
            result=self.client.post(f'/panel/settings/representatives/{self.user.id}/remove',data={'confirm':self.user.username,'understood':'1'})
        self.assertEqual(result.status_code,409);remove.assert_not_called()
    def test_confirmation_required(self):
        self.prepare();self.admin()
        with patch('app.remove_vpn_account') as remove:
            response=self.client.post(f'/panel/settings/representatives/{self.user.id}/remove',data={'confirm':'wrong','understood':'1'})
        self.assertEqual(response.status_code,400);remove.assert_not_called()
    def test_removal_failure_keeps_representative_locked(self):
        self.prepare();self.admin()
        with patch('app.remove_vpn_account',side_effect=RuntimeError('node unavailable')):
            response=self.client.post(f'/panel/settings/representatives/{self.user.id}/remove',data={'confirm':self.user.username,'understood':'1'})
        self.assertEqual(response.status_code,409)
        self.assertTrue(panel.representative_credit.Account.query.first().locked)
        self.assertIsNotNone(panel.db.session.get(panel.User,self.user.id))

    def test_success_removes_child_and_identity_without_erasing_invoice_history(self):
        self.prepare();self.admin()
        child=panel.User(username='rep-child',reseller_id=self.user.id,status='active')
        panel.db.session.add(child);panel.db.session.commit()
        uid,cid=self.user.id,child.id
        with patch.object(panel.experience,'sync_access',return_value=[]):
            response=self.client.post(f'/panel/settings/representatives/{uid}/remove',data={'confirm':self.user.username,'understood':'1'})
        self.assertEqual(response.status_code,200,response.data)
        self.assertIsNone(panel.db.session.get(panel.User,uid))
        self.assertIsNone(panel.db.session.get(panel.User,cid))
        self.assertIsNotNone(panel.db.session.get(panel.devices.RetiredUsername,'rep-child'))

    def test_failed_removal_prevents_new_customer_mutations_and_can_clear_hold(self):
        self.prepare();self.admin()
        uid=self.user.id
        with patch('app.remove_vpn_account',side_effect=RuntimeError('node unavailable')):
            self.client.post(f'/panel/settings/representatives/{uid}/remove',data={'confirm':self.user.username,'understood':'1'})
        self.assertTrue(panel.db.session.get(panel.User,uid).removal_pending)
        from removal_guard import claim
        from werkzeug.exceptions import Conflict
        with self.assertRaises(Conflict):claim(panel.db,panel.User,uid)
        response=self.client.post(f'/panel/settings/representatives/{uid}/remove',data={'confirm':self.user.username,'understood':'1','action':'cancel'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(panel.db.session.get(panel.User,uid).removal_pending)
        self.assertTrue(panel.representative_credit.Account.query.first().locked)

    def test_legacy_representative_is_not_a_404_and_can_be_removed(self):
        self.prepare();self.admin()
        account=panel.representative_credit.Account.query.one();panel.db.session.delete(account);panel.db.session.commit()
        uid=self.user.id
        page=self.client.get(f'/panel/settings/representatives/{uid}/remove')
        self.assertEqual(page.status_code,200,page.data)
        with patch.object(panel.experience,'sync_access',return_value=[]):
            response=self.client.post(f'/panel/settings/representatives/{uid}/remove',data={'confirm':self.user.username,'understood':'1'})
        self.assertEqual(response.status_code,200,response.data)
        self.assertIsNone(panel.db.session.get(panel.User,uid))
