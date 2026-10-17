import json, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import bandwidth
import test_customer as fixture
from test_customer import panel

class SpeedQueueTests(unittest.TestCase):
    def test_default_fq_supported_but_custom_queue_rejected(self):
        with patch.object(bandwidth,'qdiscs',return_value=[dict(root=True,kind='fq',handle='0:')]),patch.object(bandwidth,'run') as run:
            bandwidth.ensure_root('tun0');run.assert_called_once()
        with patch.object(bandwidth,'qdiscs',return_value=[dict(root=True,kind='fq',handle='1234:')]),patch.object(bandwidth,'run') as run:
            with self.assertRaises(ValueError):bandwidth.ensure_root('tun0')
            run.assert_not_called()
    def test_upload_filter_is_not_recreated_on_repeated_policy(self):
        link=dict(ifalias='beeny-speed:tun0',linkinfo=dict(info_kind='ifb'))
        filters=[dict(pref=49152,kind='matchall')]
        with patch.object(bandwidth.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps([link]))),patch.object(bandwidth,'qdiscs',return_value=[dict(kind='ingress')]),patch.object(bandwidth,'ensure_root'),patch.object(bandwidth,'run',return_value=json.dumps(filters)) as run:
            bandwidth.ensure_upload('tun0');bandwidth.ensure_upload('tun0')
            self.assertFalse(any(c.args[:2]==('tc','filter') and c.args[2]!='show' for c in run.call_args_list))
    def test_foreign_ingress_is_preserved(self):
        link=dict(ifalias='beeny-speed:tun0',linkinfo=dict(info_kind='ifb'))
        with patch.object(bandwidth.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps([link]))),patch.object(bandwidth,'qdiscs',return_value=[dict(kind='ingress')]),patch.object(bandwidth,'ensure_root'),patch.object(bandwidth,'run',return_value=json.dumps([dict(pref=42,kind='flower')])) as run:
            with self.assertRaises(ValueError):bandwidth.ensure_upload('tun0')
            self.assertFalse(any(c.args[:3] in [('tc','filter','del'),('tc','filter','add')] for c in run.call_args_list))

class InboxPagingTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    def test_private_pagination_shows_all_own_tickets_without_other_account(self):
        for n in range(25):panel.db.session.add(panel.support.Ticket(user_id=self.user.id,username=self.user.username,subject=f'Own {n:02}'))
        panel.db.session.add(panel.support.Ticket(user_id=self.other.id,username=self.other.username,subject='Other secret'))
        panel.db.session.commit();self.csrf();url='/panel/c/'+self.token+'/tickets'
        import re
        seen=set()
        for page in [1,2,3]:
            response=self.client.get(url+'?page='+str(page));self.assertEqual(response.status_code,200)
            rows=re.findall(rb'<span class="thread-title"><b>(Own [0-9]+)</b>',response.data)
            self.assertLessEqual(len(rows),12);seen.update(rows)
            self.assertNotIn(b'Other secret',response.data)
        self.assertEqual(len(seen),25)
    def test_community_settings_menu_retains_panel_path(self):
        self.admin();response=self.client.get('/panel/settings/portal-content')
        self.assertEqual(response.status_code,200);self.assertIn(b'href="/panel/users"',response.data)
        self.assertNotIn(b'href="/users"',response.data)
