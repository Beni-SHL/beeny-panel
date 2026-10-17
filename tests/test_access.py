"""Check local renewal removes OpenVPN's per-account deny file."""
import ast
import os
import pathlib
import socket
import types
import unittest
from unittest.mock import patch

source = ast.parse((pathlib.Path(__file__).resolve().parents[1] / 'app.py').read_text())
node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'sync_primary_access')
namespace = {'os': os, 'socket': socket,'privileged_enabled':lambda:False}
exec(compile(ast.Module(body=[node], type_ignores=[]), '<access>', 'exec'), namespace)

class AccessTests(unittest.TestCase):
    def test_personal_pause_remains_blocked_during_admin_renewal(self):
        user = types.SimpleNamespace(username='alice', status='active', customer_paused=True)
        with patch('os.makedirs'), patch('vpn_sessions.disable_ccd') as handle, patch('os.remove') as remove, patch('socket.create_connection', side_effect=OSError):
            namespace['sync_primary_access'](user, True)
        handle.assert_called_once_with('/etc/openvpn/ccd/alice')
        remove.assert_not_called()

    def test_active_renewal_removes_local_deny_file(self):
        user = types.SimpleNamespace(username='alice', status='active')
        with patch('os.path.exists', return_value=True), patch('vpn_sessions.enable_ccd') as remove:
            namespace['sync_primary_access'](user, True)
        remove.assert_called_once_with('/etc/openvpn/ccd/alice')

    def test_unselected_node_stays_blocked(self):
        user = types.SimpleNamespace(username='alice', status='active')
        with patch('os.makedirs'), patch('vpn_sessions.disable_ccd') as handle, patch('socket.create_connection', side_effect=OSError):
            namespace['sync_primary_access'](user, False)
        handle.assert_called_once_with('/etc/openvpn/ccd/alice')

if __name__ == '__main__':
    unittest.main()
