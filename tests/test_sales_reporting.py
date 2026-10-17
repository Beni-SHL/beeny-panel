import json,unittest
from datetime import datetime
from types import SimpleNamespace
from sales_reporting import summarize
class MonthlySalesTests(unittest.TestCase):
    def test_channels_refund_month_and_principal(self):
        row=lambda ref,amount,date,rep:SimpleNamespace(source_reference=ref,amount=amount,created_at=date,snapshot=json.dumps({'commission_reseller':rep}))
        rows=[row('direct',100,datetime(2026,9,1),None),row('rep',300,datetime(2026,10,1),9)]
        out=summarize(rows,[dict(reference='direct',amount=40,date=datetime(2026,10,2))],[dict(amount=70,date=datetime(2026,10,3))],datetime(2026,10,14))
        self.assertEqual(len(out),12)
        self.assertEqual(out[-2]['direct'],100)
        self.assertEqual(out[-1]['direct'],-40)
        self.assertEqual(out[-1]['representative'],300)
        self.assertEqual(out[-1]['debt'],70)
        self.assertEqual(out[-1]['total'],330)
    def test_empty_and_year_boundary(self):
        out=summarize([],[],[],datetime(2026,1,1))
        self.assertEqual(out[0]['month'],'2025-02')
        self.assertTrue(all(x['total']==0 and x['direct_height']==0 for x in out))

import test_customer as fixture
from test_customer import panel
class SalesPageTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_report_and_settings_render(self):
        self.admin()
        response=self.client.get('/panel/settings/sales')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Monthly revenue',response.data)
        self.assertNotIn(b'Cost per GB',response.data)
        response=self.client.get('/panel/settings')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'/settings/general',response.data)
        general=self.client.get('/panel/settings/general')
        self.assertIn(b'Administrators',general.data)
        self.assertNotIn(b'Update panel',response.data)
