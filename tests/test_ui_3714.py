"""Contract checks for the shared header, real notification state and credentials."""
from pathlib import Path
import unittest
from bs4 import BeautifulSoup
import test_customer as fixture
from test_customer import panel

class UnifiedUI(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    def doc(self,path):
        response=self.client.get(path,follow_redirects=True)
        self.assertEqual(response.status_code,200)
        return BeautifulSoup(response.data,'html.parser')

    def test_login_single_theme_control_language_and_real_health_form(self):
        for lang in ('en','fa'):
            for path in ('/panel/login?lang='+lang,'/panel/c/'+self.token+'/login?lang='+lang,'/panel/representatives/login?lang='+lang):
                doc=self.doc(path)
                self.assertEqual(doc.html['lang'],lang)
                self.assertEqual(len(doc.select('#auth-theme')),1)
                self.assertEqual(len(doc.select('.auth-language')),1)
                self.assertFalse(doc.select('#light,#dark'))
                form=doc.select_one('form[method=post]')
                self.assertTrue(form.select_one('input[name=csrf]')['value'])
                self.assertEqual(form.select_one('[name=password]')['type'],'password')

    def test_portal_and_subpages_use_same_header_and_four_section_dock(self):
        self.csrf()
        for lang in ('en','fa'):
            with self.client.session_transaction() as session:session['customer_language']=lang
            for suffix in ('','/wallet','/tickets','/devices'):
                doc=self.doc('/panel/c/'+self.token+suffix)
                self.assertEqual(len(doc.select('.customer-shell-header.workspace-top')),1)
                self.assertEqual(len(doc.select('.shell-controls>.notification-center,.shell-controls>.language-picker,.shell-controls>.shell-theme,.shell-controls>.account-menu')),4)
                self.assertEqual([a['data-dock-section'] for a in doc.select('.account-dock>a')],['overview','renew','configs','tickets'])
                self.assertTrue(doc.select_one('script[src*="notification-feed.js"]'))
                self.assertFalse(doc.select('.shell-nav,.mobile-shortcuts'))
                self.assertTrue(doc.select_one('#react-bg-root.beeny-background-customer'))

    def test_profile_collapsible_sections_password_eye_and_settings_shortcut(self):
        self.admin();doc=self.doc('/panel/users/view/'+str(self.user.id))
        self.assertEqual(len(doc.select('.ac-heading .ac-icon-only')),4)
        sections=doc.select('.ac-profile-grid>aside>details.profile-section')
        self.assertEqual(len(sections),4)
        self.assertTrue(all(s.select_one(':scope>summary') for s in sections))
        self.assertTrue(doc.select_one('.profile-password-field input#portal_password'))
        self.assertTrue(doc.select_one('.profile-password-field [data-profile-password-toggle]'))
        self.assertFalse(doc.select('.password-tools [data-password-toggle]'))
        self.assertTrue(doc.select_one('.share-toolbar [data-share-clear][aria-label] svg'))
        self.assertNotIn('Account actions',doc.get_text())
        add=self.doc('/panel/users/add')
        self.assertTrue(add.select_one('.profile-password-field [data-profile-password-toggle]'))

    def test_notification_read_state_clear_scope_and_csrf(self):
        csrf=self.csrf()
        panel.experience.notify(self.user.id,'My alert','My body')
        panel.experience.notify(self.other.id,'Other alert','Private body')
        panel.experience.notify(None,'Admin alert','Staff only')
        panel.db.session.commit()
        url='/panel/c/'+self.token+'/notifications'
        before=self.client.get(url).json
        self.assertEqual([r['title'] for r in before['items']],['My alert'])
        self.assertFalse(before['items'][0]['read'])
        self.assertEqual(self.client.post(url+'/clear',data={'upto':before['latest_id']}).status_code,400)
        self.client.post(url+'/read',data={'csrf':csrf,'upto':before['latest_id']})
        self.assertTrue(self.client.get(url).json['items'][0]['read'])
        self.client.post(url+'/clear',data={'csrf':csrf,'upto':before['latest_id']})
        self.assertEqual(self.client.get(url).json['items'],[])
        self.assertTrue(panel.experience.Notification.query.filter_by(user_id=self.other.id).one().cleared_at is None)
        self.admin();feed=self.client.get('/panel/notifications').json
        self.assertIn('Admin alert',[r['title'] for r in feed['items']])
        self.assertFalse(any(r['title'] in ('My alert','Other alert') for r in feed['items']))
        self.assertFalse(feed['items'][0]['read'])
        self.client.post('/panel/notifications/read',data={'csrf':csrf,'upto':feed['latest_id']})
        self.assertTrue(self.client.get('/panel/notifications').json['items'][0]['read'])

    def test_local_font_files_and_no_external_refraction_fetch(self):
        root=Path(__file__).resolve().parents[1]
        for w in (400,500,600,700,800,900):
            self.assertGreater((root/f'static/fonts/peyda/Peyda-{w}.woff2').stat().st_size,40000)
        css=(root/'static/css/typography.css').read_text()
        self.assertNotIn('Yekan',css)
        self.assertIn('BeenyPeyda',css)
        self.assertIn('data:image/webp;base64,',(root/'templates/partials/liquid_filter.html').read_text())

if __name__=='__main__':unittest.main()
