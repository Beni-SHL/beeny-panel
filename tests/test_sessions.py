import unittest
from unittest.mock import patch, MagicMock
from vpn_sessions import parse_sessions, disconnect_session
from test_traffic import SNAPSHOT

class SessionTests(unittest.TestCase):
    def test_only_requested_account_and_ipv6_supported(self):
        rows = parse_sessions(SNAPSHOT, 'alice')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], '7')
        self.assertEqual(parse_sessions(SNAPSHOT, 'unknown'), [])
        self.assertEqual(parse_sessions(SNAPSHOT.replace(',', '\t'), 'alice')[0]['fingerprint'], rows[0]['fingerprint'])

    def test_stale_or_other_user_session_never_kills(self):
        with patch('vpn_sessions.Management') as factory:
            conn = factory.return_value.__enter__.return_value
            conn.command.return_value = SNAPSHOT
            alice = parse_sessions(SNAPSHOT, 'alice')[0]
            with self.assertRaises(ValueError):
                disconnect_session('bob', alice['id'], alice['fingerprint'])
            self.assertEqual(conn.command.call_count, 1)
            conn.command.reset_mock()
            disconnect_session('alice', alice['id'], alice['fingerprint'])
            self.assertEqual(conn.command.call_args.args, ('client-kill 7',))
            conn.command.reset_mock()
            with self.assertRaises(ValueError):
                disconnect_session('alice', '7\nkill bob', alice['fingerprint'])
            conn.command.assert_not_called()
