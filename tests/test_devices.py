import unittest
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel
class DeviceTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    def test_private_cert_download_and_cross_account_isolation(self):
        base='/panel/c/'+self.token+'/devices'
        self.assertEqual(self.client.get(base).status_code,302);csrf=self.csrf()
        row=panel.devices.Device(user_id=self.user.id,name='Phone',common_name='d_1_abcdef',pending=False);other=panel.devices.Device(user_id=self.other.id,name='Other phone',common_name='d_2_abcdef',pending=False)
        panel.db.session.add_all([row,other]);panel.db.session.commit()
        self.assertNotIn(b'Other phone',self.client.get(base).data)
        self.assertEqual(self.client.get(base+'/'+str(other.id)+'/download').status_code,404)
        row.blocked=True;panel.db.session.commit()
        self.assertEqual(self.client.get(base+'/'+str(row.id)+'/download').status_code,409)
        self.assertEqual(self.client.post(base,data={'csrf':csrf,'action':'unblock','device_id':row.id}).status_code,403)
    def test_account_renewal_preserves_device_block(self):
        local=panel.Node(name='Primary',ip='127.0.0.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(local);panel.db.session.flush();panel.db.session.add(panel.UserNode(user_id=self.user.id,node_id=local.id))
        row=panel.devices.Device(user_id=self.user.id,name='Blocked',common_name='d_1_abcdef',blocked=True,pending=False);panel.db.session.add(row);panel.db.session.commit()
        with patch('app.privileged_enabled',return_value=True),patch('app.privileged_call') as helper:
            panel.sync_primary_access(self.user,True)
        helper.assert_any_call('access',username=row.common_name,active=False)
        helper.assert_any_call('access',username=self.user.username,active=True)
        self.assertTrue(row.blocked)
    def test_device_usage_resolves_to_original_owner(self):
        row=panel.devices.Device(user_id=self.user.id,name='Phone',common_name='d_1_abcdef');panel.db.session.add(row);panel.db.session.commit()
        self.assertEqual(panel.devices.owner(row.common_name).id,self.user.id)
        self.assertEqual(panel.devices.owner(self.user.username).id,self.user.id)
        self.assertIsNone(panel.devices.owner('deleted-unknown'))
