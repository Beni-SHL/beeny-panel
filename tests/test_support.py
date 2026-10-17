import unittest
from flask import g
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel
class SupportTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    def test_private_ticket_login_csrf_and_cross_account(self):
        base='/panel/c/'+self.token+'/tickets'
        self.assertEqual(self.client.get(base).status_code,302)
        csrf=self.csrf()
        self.assertEqual(self.client.post(base,data={'subject':'Help','message':'Secret'}).status_code,400)
        self.assertEqual(self.client.post(base,data={'csrf':csrf,'subject':'Help','message':'Private question'}).status_code,302)
        row=panel.support.Ticket.query.one()
        other=panel.support.Ticket(user_id=self.other.id,username=self.other.username,subject='Other private ticket');panel.db.session.add(other);panel.db.session.commit()
        self.assertNotIn(b'Other private ticket',self.client.get(base).data)
        self.assertEqual(self.client.post(base+'/'+str(other.id)+'/reply',data={'csrf':csrf,'message':'steal'}).status_code,404)
        self.assertEqual(panel.support.Message.query.filter_by(ticket_id=other.id).count(),0)
    def test_staff_reply_and_close_show_to_customer(self):
        csrf=self.csrf();base='/panel/c/'+self.token+'/tickets'
        self.client.post(base,data={'csrf':csrf,'subject':'Help','message':'Question'})
        row=panel.support.Ticket.query.one();self.admin()
        self.assertEqual(self.client.post('/panel/tickets/'+str(row.id)+'/reply',data={'message':'Staff answer'}).status_code,302)
        self.assertEqual(row.status,'answered')
        self.assertTrue(panel.experience.Notification.query.filter_by(user_id=self.user.id,title='پاسخ پشتیبانی').first())
        self.assertEqual(self.client.post('/panel/tickets/'+str(row.id)+'/status',data={'status':'closed'}).status_code,302)
        self.assertIn(b'Staff answer',self.client.get(base+'/'+str(row.id)).data)
        self.assertEqual(self.client.post(base+'/'+str(row.id)+'/reply',data={'csrf':csrf,'message':'more'}).status_code,409)
    def test_main_node_health_reports_stopped_even_with_existing_log(self):
        node=panel.Node(name='Main',ip='127.0.0.1',api_key=panel.PRIMARY_NODE_KEY);panel.db.session.add(node);panel.db.session.commit()
        with patch('health.subprocess.run') as run:
            run.return_value.returncode=3;run.return_value.stdout='inactive'
            panel.health.scan()
        result=panel.db.session.get(panel.health.Health,node.id)
        self.assertFalse(result.ok);self.assertIn('inactive',result.detail)
