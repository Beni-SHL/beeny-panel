"""Behavioral regression coverage for selective routing and fixed maintenance jobs."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import network_policy as policy
import maintenance
import test_customer as fixture
from test_customer import panel

class SelectiveWarpTests(unittest.TestCase):
    def test_unknown_presets_and_suffixes_are_rejected(self):
        for data in [{'warp_presets':['unknown']},{'warp_presets':'telegram'},{'warp_domains':'*.ir'},{'warp_ips':'0.0.0.0/0'},{'warp_mode':'shell'},{'warp_domains':'example.com; reboot'}]:
            with self.subTest(data=data),self.assertRaises(ValueError):policy.validate(data)
    def test_existing_all_traffic_policy_keeps_its_semantics(self):
        p=policy.validate({'warp_enabled':True,'warp_interface':'warp0'})
        self.assertEqual(p['warp_mode'],'all')
        self.assertEqual(policy.validate({})['warp_mode'],'selected')
    def test_selected_routes_mark_only_vpn_destinations(self):
        p=policy.validate({'warp_enabled':True,'warp_interface':'warp0','warp_mode':'selected','warp_presets':['telegram']})
        rules=policy.compile_rules(p,dict(interface='tun9',subnet='10.9.0.0/24'),{},['149.154.160.0/20'])
        self.assertIn('iifname "tun9" ip saddr 10.9.0.0/24 ip daddr { 149.154.160.0/20 } counter meta mark set 0xbee9',rules)
        state=dict(policy=p,topology=dict(interface='tun9',subnet='10.9.0.0/24'))
        with patch.object(policy,'run',return_value=SimpleNamespace(returncode=1)) as command:
            policy.configure_routes(state,{})
            self.assertIn('fwmark',command.call_args.args)
            self.assertIn('0xbee9',command.call_args.args)
            self.assertNotIn('main',command.call_args.args)
            policy.clear_routes(state)
            self.assertIn('fwmark',command.call_args_list[-2].args)
    def test_disconnected_warp_is_rejected_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);conf=root/'server.conf';conf.write_text('server 10.8.0.0 255.255.255.0\ndev tun\n')
            def run(*args,**kw):
                if args[0]=='curl':return SimpleNamespace(stdout='warp=off\n')
                return SimpleNamespace(stdout=json.dumps([{'flags':['UP'],'linkinfo':{'info_kind':'tun'}}]))
            with patch.object(policy,'ROOT',root),patch.object(policy,'CONF',conf),patch.object(policy.shutil,'which',return_value='/bin/fixed'),patch.object(policy,'topology',return_value=dict(interface='tun0',subnet='10.8.0.0/24')),patch.object(policy,'run',side_effect=run),patch.object(policy,'nft_apply') as nft:
                with self.assertRaisesRegex(ValueError,'verified connected'):policy.prepare({'warp_enabled':True,'warp_interface':'warp0','warp_mode':'selected','warp_presets':['telegram']})
                nft.assert_not_called();self.assertFalse((root/'active.json').exists())
    def test_dns_targets_and_presets_are_resolved_during_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);conf=root/'server.conf';conf.write_text('server 10.8.0.0 255.255.255.0\n')
            def run(*args,**kw):
                if args[0]=='curl':return SimpleNamespace(stdout='warp=on\n')
                if args[:3]==('ip','-d','-j'):return SimpleNamespace(stdout='[{"flags":["UP"],"linkinfo":{"info_kind":"tun"}}]')
                return SimpleNamespace(stdout='[]')
            def resolve(p,key='blocked_domains'):return {v:['1.2.3.4'] for v in p.get(key,'').splitlines()}
            with patch.object(policy,'ROOT',root),patch.object(policy,'CONF',conf),patch.object(policy.shutil,'which',return_value='/bin/fixed'),patch.object(policy,'topology',return_value=dict(interface='tun0',subnet='10.8.0.0/24')),patch.object(policy,'run',side_effect=run),patch.object(policy,'resolve',side_effect=resolve):
                state=policy.prepare({'warp_enabled':True,'warp_interface':'warp0','warp_mode':'selected','warp_presets':['telegram'],'warp_domains':'custom.example.com'})
                self.assertIn('149.154.160.0/20',state['warp_destinations']);self.assertIn('1.2.3.4/32',state['warp_destinations']);self.assertFalse((root/'active.json').exists())

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.a=patch.object(maintenance,'ROOT',self.root/'state');self.a.start()
        self.b=patch.object(maintenance,'CONFIG',self.root/'bbr.conf');self.b.start()
    def tearDown(self):self.a.stop();self.b.stop();self.temp.cleanup()
    def test_bbr_restore_preserves_original_values(self):
        values={'net.core.default_qdisc':'fq_codel','net.ipv4.tcp_congestion_control':'cubic'}
        def command(*args,**kw):
            if args[:2]==('sysctl','-n'):return SimpleNamespace(stdout='reno cubic bbr' if args[2].endswith('available_congestion_control') else values[args[2]])
            if args[:2]==('sysctl','-w'):
                key,_,value=args[2].partition('=');values[key]=value
            return SimpleNamespace(stdout='')
        with patch.object(maintenance,'run',side_effect=command):
            maintenance.bbr('bbr-enable');self.assertEqual(values['net.ipv4.tcp_congestion_control'],'bbr')
            maintenance.bbr('bbr-restore');self.assertEqual(values['net.ipv4.tcp_congestion_control'],'cubic');self.assertEqual(values['net.core.default_qdisc'],'fq_codel')
            self.assertFalse(maintenance.CONFIG.exists())
    def test_external_bbr_configuration_is_preserved(self):
        maintenance.CONFIG.write_text('external settings')
        with patch.object(maintenance,'run') as command,self.assertRaises(ValueError):maintenance.bbr('bbr-enable')
        command.assert_not_called();self.assertEqual(maintenance.CONFIG.read_text(),'external settings')
    def test_queue_never_accepts_browser_commands_and_restarts_only_panel(self):
        with self.assertRaises(ValueError):maintenance.queue('systemctl stop openvpn')
        with patch.object(maintenance,'status',return_value={}),patch.object(maintenance,'run') as command:
            maintenance.queue('panel-restart');args=command.call_args.args
            self.assertIn('panel-restart',args);self.assertFalse(any('openvpn' in a for a in args))
            job=json.loads((maintenance.ROOT/'job.json').read_text());maintenance.execute('panel-restart',job['token'])
            self.assertEqual(command.call_args.args,('systemctl','restart','beeny-panel','beeny-customer-worker'))

class AccessTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_maintenance_requires_owner_and_csrf(self):
        self.admin()
        with patch('maintenance.queue',return_value={'success':True}) as queue:
            response=self.client.post('/panel/api/settings/maintenance',json={'action':'status'});self.assertEqual(response.status_code,200);queue.assert_called_once_with('status')
            self.client.environ_base.pop('HTTP_X_CSRF_TOKEN')
            self.assertEqual(self.client.post('/panel/api/settings/maintenance',json={'action':'panel-restart'}).status_code,400)
            admin=panel.Admin.query.first();admin.role='viewer';panel.db.session.commit()
            with self.client.session_transaction() as session:self.client.environ_base['HTTP_X_CSRF_TOKEN']=session['_customer_csrf']
            from flask import g
            g.pop('_login_user',None)
            self.assertEqual(self.client.post('/panel/api/settings/maintenance',json={'action':'panel-restart'}).status_code,403)
    def test_password_reset_revokes_sessions_but_preserves_2fa(self):
        self.admin();a=panel.Admin.query.first();a.totp_secret='preserved-secret';panel.db.session.commit()
        from scripts.manage_admin import change
        change('password','admin','new-secure-password-369')
        from werkzeug.security import check_password_hash
        panel.db.session.expire_all();a=panel.Admin.query.first()
        self.assertTrue(check_password_hash(a.password,'new-secure-password-369'));self.assertEqual(a.totp_secret,'preserved-secret')
        self.assertEqual(panel.panel_sessions.PanelSession.query.filter_by(admin_id=a.id,revoked_at=None).count(),0)
        change('add','second-admin','new-secure-password-369');self.assertEqual(panel.Admin.query.filter_by(username='second-admin').one().role,'owner')
        with self.assertRaises(ValueError):change('add','second-admin','new-secure-password-369')
