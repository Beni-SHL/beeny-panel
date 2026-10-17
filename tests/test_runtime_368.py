import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from types import SimpleNamespace
from unittest.mock import patch,Mock
import test_customer as fixture
from test_customer import panel
from admission import node_token
from session_limits import enforce
import network_policy,warp_manager
from pricing import service_allowance
from session_identity import describe

class GuardTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_tenth_unique_attempt_bans_for_thirty_minutes(self):
        guard=panel.connection_guard;now=datetime.utcnow();uid=self.user.id
        for i in range(9):self.assertFalse(guard.record(uid,'192.0.2.20:9000',str(i),now=now))
        self.assertFalse(guard.record(uid,'192.0.2.20:9000','0',now=now));self.assertEqual(guard.Attempt.query.count(),9)
        self.assertTrue(guard.record(uid,'192.0.2.20:9000','9',now=now))
        self.assertTrue(guard.blocked(uid,'192.0.2.20:8000',now+timedelta(minutes=29)))
        self.assertFalse(guard.blocked(uid,'192.0.2.20:8000',now+timedelta(minutes=30)))
        self.assertFalse(guard.blocked(uid,'192.0.2.21:8000',now))
        self.assertFalse(guard.blocked(uid+1,'192.0.2.20:8000',now))
    def test_shared_nat_and_original_connection_are_preserved(self):
        guard=panel.connection_guard
        for i in range(12):self.assertFalse(guard.record(self.user.id,'192.0.2.1:9500',str(i),protected=['192.0.2.1:5000']))
        self.assertEqual(guard.Ban.query.count(),0)
        node=SimpleNamespace(id=1);rows=[dict(id='1',fingerprint='a'*64,address='192.0.2.1:1',connected_epoch=100),dict(id='2',fingerprint='b'*64,address='192.0.2.2:2',connected_epoch=200)]
        self.user.max_devices=1
        with patch('vpn_sessions.disconnect_session') as kill:
            enforce(self.user,[node],[self.user.username],lambda n:True,lambda name:rows,kill,guard=guard)
        kill.assert_called_once_with(self.user.username,'2','b'*64)
    def test_strict_admission_ban_does_not_evict_primary(self):
        node=panel.Node(name='Main',ip='192.0.2.2',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush()
        panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.add(panel.admission.Snapshot(node_id=node.id,checked_at=datetime.utcnow()));self.user.max_devices=1;panel.db.session.commit()
        def connect(ip,port):return self.client.post('/panel/api/vpn/admission',headers={'Authorization':'Bearer '+node_token(panel.app.secret_key,node.id)},json=dict(node_id=node.id,name=self.user.username,address=f'{ip}:{port}',since='1792000000',action='connect'))
        self.assertEqual(connect('192.0.2.10',5000).status_code,200)
        for i in range(10):self.assertEqual(connect('192.0.2.20',6000+i).status_code,403)
        self.assertTrue(panel.connection_guard.blocked(self.user.id,'192.0.2.20'))
        self.assertEqual(panel.admission.Lease.query.filter_by(active=True).count(),1)
        self.assertEqual(connect('192.0.2.10',5000).status_code,200)
        self.assertEqual(connect('192.0.2.20',7000).json['retry_after'],1800)
    def test_same_nat_is_not_banned_by_admission(self):
        node=panel.Node(name='Main',ip='192.0.2.2',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.add(panel.admission.Snapshot(node_id=node.id,checked_at=datetime.utcnow()));self.user.max_devices=1;panel.db.session.commit()
        headers={'Authorization':'Bearer '+node_token(panel.app.secret_key,node.id)}
        for i in range(13):
            result=self.client.post('/panel/api/vpn/admission',headers=headers,json=dict(node_id=node.id,name=self.user.username,address=f'192.0.2.10:{5000+i}',since='1792000000',action='connect'))
            self.assertEqual(result.status_code,200 if i==0 else 403)
        self.assertEqual(panel.connection_guard.Ban.query.count(),0)
    def test_owner_can_clear_one_peer_without_changing_other_restrictions(self):
        self.admin();guard=panel.connection_guard;now=datetime.utcnow()
        panel.db.session.add_all([guard.Ban(user_id=self.user.id,address='192.0.2.1',until=now+timedelta(minutes=30)),guard.Ban(user_id=self.user.id,address='192.0.2.2',until=now+timedelta(minutes=30))]);panel.db.session.commit()
        before=(self.user.status,self.user.traffic_limit,self.user.traffic_used)
        response=self.client.post('/panel/api/vpn/peer-bans',json=dict(user_id=self.user.id,address='192.0.2.1'))
        self.assertEqual(response.status_code,200);self.assertFalse(guard.blocked(self.user.id,'192.0.2.1'));self.assertTrue(guard.blocked(self.user.id,'192.0.2.2'));self.assertEqual(before,(self.user.status,self.user.traffic_limit,self.user.traffic_used))
        admin=panel.Admin.query.first();admin.role='viewer';panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/api/vpn/peer-bans').status_code,403)
    def test_portal_gift_label_omits_zero_days(self):
        plans=self.features.settings()['plans'];plans[0]['gift_days']=0;plans[0]['gift_quota']=20
        self.features.set_setting('plans',json.dumps(plans));panel.db.session.commit()
        fixture.CustomerFlowTests.csrf(self)
        page=self.client.get('/panel/c/'+self.token)
        self.assertEqual(page.status_code,200)
        import re
        label=re.search(r'<span class="plan-gift">(.*?)</span>',page.data.decode(),re.S).group(1)
        self.assertIn('20',label);self.assertIn('گیگ هدیه',label);self.assertNotIn('روز',label)
    def test_gift_renewal_applies_once_without_changing_price(self):
        self.admin();self.user.traffic_limit=100;self.user.traffic_usage=0;self.user.expire_date='2029-01-01';panel.db.session.commit()
        plan=dict(id='gift',title='Gift plan',days=30,quota=100,devices=1,price=200000,gift_days=0,gift_quota=20)
        row=panel.customer_features.RenewalRequest(user_id=self.user.id,username=self.user.username,plan=json.dumps(plan),receipt='',source='web',billing_reference='gift-test')
        panel.db.session.add(row);panel.db.session.commit()
        with panel.app.test_request_context(),patch.object(panel.experience,'sync_access',return_value=[]):panel.experience.approve_renewal(row)
        self.assertEqual(self.user.traffic_limit,220);self.assertEqual(json.loads(row.plan)['price'],200000)
        from werkzeug.exceptions import Conflict
        with panel.app.test_request_context(),self.assertRaises(Conflict):panel.experience.approve_renewal(row)
        self.assertEqual(self.user.traffic_limit,220)

class RuntimePureTests(unittest.TestCase):
    def test_gift_is_not_doubled_and_ua_never_invents_phone_model(self):
        gift=service_allowance(dict(days=30,quota=100,price=200000,gift_days=0,gift_quota=20))
        self.assertEqual((gift['quota'],gift['days'],gift['price']),(120,30,200000));self.assertEqual(service_allowance(gift),gift)
        self.assertEqual(describe('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Safari/604.1'),'iPhone · Safari')
        self.assertIn('SM-S918B',describe('Mozilla/5.0 (Linux; Android 13; SM-S918B Build/TP1A) Chrome/120.0'))
        self.assertNotIn('K ·',describe('Mozilla/5.0 (Linux; Android 10; K) Chrome/120.0'))
    def test_iran_resource_count_above_old_1500_cap_is_accepted(self):
        import iran_network
        networks=[f'5.{i//256}.{i%256}.0/25' for i in range(1747)]
        prefixes=iran_network.prefixes({'data':{'resources':{'ipv4':networks}}})
        self.assertEqual(len(prefixes),1747)
        policy=network_policy.validate({'bypass_ips':'\n'.join(prefixes)})
        self.assertEqual(len(network_policy.client_routes(policy)),1747)
    def test_restart_routes_is_explicit_and_refuses_pending_policy(self):
        with patch.object(network_policy,'load',return_value={'token':'pending'}),patch.object(network_policy,'run') as run:
            with self.assertRaises(ValueError):network_policy.activate_client_routes()
        run.assert_not_called()
        with patch.object(network_policy,'load',side_effect=[None,{'policy':{}}]),patch.object(network_policy,'run') as run:
            with self.assertRaises(ValueError):network_policy.activate_client_routes()
        run.assert_not_called()
        with patch.object(network_policy,'load',side_effect=[None,{'policy':{'bypass_ips':'5.160.0.0/16'}}]),patch.object(network_policy,'run') as run:
            self.assertTrue(network_policy.activate_client_routes()['success'])
        self.assertEqual(run.call_args_list[0].args,('systemctl','restart','openvpn-server@server'))
    def test_interrupted_warp_job_is_not_reported_as_running_forever(self):
        import time,subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'result.json').write_text(json.dumps(dict(state='running',started_at=int(time.time())-100,action='install')))
            with patch.object(warp_manager,'ROOT',root),patch.object(warp_manager,'in_use',return_value=False),patch.object(warp_manager,'run',side_effect=subprocess.CalledProcessError(3,['systemctl'])):
                self.assertEqual(warp_manager.status()['job']['state'],'interrupted')
    def test_warp_refuses_external_or_in_use_removal(self):
        for state in [dict(installed=True,managed=False,in_use=False),dict(installed=True,managed=True,in_use=True)]:
            with patch.object(warp_manager,'supported',return_value='noble'),patch.object(warp_manager,'status',return_value=state),patch.object(warp_manager,'run') as run:
                with self.assertRaises(ValueError):warp_manager.queue('remove')
            run.assert_not_called()
    def test_warp_install_never_registers_connects_or_restarts_vpn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);response=Mock();response.geturl.return_value='https://pkg.cloudflareclient.com/pubkey.gpg';response.read.return_value=b'public-key';opener=Mock();opener.open.return_value.__enter__=Mock(return_value=response);opener.open.return_value.__exit__=Mock()
            with patch.multiple(warp_manager,ROOT=root,KEY=root/'key.gpg',REPO=root/'repo.list'),patch.object(warp_manager,'supported',return_value='noble'),patch.object(warp_manager.shutil,'which',side_effect=[None,'/usr/bin/warp-cli']),patch.object(warp_manager.urllib.request,'build_opener',return_value=opener),patch.object(warp_manager,'run',return_value=SimpleNamespace(stdout=b'key')) as run:
                self.assertTrue(warp_manager.execute('install'))
                self.assertTrue((root/'managed').exists())
            commands=[call.args for call in run.call_args_list]
            self.assertEqual(commands,[('gpg','--batch','--yes','--dearmor'),('apt-get','update'),('apt-get','install','-y','cloudflare-warp')])
