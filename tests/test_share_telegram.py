import unittest
from unittest.mock import patch
import test_customer as fixture
from test_customer import panel

class TelegramCredentialTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    admin=fixture.CustomerFlowTests.admin
    def fields(self):
        self.admin()
        with self.client.session_transaction() as session:csrf=session['_customer_csrf']
        link=panel.db.session.get(panel.AccountLink,self.user.id)
        panel.db.session.add(panel.customer_features.TelegramAccount(user_id=self.user.id,chat_id=123,link_hash=link.token_hash));panel.db.session.commit()
        return {'csrf':csrf,'password':'customer-password-123','url':'http://localhost/panel/c/'+self.token}
    def test_verified_binding_password_and_escaped_code(self):
        fields=self.fields();url='/panel/users/view/'+str(self.user.id)+'/share-telegram'
        with patch.object(panel.customer_features,'telegram') as send:
            self.assertEqual(self.client.post(url,data={**fields,'password':'wrong'}).status_code,400)
            self.assertEqual(self.client.post(url,data={**fields,'url':'https://evil.example/panel/c/'+self.token}).status_code,400)
            send.assert_not_called()
            self.assertEqual(self.client.post(url,data=fields).status_code,200)
            args=send.call_args.args
            self.assertEqual(args[1]['parse_mode'],'HTML');self.assertEqual(args[1]['chat_id'],123)
            self.assertIn('<code>customer-password-123</code>',args[1]['text'])
    def test_english_message_keeps_verified_recipient_and_password(self):
        fields=self.fields();url='/panel/users/view/'+str(self.user.id)+'/share-telegram'
        with patch.object(panel.customer_features,'telegram') as send:
            self.assertEqual(self.client.post(url,data={**fields,'language':'en'}).status_code,200)
            message=send.call_args.args[1]
            self.assertEqual(message['chat_id'],123)
            self.assertIn('Your Beeny account details:',message['text'])
            self.assertIn('<code>customer-password-123</code>',message['text'])
            self.assertNotIn('سلام',message['text'])
            send.reset_mock()
            self.assertEqual(self.client.post(url,data={**fields,'language':'invalid'}).status_code,400)
            send.assert_not_called()
    def test_rotated_binding_and_missing_csrf_cannot_send(self):
        fields=self.fields();url='/panel/users/view/'+str(self.user.id)+'/share-telegram'
        panel.customer_features.TelegramAccount.query.one().link_hash='b'*64;panel.db.session.commit()
        with patch.object(panel.customer_features,'telegram') as send:
            self.assertEqual(self.client.post(url,data={**fields,'csrf':'wrong'}).status_code,400)
            self.assertEqual(self.client.post(url,data=fields).status_code,409)
            send.assert_not_called()
