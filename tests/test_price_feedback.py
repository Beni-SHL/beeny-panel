import unittest
import test_representative_credit as fixture
from test_customer import panel
class PriceFeedbackTests(unittest.TestCase):
    setUp=fixture.RepresentativeCreditTests.setUp
    tearDown=fixture.RepresentativeCreditTests.tearDown
    csrf=fixture.RepresentativeCreditTests.csrf
    configure=fixture.RepresentativeCreditTests.configure
    enable=fixture.RepresentativeCreditTests.enable
    admin=fixture.RepresentativeCreditTests.admin
    prepare=fixture.RepresentativeCreditTests.prepare
    def price(self,value,plan='monthly'):
        return self.client.post('/panel/c/'+self.token+'/reseller/commission',data={'csrf':self.csrf_token,'action':'price','plan_id':plan,'price':value},headers={'X-Requested-With':'XMLHttpRequest','Accept':'application/json'})
    def test_290000_is_accepted_in_200000_to_300000_range(self):
        self.prepare();rate=self.db.session.get(self.c.Rate,(self.user.id,'monthly'));rate.maximum=300000;self.db.session.commit()
        self.assertEqual(self.price(290000).status_code,200);self.assertEqual(rate.sale_price,290000)
        response=self.price(310000);self.assertEqual(response.status_code,400);self.assertEqual(response.json['code'],'price_out_of_range');self.assertIn('300,000',response.json['error']);self.assertEqual(rate.sale_price,290000)
    def test_missing_disabled_and_locked_have_distinct_feedback(self):
        self.prepare();response=self.price(290000,'missing');self.assertEqual(response.status_code,404);self.assertEqual(response.json['code'],'plan_missing')
        rate=self.db.session.get(self.c.Rate,(self.user.id,'monthly'));rate.enabled=False;self.db.session.commit();response=self.price(290000);self.assertEqual(response.status_code,403);self.assertEqual(response.json['code'],'plan_disabled')
        rate.enabled=True;self.credit.Account.query.one().locked=True;self.db.session.commit();response=self.price(290000);self.assertEqual(response.status_code,403);self.assertEqual(response.json['code'],'sales_unavailable')
    def test_invalid_integer_and_bad_csrf_do_not_update_price(self):
        self.prepare();rate=self.db.session.get(self.c.Rate,(self.user.id,'monthly'));before=rate.sale_price
        response=self.price('290,000');self.assertEqual(response.status_code,400);self.assertEqual(response.json['code'],'invalid_price')
        response=self.client.post('/panel/c/'+self.token+'/reseller/commission',data={'action':'price','plan_id':'monthly','price':290000},headers={'X-Requested-With':'XMLHttpRequest'})
        self.assertEqual(response.status_code,400);self.assertEqual(rate.sale_price,before)
