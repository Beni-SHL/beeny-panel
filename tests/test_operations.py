import unittest
from unittest.mock import patch
from datetime import datetime,timedelta
import test_customer as fixture
from test_customer import panel
class OperationTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_host_traffic_is_independent_of_user_reset_and_deletion(self):
        data=dict(interface='eth0',boot_id='boot-one',received=1000,sent=2000)
        panel.host_traffic.record(1,'Primary',data);panel.db.session.commit()
        self.assertEqual(panel.host_traffic.Daily.query.count(),0)
        data.update(received=1500,sent=3500);panel.host_traffic.record(1,'Primary',data);panel.db.session.commit()
        row=panel.host_traffic.Daily.query.one();self.assertEqual(row.received+row.sent,2000)
        self.user.traffic_usage=0;panel.db.session.delete(self.user);panel.db.session.commit()
        self.assertEqual(row.received+row.sent,2000)
        data.update(boot_id='boot-two',received=100,sent=200);panel.host_traffic.record(1,'Primary',data);panel.db.session.commit()
        self.assertEqual(row.received+row.sent,2300)
    def test_bulk_preview_does_not_mutate_and_confirm_is_single_use(self):
        self.admin();url='/panel/users/bulk'
        self.assertEqual(self.client.post(url,data={'users':[self.user.id],'operation':'renew','value':'30'}).status_code,200)
        self.assertEqual(self.user.expire_date,'2027-01-01');self.assertEqual(panel.bulk.Job.query.count(),0)
        with self.client.session_transaction() as session:token=session['bulk_preview']['token']
        self.assertEqual(self.client.post(url,data={'confirm':token}).status_code,302)
        self.assertEqual(self.client.post(url,data={'confirm':token}).status_code,400)
        with patch.object(panel.experience,'sync_access',return_value=[]):panel.bulk.cycle();panel.bulk.cycle()
        self.assertEqual(self.user.expire_date,'2027-01-31')
        self.assertEqual(panel.bulk.Item.query.one().state,'completed')
    def test_clearing_old_notices_never_deletes_host_or_vpn_ledger(self):
        from scripts.cleanup_storage import cleanup
        panel.host_traffic.record(1,'Primary',dict(interface='eth0',boot_id='one',received=1,sent=1));panel.db.session.commit()
        panel.host_traffic.record(1,'Primary',dict(interface='eth0',boot_id='one',received=2,sent=2));panel.db.session.commit()
        cleanup()
        self.assertEqual(panel.host_traffic.Daily.query.one().received,1)
    def test_traffic_page_renders_measured_and_missing_host_data(self):
        self.admin();response=self.client.get('/panel/traffic')
        self.assertEqual(response.status_code,200);self.assertIn(b'Server interface traffic',response.data)
