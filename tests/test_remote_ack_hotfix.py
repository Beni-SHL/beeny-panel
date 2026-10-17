import unittest
from unittest.mock import patch,Mock
import test_customer as fixture
from test_customer import panel
from test_traffic import SNAPSHOT

class RemoteAckTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    def test_remote_final_bytes_acked_to_node_not_peer_and_not_charged_twice(self):
        node=panel.Node(name='England',ip='192.0.2.10:6200',host='https://gb.example.test',api_key='test-only-node-key')
        panel.db.session.add(node);panel.db.session.flush()
        self.user.username='alice';panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        event=dict(username='alice',address='198.51.100.1:5000',since='1790643600',received=2097152,sent=2097152,event_id='a'*64)
        def collect(log,events):
            with patch('node_snapshots.collect',return_value={node.id:dict(log=log,events=events)}):panel.update_openvpn_status()
        with patch.object(panel.requests,'post',return_value=Mock(status_code=200)) as post:
            collect(SNAPSHOT,[])
            empty=SNAPSHOT[:SNAPSHOT.index('CLIENT_LIST,alice')]
            collect(empty,[event]);self.assertEqual(self.user.traffic_used,4194304)
            collect(empty,[event]);self.assertEqual(self.user.traffic_used,4194304)
        ack=[c for c in post.call_args_list if c.args and c.args[0].endswith('/ack-traffic')]
        self.assertTrue(ack)
        for c in ack:
            self.assertEqual(c.args[0],'https://gb.example.test/api/node/ack-traffic')
            self.assertEqual(c.kwargs['json'],{'ids':['a'*64]})
