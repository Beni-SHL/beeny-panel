import json,unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel
import bandwidth
from speed_policy import validate_policy,endpoint,limited
from renewal import activation_error

class PolicyUnitTests(unittest.TestCase):
    def test_metered_blocks_and_fair_use_keeps_only_valid_active_accounts(self):
        today=date(2026,10,11)
        self.assertIsNotNone(activation_error('2026-11-01',100,101,today=today))
        self.assertIsNone(activation_error('2026-11-01',100,101,today=today,quota_mode='fair_use'))
        self.assertIsNotNone(activation_error('2026-10-01',100,101,today=today,quota_mode='fair_use'))
        self.assertIsNone(activation_error('-',0,999,today=today))
    def test_explicit_type_and_rate_validation_do_not_guess_title(self):
        self.assertEqual(validate_policy('fair_use',2000,1000,100)['throttle_up_kbps'],1000)
        for values in [('unlimited',2000,2000,100),('fair_use',2000,2000,0),('fair_use','bad',2000,100),('fair_use',0,2000,100)]:
            with self.assertRaises(ValueError):validate_policy(*values)
    def test_endpoint_accepts_domains_ipv4_ipv6_and_rejects_injection(self):
        for host in ['c1.appinet.xyz','195.248.243.17','2001:db8::1']:
            self.assertEqual(endpoint(host,110)['host'],host)
        for host in ['https://evil.com','a.com\nremote evil.com','a.com:6200','-evil','a..com','user@host']:
            with self.assertRaises(ValueError):endpoint(host,110)
        with self.assertRaises(ValueError):endpoint('vpn.test',0)
    def test_all_certificate_ips_share_one_account_class_and_other_users_unmatched(self):
        p={'alice':bandwidth.validate('alice',['alice','alice-device'],2000,1000),'bob':bandwidth.validate('bob',['bob'],500,500)}
        plan=bandwidth.plans(p,[('alice','10.8.0.2'),('alice-device','10.8.0.3'),('alice','2001:db8::2'),('bob','10.8.0.4'),('other','10.8.0.5')],lambda ip:'tun0')
        self.assertEqual(len(plan['tun0']['alice']['addresses']),3)
        self.assertNotEqual(plan['tun0']['alice']['classid'],plan['tun0']['bob']['classid'])
        self.assertNotIn('10.8.0.5',str(plan))
    def test_tc_commands_share_class_use_tunnel_directions_and_never_shell(self):
        group={'alice':dict(names=['alice'],down=2000,up=1000,classid='1',addresses=['10.8.0.2','10.8.0.3','2001:db8::2'])}
        with patch.object(bandwidth,'ensure_root'),patch.object(bandwidth,'run',return_value='[]') as run:
            bandwidth.apply_device('tun0',group,'down')
            commands=[call.args for call in run.call_args_list]
            classes=[c for c in commands if c[:3]==('tc','class','replace')]
            self.assertEqual(len(classes),1);self.assertIn('2000kbit',classes[0])
            filters=[c for c in commands if c[:3]==('tc','filter','add')]
            self.assertEqual(len(filters),3)
            self.assertTrue(all('dst_ip' in c and '7bee:1' in c for c in filters))
            self.assertTrue(any('ipv6' in c for c in filters))
    def test_certificate_path_or_command_injection_rejected(self):
        for name in ['../root','bob;reboot','name\nkill other']:
            with self.assertRaises(ValueError):bandwidth.validate(name,[name],2000,2000)
        with self.assertRaises(ValueError):bandwidth.validate('alice',['alice'],True,2000)
    def test_ethernet_route_cannot_be_shaped(self):
        with patch.object(bandwidth,'run',side_effect=['[{"dev":"eth0"}]','[{"linkinfo":{"info_kind":"ether"}}]']):
            with self.assertRaises(ValueError):bandwidth.tunnel_for('10.8.0.2')

class SpeedAccountTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    def test_owner_endpoint_edit_and_new_download_use_saved_remote(self):
        self.admin();node=panel.Node(name='Primary',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        with self.client.session_transaction() as session:csrf=session['_customer_csrf']
        url='/panel/settings/vpn-access'
        response=self.client.post(url,data={'csrf':csrf,'host_'+str(node.id):'vpn.new.test','port_'+str(node.id):'443'})
        self.assertEqual(response.status_code,409);self.assertEqual(node.ip,'192.0.2.1')
        self.assertEqual(panel.speed_policy.endpoints(),{})
        self.assertEqual(self.client.get(url).location,'/panel/settings/transports')
    def test_fair_use_banner_remains_private_and_has_renewal_action(self):
        self.user.quota_mode='fair_use';self.user.traffic_limit=100;self.user.traffic_usage=101;self.user.expire_date='2099-01-01';self.user.throttle_down_kbps=2000;self.user.throttle_up_kbps=1000;panel.db.session.commit()
        root='/panel/c/'+self.token
        self.assertEqual(self.client.get(root).status_code,302)
        self.csrf();body=self.client.get(root).data
        self.assertIn(b'speed-status-card',body);self.assertIn(b'2 Mbps',body);self.assertIn(b'1 Mbps',body)
        self.user.quota_mode='metered';panel.db.session.commit();self.assertNotIn(b'speed-status-card',self.client.get(root).data);self.assertNotIn(b'is-throttled',self.client.get(root).data)
    def test_speed_failure_retains_valid_access_without_zeroing_consumption(self):
        node=panel.Node(name='Primary',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id))
        user=self.user;user.quota_mode='fair_use';user.traffic_limit=100;user.traffic_usage=101;user.traffic_used=108447924224;user.expire_date='2099-01-01';panel.db.session.commit()
        with patch('privileged.enabled',return_value=True),patch('privileged.call',side_effect=RuntimeError('Unsupported')),patch('app.sync_primary_access') as sync,patch('vpn_sessions.local_sessions',return_value=[]):
            failures=panel.experience.sync_access(user)
        self.assertIn('Primary',failures);sync.assert_called_with(user,True)
        self.assertTrue(user.speed_sync_pending);self.assertEqual(user.traffic_usage,101)
    def test_successful_renewal_clear_removes_speed_policy_without_reset(self):
        node=panel.Node(name='Primary',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id))
        user=self.user;user.quota_mode='fair_use';user.traffic_limit=200;user.traffic_usage=101;user.speed_state=json.dumps(dict(nodes=[node.id],names=[user.username],down=2000,up=2000));panel.db.session.commit()
        with patch('privileged.enabled',return_value=True),patch('privileged.call',return_value={'success':True}) as call:
            self.assertEqual(panel.speed_policy.sync(user),[])
        self.assertEqual(call.call_args.kwargs['down'],0);self.assertEqual(user.speed_state,'');self.assertEqual(user.traffic_usage,101)

class SpeedFailureTests(unittest.TestCase):
    def test_bridge_speed_post_reaches_shaper_and_status_reports_failure(self):
        from node_agent import bridge
        with patch.object(bridge,'KEY','test-key'):
            client=bridge.app.test_client();headers={'Authorization':'Bearer test-key'}
            self.assertEqual(client.post('/api/node/set-speed-policy',json={}).status_code,401)
            with patch.object(bandwidth,'set_policy',return_value={'success':True}) as apply:
                result=client.post('/api/node/set-speed-policy',headers=headers,json={'username':'alice','names':['alice'],'down':2000,'up':1000})
                self.assertEqual(result.status_code,200);apply.assert_called_once_with('alice',['alice'],2000,1000)
            with patch.object(bandwidth,'LAST_ERROR',True):
                self.assertEqual(client.get('/api/node/speed-status',headers=headers).status_code,503)
    def test_failed_partial_application_keeps_previous_policy_and_retries(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp,patch.object(bandwidth,'STORE',Path(tmp)/'policies.json'),patch.object(bandwidth,'run',return_value='[{"ifname":"tun0","linkinfo":{"info_kind":"tun"}}]'),patch.object(bandwidth,'ensure_root'),patch.object(bandwidth,'ensure_upload'),patch.object(bandwidth,'reconcile',side_effect=RuntimeError('tc failed')):
            bandwidth.save({'alice':bandwidth.validate('alice',['alice'],500,500)})
            with self.assertRaises(RuntimeError):bandwidth.set_policy('alice',['alice'],2000,2000)
            self.assertEqual(bandwidth.read()['alice']['down'],500)
        bandwidth.LAST_ERROR=False
    def test_incomplete_status_is_not_treated_as_no_connected_accounts(self):
        with self.assertRaises(ValueError):bandwidth.sessions('ERROR: management unavailable')
        self.assertEqual(bandwidth.sessions('HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address\nEND\n'),[])
    def test_foreign_custom_qdisc_is_never_replaced(self):
        with patch.object(bandwidth,'qdiscs',return_value=[{'root':True,'handle':'1:','kind':'cake'}]),patch.object(bandwidth,'run') as run:
            with self.assertRaises(ValueError):bandwidth.ensure_root('tun0')
            run.assert_not_called()

class SpeedSecurityTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_endpoint_requires_csrf_and_invalid_host_preserves_saved_settings(self):
        self.admin();node=panel.Node(name='Primary',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.commit()
        url='/panel/settings/vpn-access'
        self.assertEqual(self.client.post(url,data={}).status_code,400)
        with self.client.session_transaction() as session:csrf=session['_customer_csrf']
        self.features.set_setting('vpn_client_endpoints',json.dumps({str(node.id):{'host':'old.test','port':110}}));panel.db.session.commit()
        response=self.client.post(url,data={'csrf':csrf,'host_'+str(node.id):'bad\nremote attacker.test','port_'+str(node.id):110})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get(url).status_code,302)
        self.assertEqual(self.client.get('/panel/users/add').status_code,200)
        self.assertEqual(panel.speed_policy.endpoints()[str(node.id)]['host'],'old.test')
    def test_approved_plan_restores_speed_and_preserves_consumption(self):
        self.configure=fixture.CustomerFlowTests.configure.__get__(self)
        self.configure()
        node=panel.Node(name='Primary',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id))
        self.user.quota_mode='fair_use';self.user.traffic_usage=101;self.user.traffic_limit=100;self.user.expire_date='2099-01-01';self.user.speed_state=json.dumps(dict(nodes=[node.id],names=[self.user.username],down=2000,up=2000));panel.db.session.commit()
        row=self.features.create_request(self.user,'monthly',fixture.jpeg(),name='User',contact='Phone')
        plan=json.loads(row.plan);plan.update(quota_mode='fair_use',throttle_down_kbps=1000,throttle_up_kbps=500);row.plan=json.dumps(plan);panel.db.session.commit()
        with patch('privileged.enabled',return_value=True),patch('privileged.call',return_value={'success':True}) as call,patch('app.sync_primary_access'),patch('vpn_sessions.local_sessions',return_value=[]):
            self.assertEqual(panel.experience.approve_renewal(row),[])
        self.assertGreater(self.user.traffic_limit,101);self.assertEqual(self.user.traffic_usage,101);self.assertEqual(self.user.speed_state,'');self.assertEqual(self.user.quota_mode,'fair_use');self.assertTrue(any(c.kwargs.get('down')==0 for c in call.call_args_list))
