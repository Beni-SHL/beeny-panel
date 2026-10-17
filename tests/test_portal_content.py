import unittest, json, io
import test_customer as fixture
from test_customer import panel

class PortalContentTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    def home(self):return '/panel/c/'+self.token
    def test_announcements_private_acknowledgement_and_idempotence(self):
        row=panel.portal_content.Announcement(title='<script>alert(1)</script>',body='Private news')
        panel.db.session.add(row);panel.db.session.commit();url=self.home()
        self.assertEqual(self.client.get(url).status_code,302)
        csrf=self.csrf();body=self.client.get(url).data
        self.assertIn(b'data-announcement=',body);self.assertIn(b'&lt;script&gt;',body)
        ack=url+'/announcements/'+str(row.id)+'/seen'
        self.assertEqual(self.client.post(ack).status_code,400)
        self.assertEqual(self.client.post(ack,data={'csrf':csrf}).status_code,200)
        self.assertEqual(self.client.post(ack,data={'csrf':csrf}).status_code,200)
        self.assertEqual(panel.portal_content.Seen.query.count(),1)
        self.assertNotIn(b'data-announcement=',self.client.get(url).data)
        self.assertEqual(panel.portal_content.Seen.query.first().user_id,self.user.id)
    def test_owner_can_edit_delete_announcement_and_edit_resets_dismissal(self):
        self.admin();url='/panel/settings/portal-content'
        with self.client.session_transaction() as saved:csrf=saved['_customer_csrf']
        post=lambda **data:self.client.post(url,data={'csrf':csrf,**data})
        self.assertEqual(post(action='announcement',title='News',body='Message',icon='gift',color='violet').status_code,302)
        row=panel.portal_content.Announcement.query.one()
        panel.db.session.add(panel.portal_content.Seen(user_id=self.user.id,announcement_id=row.id));panel.db.session.commit()
        self.assertEqual(post(action='edit_announcement',id=row.id,title='Changed',body='New',icon='warning',color='rose').status_code,302)
        self.assertEqual((row.icon,row.color,row.title),('warning','rose','Changed'))
        self.assertEqual(panel.portal_content.Seen.query.count(),0)
        self.assertEqual(post(action='edit_announcement',id=row.id,title='Changed',body='New',icon='bad',color='rose').status_code,200)
        self.assertEqual(row.icon,'warning')
        self.assertEqual(post(action='delete_announcement',id=row.id).status_code,302)
        self.assertEqual(panel.portal_content.Announcement.query.count(),0)

    def test_owner_content_validates_urls_and_video_updates(self):
        self.admin();url='/panel/settings/portal-content'
        with self.client.session_transaction() as saved:csrf=saved['_customer_csrf']
        self.client.environ_base['HTTP_X_CSRF_TOKEN']=csrf
        post=lambda data:self.client.post(url,data={'csrf':csrf,**data})
        self.assertEqual(post({'channel':'javascript:alert(1)'}).status_code,200)
        self.assertNotIn('channel',panel.portal_content.config())
        self.assertEqual(post({'channel':'https://evil.example/channel'}).status_code,200)
        self.assertEqual(post({'channel':'https://t.me/test','group':'https://t.me/+invite'}).status_code,302)
        self.assertEqual(post({'action':'video','title':'Android','title_en':'Android guide','url':'https://cdn.example/one.mp4','cover':(io.BytesIO(fixture.jpeg()),'cover.jpg')}).status_code,302)
        video=panel.portal_content.config()['videos'][0];self.assertTrue(video['cover'].endswith('.webp'))
        self.assertEqual(post({'action':'video','id':video['id'],'title':'Updated','url':'https://cdn.example/two.mp4'}).status_code,302)
        videos=panel.portal_content.config()['videos'];self.assertEqual(len(videos),1);self.assertEqual(videos[0]['cover'],video['cover'])
        self.assertEqual(post({'action':'delete_video','id':video['id']}).status_code,302)
        self.assertFalse((self.features.storage/video['cover']).exists())
    def test_login_language_before_authentication(self):
        response=self.client.get(self.home()+'/login?lang=en')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Enter your password',response.data)
        self.assertIn(b'lang="en" dir="ltr"',response.data)

    def test_language_is_private_persistent_and_ui_translated(self):
        csrf=self.csrf();url=self.home()
        self.assertEqual(self.client.post(url+'/language',data={'csrf':csrf,'language':'invalid'}).status_code,400)
        self.assertEqual(self.client.post(url+'/language',data={'csrf':csrf,'language':'en'}).status_code,302)
        body=self.client.get(url).data
        self.assertIn(b'lang="en" dir="ltr"',body);self.assertIn(b'Remaining data',body);self.assertIn(b'Hello,',body)
        self.assertIn(self.user.username.encode(),body)
        self.assertEqual(self.client.get(url+'/learn').status_code,200)
    def test_media_allowlist_and_private_access(self):
        name=self.features.store_image(fixture.jpeg(),avatar=True)
        self.features.set_setting('portal_content',json.dumps({'support_avatar':name}));panel.db.session.commit()
        self.assertEqual(self.client.get(self.home()+'/media/'+name).status_code,302)
        self.csrf();response=self.client.get(self.home()+'/media/'+name)
        self.assertEqual(response.status_code,200);self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(self.client.get(self.home()+'/media/secret.webp').status_code,404)
    def test_nonowner_cannot_manage_content(self):
        self.admin();admin=panel.Admin.query.first();admin.role='support';panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/settings/portal-content').status_code,403)
        self.assertEqual(self.client.post('/panel/settings/portal-content',data={'action':'announcement','title':'x','body':'y'}).status_code,403)
    def test_ticket_customer_uploaded_avatar_is_scoped(self):
        self.csrf();profile=panel.db.session.get(self.features.CustomerProfile,self.user.id)
        profile.avatar=self.features.store_image(fixture.jpeg(),avatar=True)
        row=panel.support.Ticket(user_id=self.user.id,username=self.user.username,subject='Help')
        other=panel.support.Ticket(user_id=self.other.id,username=self.other.username,subject='Other')
        panel.db.session.add_all([row,other]);panel.db.session.commit()
        self.assertEqual(self.client.get(self.home()+'/tickets/'+str(row.id)+'/avatar').status_code,200)
        self.assertEqual(self.client.get(self.home()+'/tickets/'+str(other.id)+'/avatar').status_code,404)


class AnnouncementMigrationTests(unittest.TestCase):
    def test_additive_upgrade_preserves_old_notice_and_adds_defaults(self):
        from sqlalchemy import create_engine,text
        from types import SimpleNamespace
        from migrations import upgrade
        engine=create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE portal_announcements(id INTEGER PRIMARY KEY,title TEXT,body TEXT)'))
            connection.execute(text("INSERT INTO portal_announcements VALUES(1,'Old notice','Preserved message')"))
        upgrade(SimpleNamespace(engine=engine,create_all=lambda:None))
        with engine.connect() as connection:
            row=connection.execute(text('SELECT title,body,icon,color FROM portal_announcements')).one()
            self.assertEqual(tuple(row),('Old notice','Preserved message','info','blue'))
        engine.dispose()
