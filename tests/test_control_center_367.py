import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
import test_customer as fixture
from test_customer import panel
import iran_network,network_policy

class GlobalSearchTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def test_search_and_online_order_apply_before_pagination(self):
        self.admin()
        panel.db.session.add_all([panel.User(username=f'bulk-{i:03}',status='active',online_status='offline') for i in range(220)])
        old=panel.User(username='old-online-target',status='active',online_status='online')
        panel.db.session.add(old);panel.db.session.commit()
        panel.db.session.add_all([panel.User(username=f'new-{i}',status='active',online_status='offline') for i in range(110)])
        panel.db.session.commit()
        data=self.client.get('/panel/api/users/search?q=bulk-000&per_page=10').json
        self.assertEqual(data['pagination']['total'],1)
        self.assertEqual(data['users'][0]['username'],'bulk-000')
        data=self.client.get('/panel/api/users/search?sort=online_first&per_page=1').json
        self.assertEqual(data['users'][0]['username'],'old-online-target')
        self.assertGreater(data['pagination']['total'],300)
    def test_literal_wildcards_and_global_filter(self):
        self.admin()
        panel.db.session.add_all([panel.User(username='find_100%',status='disabled'),panel.User(username='findX100a',status='active')]);panel.db.session.commit()
        data=self.client.get('/panel/api/users/search',query_string={'q':'_100%'}).json
        self.assertEqual([u['username'] for u in data['users']],['find_100%'])
        self.assertEqual(self.client.get('/panel/api/users/search?q=find&status=disabled').json['pagination']['total'],1)
    def test_general_embeds_real_administrators_and_local_font(self):
        self.admin();r=self.client.get('/panel/settings/general')
        self.assertIn(b'data-cc-panel="team"',r.data)
        self.assertIn(b'name="return_to" value="general"',r.data)
        self.client.post('/panel/api/admin/language',data={'language':'fa'})
        r=self.client.get('/panel/settings')
        self.assertIn('فضای کاری'.encode(),r.data)
        self.assertIn(b'dir="rtl"',r.data)


    def test_iran_import_is_owner_only_and_never_applies_rules(self):
        self.admin()
        with patch('iran_network.retrieve',return_value={'prefixes':['5.160.0.0/16'],'source':'RIPE'}),patch('network_policy.handle') as apply:
            response=self.client.post('/panel/api/settings/network/iran-prefixes')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['prefixes'],['5.160.0.0/16']);apply.assert_not_called()
        admin=panel.Admin.query.first();admin.role='viewer';panel.db.session.commit()
        with patch('iran_network.retrieve') as retrieve:
            self.assertEqual(self.client.post('/panel/api/settings/network/iran-prefixes').status_code,403)
        retrieve.assert_not_called()
    def test_old_secured_bridge_cannot_silently_discard_direct_domains(self):
        self.admin();node=panel.Node(name='Remote',ip='192.0.2.5',host='https://node.example.com',api_key='test-private-key')
        panel.db.session.add(node);panel.db.session.commit()
        with patch('requests.Session') as factory:
            session=factory.return_value.__enter__.return_value
            session.get.return_value=Mock(ok=True,json=lambda:{'capabilities':['network-policy-v1']})
            response=self.client.post(f'/panel/api/settings/network/{node.id}',json={'action':'preview','policy':{'bypass_domains':'example.ir'}})
        self.assertEqual(response.status_code,400)
        session.post.assert_not_called();self.assertNotIn(b'test-private-key',response.data)

class IranPolicyTests(unittest.TestCase):
    def test_resource_parser_collapses_ranges_and_rejects_unsafe(self):
        payload={'data':{'resources':{'ipv4':['5.160.0.0/17','5.160.128.0/17','2.144.0.0-2.144.0.255']}}}
        self.assertEqual(iran_network.prefixes(payload),['2.144.0.0/24','5.160.0.0/16'])
        for value in ['0.0.0.0/0','127.0.0.0/8','::/0','5.1.1.1; reboot']:
            with self.subTest(value=value),self.assertRaises(ValueError):iran_network.prefixes({'data':{'resources':{'ipv4':[value]}}})
    def test_cached_resource_does_not_make_network_call(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'iran-network-resources.json').write_text(json.dumps({'fetched_at':int(time.time()),'prefixes':['5.160.0.0/16']}))
            with patch('iran_network.requests.Session') as session:self.assertEqual(iran_network.retrieve(tmp)['prefixes'],['5.160.0.0/16'])
            session.assert_not_called()
    def test_domain_bypass_routes_deduplicate_and_keep_other_config(self):
        policy=network_policy.validate({'bypass_ips':'5.160.0.0/16','bypass_domains':'example.ir'})
        resolved={'example.ir':['5.160.1.2','2.144.0.1']}
        routes=network_policy.client_routes(policy,resolved)
        self.assertEqual(len(routes),2)
        self.assertTrue(any('2.144.0.1 255.255.255.255 net_gateway' in r for r in routes))
        with tempfile.TemporaryDirectory() as tmp:
            conf=Path(tmp,'server.conf');conf.write_text('port 110\nproto tcp\n')
            with patch.object(network_policy,'CONF',conf),patch.object(network_policy,'run') as command:
                network_policy.bypass(policy,resolved)
                self.assertIn('port 110',conf.read_text())
                self.assertIn('2.144.0.1',conf.read_text())
            command.assert_not_called()
    def test_invalid_direct_domain_never_executes_command(self):
        with patch.object(network_policy,'run') as run:
            with self.assertRaises(ValueError):network_policy.validate({'bypass_domains':'example.ir; reboot'})
        run.assert_not_called()
