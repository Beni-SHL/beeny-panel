import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import network_policy as policy
import test_customer as fixture
from test_customer import panel

class PolicyValidation(unittest.TestCase):
    def test_rejects_injection_default_routes_and_invalid_types(self):
        for data in ({'blocked_ips':'0.0.0.0/0'},{'blocked_ips':'1.2.3.4; reboot'},
                     {'blocked_domains':'https://example.com/path'},{'warp_enabled':'1'},
                     {'warp_interface':'wg0"; flush ruleset'},{'blocked_ports':'70000'},
                     {'bypass_ips':'::/0'},{'blocked_ports':'9000-100'}):
            with self.subTest(data=data),self.assertRaises(ValueError):policy.validate(data)
    def test_compiler_scopes_rules_to_vpn_and_keeps_server_route(self):
        p=policy.validate(dict(blocked_ips='203.0.113.0/24',blocked_ports='6881\n6882-6889',torrent_ports=True,warp_enabled=True,warp_interface='wg-warp'))
        rules=policy.compile_rules(p,dict(interface='tun9',subnet='10.9.0.0/24'),{'example.com':['192.0.2.2']})
        self.assertIn('iifname "tun9" ip daddr',rules)
        self.assertIn('oifname "wg-warp" ip saddr 10.9.0.0/24',rules)
        self.assertEqual(rules.count('6881-6889'),2)
        self.assertNotIn('flush ruleset',rules)
        self.assertNotIn('hook input',rules)
    def test_atomic_firewall_batch_is_checked_before_apply(self):
        with patch.object(policy,'run',return_value=SimpleNamespace(returncode=0)) as command:
            policy.nft_apply('table inet beeny_policy {}\n')
        calls=command.call_args_list
        self.assertEqual(calls[1].args,('nft','-c','-f','-'))
        self.assertEqual(calls[2].args,('nft','-f','-'))
        self.assertEqual(calls[1].kwargs['input'],calls[2].kwargs['input'])
        self.assertTrue(calls[2].kwargs['input'].startswith('delete table inet beeny_policy\n'))
    def test_failed_validation_does_not_apply(self):
        with patch.object(policy,'run',side_effect=[SimpleNamespace(returncode=0),RuntimeError('invalid nft')]) as command:
            with self.assertRaises(RuntimeError):policy.nft_apply('bad rules')
        self.assertEqual(command.call_count,2)

class PolicyLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.conf=root/'server.conf';self.conf.write_text('port 110\nserver 10.8.0.0 255.255.255.0\ndev tun\n')
        self.root_patch=patch.object(policy,'ROOT',root/'state');self.root_patch.start()
        self.conf_patch=patch.object(policy,'CONF',self.conf);self.conf_patch.start()
        self.state=dict(policy=policy.validate({}),topology=dict(interface='tun0',subnet='10.8.0.0/24'),resolved={},revision='preview-revision')
    def tearDown(self):self.root_patch.stop();self.conf_patch.stop();self.temp.cleanup()
    def test_clear_missing_routes_is_safe_after_reboot(self):
        state=dict(policy=dict(warp_enabled=True),topology=dict(interface='tun0',subnet='10.8.0.0/24'))
        with patch.object(policy,'run',return_value=SimpleNamespace(returncode=2)) as command:
            policy.clear_routes(state)
        self.assertFalse(command.call_args.kwargs['check'])

    def test_stale_preview_cannot_apply(self):
        with patch.object(policy,'prepare',return_value=self.state),patch.object(policy,'run') as command:
            with self.assertRaisesRegex(ValueError,'changed'):policy.handle('apply',{},'old-revision')
        command.assert_not_called();self.assertIsNone(policy.load('pending.json'))
    def test_queue_failure_leaves_no_pending_change_and_no_kernel_mutation(self):
        with patch.object(policy,'prepare',return_value=self.state),patch.object(policy,'run',side_effect=RuntimeError('systemd unavailable')),patch.object(policy,'enact') as enact:
            with self.assertRaises(RuntimeError):policy.handle('apply',{},'preview-revision')
        enact.assert_not_called();self.assertIsNone(policy.load('pending.json'))
    def test_expiry_rolls_back_but_confirmation_cancels_it(self):
        with patch.object(policy,'prepare',return_value=self.state),patch.object(policy,'run') as command,patch.object(policy,'enact'):
            result=policy.handle('apply',{},'preview-revision')
        self.assertIn('--on-active=120s',command.call_args.args)
        with patch.object(policy,'restore') as restore:policy.expire(result['token'])
        restore.assert_called_once_with(None)
        self.assertIsNone(policy.load('pending.json'))
        with patch.object(policy,'prepare',return_value=self.state),patch.object(policy,'run'),patch.object(policy,'enact'):
            result=policy.handle('apply',{},'preview-revision')
        policy.handle('confirm',expected=result['token'])
        with patch.object(policy,'restore') as restore:policy.expire(result['token'])
        restore.assert_not_called()
    def test_apply_failure_restores_previous_and_does_not_claim_success(self):
        previous={'prior':'metadata'};policy.save('active.json',previous)
        with patch.object(policy,'prepare',return_value=self.state),patch.object(policy,'run'),patch.object(policy,'enact',side_effect=RuntimeError('kernel rejected')),patch.object(policy,'restore') as restore:
            with self.assertRaises(RuntimeError):policy.handle('apply',{},'preview-revision')
        restore.assert_called_once_with(previous)
        self.assertIsNone(policy.load('pending.json'))
    def test_bypass_preserves_other_settings_and_never_restarts_vpn(self):
        with patch.object(policy,'run') as command:
            policy.bypass(policy.validate(dict(bypass_ips='203.0.113.0/24')))
            self.assertIn('push "route 203.0.113.0 255.255.255.0 net_gateway"',self.conf.read_text())
            self.assertIn('port 110',self.conf.read_text())
            policy.bypass(policy.validate({}))
        command.assert_not_called();self.assertNotIn(policy.BEGIN,self.conf.read_text())

class NetworkEndpointTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_requires_owner_and_uses_fixed_local_helper(self):
        self.admin();node=panel.Node(name='Local',api_key=panel.PRIMARY_NODE_KEY,ip='127.0.0.1');panel.db.session.add(node);panel.db.session.commit()
        with patch('app.privileged_call') as helper,patch('network_policy.handle',return_value={'success':True}) as local:
            response=self.client.post(f'/panel/api/settings/network/{node.id}',json={'action':'preview','policy':{}})
        self.assertEqual(response.status_code,200);local.assert_called_once_with('preview',{},None)
        admin=panel.Admin.query.first();admin.role='viewer';panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/settings/network').status_code,403)
        self.assertEqual(self.client.post(f'/panel/api/settings/network/{node.id}',json={'action':'apply'}).status_code,403)
    def test_remote_legacy_http_is_rejected_without_request(self):
        self.admin();node=panel.Node(name='Old',api_key='secret',ip='192.0.2.4:6200');panel.db.session.add(node);panel.db.session.commit()
        with patch('requests.Session.post') as post:
            response=self.client.post(f'/panel/api/settings/network/{node.id}',json={'action':'status'})
        self.assertEqual(response.status_code,400);post.assert_not_called()
