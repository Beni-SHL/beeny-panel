import plistlib,struct,unittest
from unittest.mock import patch
import dns_services as dns
import tunnel_engines as engines
import test_customer as fixture
panel=fixture.panel
class DNSValidationTests(unittest.TestCase):
 def test_private_addresses_and_insecure_urls_rejected(self):
  for data in [dict(provider='doctor',address='127.0.0.1'),dict(provider='hyperdns',address='8.8.8.8',doh_url='http://dns.example.com/query'),dict(provider='doctor',address='8.8.8.8',doh_url='https://127.0.0.1/query'),dict(provider='doctor',address='8.8.8.8',doh_url='https://user:pass@example.com/query')]:
   with self.subTest(data=data),self.assertRaises(ValueError):dns.clean(data)
 def test_apple_profile_has_only_subscriber_endpoints(self):
  cfg=dns.clean(dict(provider='hyperdns',address='8.8.8.8',doh_url='https://dns.example.com/dns-query/only-this-user',enabled=True))
  result=plistlib.loads(dns.profile(cfg,'Test'));settings=result['PayloadContent'][0]['DNSSettings']
  self.assertEqual(settings['DNSProtocol'],'HTTPS');self.assertIn('only-this-user',settings['ServerURL']);self.assertNotIn('PayloadRemovalDisallowed',result)
 def test_dns_response_with_refusal_is_not_reported_healthy(self):
  with patch.object(dns.secrets,'randbelow',return_value=12),patch.object(dns.socket,'socket') as sock:
   sock.return_value.__enter__.return_value.recv.return_value=struct.pack('!HHHHHH',12,0x8185,1,0,0,0)
   result=dns.probe('8.8.8.8');self.assertFalse(result['usable']);self.assertEqual(result['rcode'],5)
 def test_engine_config_is_local_and_skips_sysctl(self):
  for mode in engines.MODES:
   cfg=engines.config(dict(mode=mode,host='entry.example.com',control_port=8443,public_port=8880,vpn_port=3389,vpn_proto='tcp',token='a'*64),'entry')
   for value in ['ports = ["8880=127.0.0.1:3389"]','skip_optz = true','proxy_protocol = false','web_bind = "127.0.0.1"']:self.assertIn(value,cfg)
class TunnelReleaseTests(unittest.TestCase):
 def test_arange_kcp_refuses_udp_vpn(self):
  with self.assertRaisesRegex(ValueError,'TCP VPN'):
   engines.config(dict(mode='arange-kcp',vpn_proto='udp'),'entry')
 def test_tunnel_surface_uses_country_neutral_roles(self):
  from pathlib import Path
  page=(Path(__file__).resolve().parents[1]/'templates/tunnels.html').read_text()
  self.assertIn('in any country',page)
  for label in ['Iran','foreign node','ایران']:
   self.assertNotIn(label,page)
class DNSAccessTests(unittest.TestCase):
 setUp=fixture.CustomerFlowTests.setUp
 tearDown=fixture.CustomerFlowTests.tearDown
 admin=fixture.CustomerFlowTests.admin
 csrf=fixture.CustomerFlowTests.csrf
 def setup_node(self):
  self.admin();node=panel.Node(name='DNS location',ip='192.0.2.20',api_key=panel.PRIMARY_NODE_KEY)
  panel.db.session.add(node);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit();return node
 def test_owner_csrf_and_private_profile(self):
  node=self.setup_node();url=f'/panel/api/settings/dns-services/{self.user.id}/{node.id}'
  data=dict(provider='doctor',address='8.8.8.8',doh_url='https://dns.example.com/dns-query/private',enabled=True)
  self.assertEqual(self.client.post(url,json=dict(action='save',data=data)).status_code,200)
  self.assertEqual(self.client.get(url).json['settings']['address'],'8.8.8.8')
  self.assertEqual(self.client.get('/panel/settings/dns-services').status_code,200)
  with self.client.session_transaction() as sess:sess.pop('customer_auth',None)
  self.assertEqual(self.client.get(f'/panel/c/{self.token}/dns/{node.id}.mobileconfig').status_code,302)
  self.csrf();page=self.client.get(f'/panel/c/{self.token}/dns');self.assertEqual(page.status_code,200)
  profile=self.client.get(f'/panel/c/{self.token}/dns/{node.id}.mobileconfig');self.assertEqual(profile.status_code,200);self.assertEqual(profile.headers['Cache-Control'],'no-store')
  self.assertEqual(self.client.get(f'/panel/c/{self.token}/dns/99999.mobileconfig').status_code,404)
  panel.Admin.query.first().role='viewer';panel.db.session.commit();self.assertEqual(self.client.post(url,json=dict(action='delete')).status_code,403)
 def test_mutation_requires_csrf(self):
  node=self.setup_node();self.client.environ_base.pop('HTTP_X_CSRF_TOKEN',None)
  self.assertEqual(self.client.post(f'/panel/api/settings/dns-services/{self.user.id}/{node.id}',json=dict(action='delete')).status_code,400)
