import json
from unittest.mock import patch
import unittest
import test_customer as fixture
panel=fixture.panel

class TransportAccessTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    csrf=fixture.CustomerFlowTests.csrf
    def setup_node(self):
        self.admin();node=panel.Node(name='Local',ip='192.0.2.20',api_key=panel.PRIMARY_NODE_KEY)
        panel.db.session.add(node);panel.db.session.flush()
        panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        return node
    def test_listener_owner_and_csrf_checks_precede_runtime_calls(self):
        node=self.setup_node();url='/panel/api/settings/transports/'+str(node.id)
        with patch.object(panel.transport_settings,'call') as call:
            self.client.environ_base.pop('HTTP_X_CSRF_TOKEN',None)
            self.assertEqual(self.client.post(url,json={'action':'status'}).status_code,400);call.assert_not_called()
            panel.Admin.query.first().role='viewer';panel.db.session.commit()
            self.assertEqual(self.client.get('/panel/settings/transports').status_code,403)
    def test_apply_updates_listener_before_profile_and_reads_actual_udp_port(self):
        node=self.setup_node();url='/panel/api/settings/transports/'+str(node.id)
        state=dict(success=True,active=True,proto='udp',port=21194,tcp_port=21110,udp_port=21194,revision='new',pending={'token':'test','deadline':9999999999})
        with patch.object(panel.transport_settings,'call',return_value=state) as call:
            response=self.client.post(url,json=dict(action='apply',host='vpn.node.test',accept_disconnect=True,revision='before',data=dict(proto='udp',tcp_port=21110,udp_port=21194)))
            self.assertEqual(response.status_code,200);self.assertTrue(panel.speed_policy.endpoints()[str(node.id)]['managed'])
            call.assert_called_once()
            with patch('app.privileged_enabled',return_value=True),patch('app.privileged_call',return_value=dict(ca='CA',ta='TA',cert='CERT',key='KEY')):
                with panel.app.test_request_context():
                    result=panel.build_config(self.user);result.direct_passthrough=False
                    self.assertIn('remote vpn.node.test 21194 udp',result.get_data(as_text=True));self.assertIn('proto udp\n',result.get_data(as_text=True))
    def test_failed_listener_does_not_save_false_endpoint(self):
        node=self.setup_node()
        with patch.object(panel.transport_settings,'call',side_effect=ValueError('Listener rejected')):
            result=self.client.post('/panel/api/settings/transports/'+str(node.id),json=dict(action='apply',host='vpn.test',accept_disconnect=True))
        self.assertEqual(result.status_code,400);self.assertEqual(panel.speed_policy.endpoints(),{})
    def test_tunneled_download_selects_iran_endpoint_and_keeps_direct(self):
        node=self.setup_node();self.features.set_setting('vpn_tunnel_nodes',json.dumps([str(node.id)]));panel.db.session.commit()
        with patch('app.privileged_enabled',return_value=True),patch('app.privileged_call',return_value=dict(ca='CA',ta='TA',cert='CERT',key='KEY')):
            with patch.object(panel.tunnel_settings,'call',return_value=dict(success=True,endpoint=dict(host='iran.test',port=2443,proto='tcp'))):
                with panel.app.test_request_context('/?route=tunnel&node_id='+str(node.id)):
                    result=panel.build_config(self.user,node.id);result.direct_passthrough=False
                    self.assertIn('remote iran.test 2443 tcp',result.get_data(as_text=True));self.assertIn('_Tunnel.ovpn',result.headers['Content-Disposition'])
            with panel.app.test_request_context():
                result=panel.build_config(self.user,node.id);result.direct_passthrough=False
                self.assertNotIn('iran.test',result.get_data(as_text=True))
    def test_tunnel_export_is_owner_only_and_no_store(self):
        node=self.setup_node();url='/panel/api/settings/tunnels/'+str(node.id)
        with patch.object(panel.tunnel_settings,'call',return_value=dict(success=True,invitation={'token':'test-only'})) as call:
            result=self.client.post(url,json={'action':'export'})
            self.assertEqual(result.status_code,200);self.assertEqual(result.headers['Cache-Control'],'no-store')
            panel.Admin.query.first().role='support';panel.db.session.commit()
            self.assertEqual(self.client.post(url,json={'action':'export'}).status_code,403)
            self.assertEqual(call.call_count,1)
    def test_device_download_links_keep_certificate_and_selected_tunnel_node(self):
        node=self.setup_node()
        self.features.set_setting('vpn_tunnel_nodes',json.dumps([str(node.id)]))
        device=panel.devices.Device(user_id=self.user.id,name='Phone',common_name='d_1_example',pending=False,blocked=False)
        panel.db.session.add(device);panel.db.session.commit();self.csrf()
        response=self.client.get('/panel/c/'+self.token+'/devices')
        self.assertEqual(response.status_code,200)
        self.assertIn(('devices/'+str(device.id)+'/download?node_id='+str(node.id)+'&amp;route=tunnel').encode(),response.data)
