import unittest
from traffic_ledger import parse_status, usage_delta
from renewal import extend_expiry
from datetime import date

SNAPSHOT = '''TITLE,OpenVPN 2.6
HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,Bytes Received,Bytes Sent,Connected Since,Connected Since (time_t),Username,Client ID,Peer ID,Data Channel Cipher
CLIENT_LIST,alice,198.51.100.1:5000,10.8.0.2,,1048576,2097152,2026-09-29 01:00:00,1790643600,UNDEF,7,0,AES-256-GCM
CLIENT_LIST,bob,198.51.100.2:5100,10.8.0.3,,1024,2048,2026-09-29 01:02:00,1790643720,UNDEF,8,0,AES-256-GCM
END
'''

class TrafficTests(unittest.TestCase):
    def test_session_counters_do_not_count_twice(self):
        clients = parse_status(SNAPSHOT)
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0][0], 'alice')
        self.assertEqual(clients[0][2:4], (1048576, 2097152))
        self.assertEqual(usage_delta(None, 3145728), 3145728)
        self.assertEqual(usage_delta(3145728, 3145728), 0)
        self.assertEqual(usage_delta(3145728, 4194304), 1048576)
        self.assertEqual(usage_delta(3145728, 2048), 2048)

    def test_renewal_reenables_expired_account_from_today(self):
        self.assertEqual(extend_expiry('2026-09-01', 30, today=date(2026, 9, 29)), '2026-10-29')
        self.assertEqual(extend_expiry('2026-10-15', 30, today=date(2026, 9, 29)), '2026-11-14')

if __name__ == '__main__':
    unittest.main()
