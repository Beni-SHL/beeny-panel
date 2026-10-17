import unittest
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel
from test_traffic import SNAPSHOT
class TerminalAccountingTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    def test_terminal_delta_commits_once_without_marking_disconnected_customer_online(self):
        node=panel.Node(name='Main',ip='192.0.2.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.flush()
        self.user.username='alice';panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=node.id));panel.db.session.commit()
        def run(log,events):
            with patch('node_snapshots.collect',return_value={node.id:dict(log=log,events=events)}),patch('terminal_traffic.acknowledge'):
                panel.update_openvpn_status()
        run(SNAPSHOT,[])
        self.assertEqual(self.user.traffic_used,3145728)
        event=dict(username='alice',address='198.51.100.1:5000',since='1790643600',received=2097152,sent=2097152,event_id='a'*64)
        empty=SNAPSHOT[:SNAPSHOT.index('CLIENT_LIST,alice')]
        run(empty,[event]);self.assertEqual(self.user.traffic_used,4194304);self.assertFalse(self.user.online)
        run(empty,[event]);self.assertEqual(self.user.traffic_used,4194304)
