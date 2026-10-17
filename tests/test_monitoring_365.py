import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from host_metrics import rate,pool_capacity
from monitoring import capacity,clean
import test_customer as fixture
from test_customer import panel

class MetricMath(unittest.TestCase):
    def test_rates_are_deltas_not_lifetime_counters_and_reset_is_unknown(self):
        a=dict(boot_id='one',interface='eth0',sample_mono=10,received=10**12,sent=2*10**12)
        b=dict(a,sample_mono=20,received=a['received']+12500000,sent=a['sent']+25000000)
        self.assertEqual(rate(a,b),(10,20))
        for changed in (dict(b,boot_id='two'),dict(b,interface='eth1'),dict(b,received=0),dict(b,sample_mono=10),dict(b,sample_mono=200)):
            self.assertEqual(rate(a,changed),(None,None))
        self.assertEqual(rate(None,b),(None,None))
    def test_pool_is_configured_limit_not_hardware(self):
        self.assertEqual(pool_capacity('server 10.8.0.0 255.255.255.0'),62)
        self.assertEqual(pool_capacity('server 10.8.0.0 255.255.255.0\ntopology subnet'),253)
        self.assertEqual(pool_capacity('server 10.8.0.0 255.255.255.0\nmax-clients 20'),20)
        self.assertIsNone(pool_capacity('server 10.8.0.0 255.255.255.0 nopool'))
        self.assertIsNone(pool_capacity('invalid'))
    def test_nonfinite_and_missing_fields_are_not_fake_zeroes(self):
        r=clean(dict(cpu=float('nan'),cpu_per_core=[10,float('inf'),60],memory=None,rx_mbps=-1))
        self.assertIsNone(r['cpu']);self.assertEqual(r['core'],60);self.assertIsNone(r['ram']);self.assertIsNone(r['rx'])
    def test_idle_server_does_not_generate_sales_capacity(self):
        start=datetime.utcnow()-timedelta(days=2)
        rows=[dict(at=start+timedelta(minutes=i*6),available=True,core=3,ram=19,connections=9,rx=.1,tx=.1) for i in range(250)]
        result=capacity(rows,62,1000)
        self.assertIsNone(result['estimated_connections']);self.assertEqual(result['observed_with_headroom'],9)
    def test_loaded_estimate_is_pool_bounded_low_confidence(self):
        start=datetime.utcnow()-timedelta(days=2)
        rows=[dict(at=start+timedelta(minutes=i*6),available=True,core=30,ram=40,connections=40,rx=20,tx=30) for i in range(250)]
        result=capacity(rows,62,1000)
        self.assertEqual(result['estimated_connections'],62);self.assertEqual(result['confidence'],'low')
        self.assertIsNone(capacity(rows[:10],62,1000)['estimated_connections'])

class MonitoringIntegration(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def node(self):
        n=panel.Node(name='Germany',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(n);panel.db.session.commit();return n
    def payload(self):return dict(cpu=8,cpu_per_core=[4,12],memory=19,disk=23,rx_mbps=10,tx_mbps=20,connections=9,pool_capacity=62,vpn_active=True,interface='eth0',boot_id='x',memory_total=4*1024**3)
    def test_history_persists_peaks_and_offline_is_unknown_not_zero(self):
        self.admin();n=self.node();now=datetime.utcnow()
        panel.monitoring.record(n.id,self.payload(),12,now-timedelta(minutes=2))
        panel.monitoring.record(n.id,None,4000,now-timedelta(minutes=1));panel.db.session.commit()
        body=self.client.get('/panel/api/monitoring').json['nodes'][0]
        self.assertFalse(body['fresh']);self.assertIsNone(body['current']);self.assertEqual(body['peaks']['connections'],9)
        self.assertEqual(body['availability'],50)
        self.assertEqual(sum(h.samples for h in panel.monitoring.Hour.query.all()),2)
    def test_settings_owner_only_validated_csrf_and_scope(self):
        self.admin();n=self.node();self.client.get('/panel/settings/monitoring')
        with self.client.session_transaction() as s:csrf=s['_customer_csrf']
        self.assertEqual(self.client.post('/panel/api/monitoring/settings',data=dict(node_id=n.id,link_mbps='1000',csrf=csrf)).status_code,200)
        self.assertEqual(panel.monitoring.Setting.query.one().link_mbps,1000)
        self.assertEqual(self.client.post('/panel/api/monitoring/settings',data=dict(node_id=n.id,link_mbps='nan',csrf=csrf)).status_code,400)
        self.client.environ_base.pop('HTTP_X_CSRF_TOKEN',None)
        self.assertEqual(self.client.post('/panel/api/monitoring/settings',data=dict(node_id=n.id,link_mbps='2000')).status_code,400)
        self.assertEqual(self.client.get('/panel/api/monitoring?days=999').status_code,400)
    def test_monitoring_render_and_unknown_nodes(self):
        self.admin();self.node()
        page=self.client.get('/panel/settings/monitoring');self.assertEqual(page.status_code,200)
        self.assertIn(b'Monitoring &amp; capacity',page.data.replace(b'Monitoring & capacity',b'Monitoring &amp; capacity'))
        body=self.client.get('/panel/api/monitoring').json['nodes'][0]
        self.assertFalse(body['fresh']);self.assertIsNone(body['peaks']['cpu'])
    def test_record_deduplicates_nearby_probes(self):
        n=self.node();now=datetime.utcnow()
        self.assertTrue(panel.monitoring.record(n.id,self.payload(),1,now))
        panel.db.session.flush()
        self.assertFalse(panel.monitoring.record(n.id,self.payload(),1,now+timedelta(seconds=5)))
        self.assertEqual(panel.monitoring.Point.query.count(),1)
    def test_scope_excludes_other_node_history(self):
        self.admin();n=self.node();other=panel.Node(name='England',ip='192.0.2.2',api_key='secret-test');panel.db.session.add(other);panel.db.session.flush()
        admin=panel.Admin.query.first();admin.role='viewer';admin.node_scope=True
        panel.db.session.add(panel.security.AdminNodeGrant(admin_id=admin.id,node_id=n.id));panel.db.session.commit()
        from flask import g
        g.pop('_login_user',None)
        body=self.client.get('/panel/api/monitoring').json
        self.assertEqual([x['id'] for x in body['nodes']],[n.id])
    def test_system_stats_uses_real_rate_and_no_one_second_blocking_call(self):
        self.admin();p=dict(self.payload(),rx_mbps=8,tx_mbps=16,memory_used=1,memory_total=4,disk_used=1,disk_total=10,cpu_cores=2)
        with patch('host_metrics.snapshot',return_value=p),patch('app.privileged_enabled',return_value=False),patch('app.psutil.cpu_percent') as cpu:
            response=self.client.get('/panel/api/system/stats');self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['network'],3);cpu.assert_not_called()

    def test_history_endpoint_never_probes_live_nodes(self):
        self.admin();self.node()
        with patch('monitoring.requests.get') as network,patch('host_metrics.snapshot') as sample:
            response=self.client.get('/panel/api/monitoring?days=7')
            self.assertEqual(response.status_code,200);network.assert_not_called();sample.assert_not_called()
    def test_non_owner_cannot_change_capacity_settings(self):
        self.admin();n=self.node();admin=panel.Admin.query.first();admin.role='viewer';panel.db.session.commit()
        from flask import g
        g.pop('_login_user',None)
        self.assertEqual(self.client.post('/panel/api/monitoring/settings',data=dict(node_id=n.id,link_mbps='1000')).status_code,403)
