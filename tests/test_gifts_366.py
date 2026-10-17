import unittest
from pricing import with_gift
class GiftTests(unittest.TestCase):
    def test_price_unchanged_and_snapshot_preserves_billable_service(self):
        plan=dict(days=30,quota=100,price=200000,devices=1)
        result=with_gift(plan,2,5)
        self.assertEqual((result['days'],result['quota'],result['price']),(32,105,200000))
        self.assertEqual((result['billable_days'],result['billable_quota']),(30,100))
        self.assertEqual(plan['days'],30)
    def test_invalid_and_overflow_rejected(self):
        for days,quota in [(-1,0),('1.5',0),(True,0),(3650,0),(0,1000000)]:
            with self.assertRaises(ValueError):with_gift(dict(days=30,quota=100,price=1),days,quota)
    def test_unlimited_does_not_turn_into_small_metered_quota(self):
        self.assertEqual(with_gift(dict(days=30,quota=0,price=1),0,5)['quota'],0)
