import tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from vpn_sessions import disable_ccd,enable_ccd

class CCDPermissionTests(unittest.TestCase):
    def test_block_readable_by_vpn_user_and_enable_preserves_custom_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'alice';original=b'ifconfig-push 10.8.0.2 255.255.255.0\npush "route 10.9.0.0 255.255.0.0"\n'
            p.write_bytes(original);p.chmod(0o600)
            disable_ccd(p);disable_ccd(p)
            self.assertEqual(p.read_bytes(),original+b'disable\n');self.assertEqual(p.stat().st_mode&0o777,0o644)
            enable_ccd(p);self.assertEqual(p.read_bytes(),original);self.assertEqual(p.stat().st_mode&0o777,0o644)
    def test_symlink_cannot_modify_foreign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'target';target.write_text('private');p=root/'alice';p.symlink_to(target)
            with self.assertRaises(ValueError):disable_ccd(p)
            self.assertEqual(target.read_text(),'private')
    def test_bridge_stats_compatible_with_existing_panel_and_reports_speed_version(self):
        from node_agent import bridge
        with patch.object(bridge,'KEY','test'),patch.object(bridge.subprocess,'run',return_value=Mock(returncode=0)),patch.object(bridge,'metrics',return_value={}):
            response=bridge.app.test_client().get('/api/node/stats',headers={'Authorization':'Bearer test'})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['status'],'online');self.assertEqual(response.json['agent_version'],Path('VERSION').read_text().strip())
    def test_node_editor_has_independent_api_host_and_local_modal_handler(self):
        source=(Path(__file__).resolve().parents[1]/'templates/nodes.html').read_text()
        self.assertIn('name="host"',source);self.assertIn('data-cc-toggle="node-editor-',source);self.assertIn('data-settings-ajax',source)

    def test_bridge_block_and_enable_preserve_ccd_and_return_confirmed_state(self):
        from node_agent import bridge
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'alice';p.write_text('ifconfig-push 10.8.0.2 255.255.255.0\n')
            original=p.read_bytes()
            with patch.object(bridge,'KEY','test'),patch.object(bridge,'Path',side_effect=lambda value:root if value=='/etc/openvpn/ccd' else Path(value)),patch.object(bridge.subprocess,'run',return_value=Mock(returncode=0)),patch.object(bridge,'local_sessions',return_value=[]):
                client=bridge.app.test_client();headers={'Authorization':'Bearer test'}
                disabled=client.post('/api/node/set-user-state',headers=headers,json={'username':'alice','active':False})
                self.assertEqual(disabled.status_code,200);self.assertTrue(disabled.json['success']);self.assertEqual(p.stat().st_mode&0o777,0o644);self.assertIn(b'disable',p.read_bytes())
                enabled=client.post('/api/node/set-user-state',headers=headers,json={'username':'alice','active':True})
                self.assertEqual(enabled.status_code,200);self.assertEqual(p.read_bytes(),original)

    def test_new_ccd_directory_readable_under_restrictive_service_umask(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ccd'/'alice';old=os.umask(0o077)
            try:disable_ccd(p)
            finally:os.umask(old)
            self.assertEqual(p.parent.stat().st_mode&0o777,0o755)
            self.assertEqual(p.stat().st_mode&0o777,0o644)
