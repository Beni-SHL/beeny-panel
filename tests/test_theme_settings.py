import copy,json,unittest
from bs4 import BeautifulSoup
import test_customer as fixture
from test_customer import panel
from theme_settings import DEFAULT,clean

class ThemeSettingsTests(unittest.TestCase):
 setUp=fixture.CustomerFlowTests.setUp
 tearDown=fixture.CustomerFlowTests.tearDown
 csrf=fixture.CustomerFlowTests.csrf
 admin=fixture.CustomerFlowTests.admin
 def test_defaults_and_colors_validate_without_mutating_source(self):
  value=clean(copy.deepcopy(DEFAULT));value['customer']['dark']['colors'][0]='#123456'
  self.assertNotEqual(value,DEFAULT)
  for invalid in ('red','#fff','</style>',None,12):
   item=copy.deepcopy(DEFAULT);item['admin']['dark']['tint']=invalid
   with self.assertRaises(ValueError):clean(item)
  for invalid in (-1,96,True,float('nan'),float('inf')):
   item=copy.deepcopy(DEFAULT);item['customer']['light']['opacity']=invalid
   with self.assertRaises(ValueError):clean(item)
  item=copy.deepcopy(DEFAULT);item['admin']['custom_css']='body{}'
  with self.assertRaises(ValueError):clean(item)
 def test_save_requires_owner_and_csrf_and_is_persistent_on_customer_pages(self):
  path='/panel/settings/theme';config=copy.deepcopy(DEFAULT);config['customer']['light']['colors']=['#112233','#445566','#aabbcc'];config['admin']['dark']['blur']=12
  self.assertEqual(self.client.post(path,json=config).status_code,302)
  csrf=self.csrf();self.admin()
  self.assertEqual(self.client.post(path,json=config,headers={'X-CSRF-Token':''}).status_code,400)
  res=self.client.post(path,json=config,headers={'X-CSRF-Token':csrf});self.assertEqual(res.status_code,200,res.data);self.assertTrue(res.json['success'])
  self.assertEqual(json.loads(self.features.get_setting('appearance_v1')),config)
  doc=BeautifulSoup(self.client.get('/panel/c/'+self.token).data,'html.parser');received=json.loads(doc.select_one('#beeny-theme-config').string)
  self.assertEqual(received,config)
 def test_nonowner_cannot_read_or_mutate_studio(self):
  csrf=self.csrf();self.admin();owner=panel.Admin.query.first();owner.role='viewer';panel.db.session.commit()
  self.assertEqual(self.client.get('/panel/settings/theme').status_code,403)
  self.assertEqual(self.client.post('/panel/settings/theme',json=DEFAULT,headers={'X-CSRF-Token':csrf}).status_code,403)
  self.assertEqual(self.features.get_setting('appearance_v1','missing'),'missing')
 def test_invalid_save_does_not_replace_saved_theme(self):
  csrf=self.csrf();self.admin();self.features.set_setting('appearance_v1',json.dumps(DEFAULT));panel.db.session.commit()
  item=copy.deepcopy(DEFAULT);item['admin']['dark']['colors'][0]='url(https://bad.example)'
  self.assertEqual(self.client.post('/panel/settings/theme',json=item,headers={'X-CSRF-Token':csrf}).status_code,400)
  self.assertEqual(panel.appearance.load(),DEFAULT)
 def test_studio_has_both_modes_live_controls_and_hub_link(self):
  self.admin()
  for lang in ('fa','en'):
   panel.Admin.query.first().language=lang;panel.db.session.commit()
   doc=BeautifulSoup(self.client.get('/panel/settings/theme').data,'html.parser')
   self.assertEqual(len(doc.select('[data-theme-color]')),3)
   self.assertEqual({o['value'] for o in doc.select('[data-theme-scope] option')},{'admin','customer'})
   self.assertEqual({o['value'] for o in doc.select('[data-theme-mode] option')},{'light','dark'})
   self.assertEqual(len(doc.select('[data-theme-preset]')),5)
   self.assertTrue(doc.select_one('[data-theme-preview]'))
   self.assertIn('/settings/theme',self.client.get('/panel/settings').get_data(as_text=True))
 def test_profile_form_has_one_inside_eye_and_wallet_payment_after_card_transfer(self):
  self.admin()
  for path in ('/panel/users/add','/panel/users/view/'+str(self.user.id)):
   doc=BeautifulSoup(self.client.get(path).data,'html.parser')
   self.assertEqual(len(doc.select('.profile-password-field [data-profile-password-toggle]')),1)
   self.assertFalse(doc.select('.password-tools [data-password-toggle]'))
  doc=BeautifulSoup(self.client.get('/panel/users/view/'+str(self.user.id)).data,'html.parser')
  self.assertTrue(doc.select_one('details.ac-usage.profile-section>summary'))
  csrf=self.csrf();preview=self.client.post('/panel/users/view/'+str(self.user.id)+'/portal',data={'csrf':csrf})
  link=BeautifulSoup(preview.data,'html.parser').select_one('.private-page-preview');self.assertTrue(link)
  self.token=link['href'].rsplit('/',1)[1]
  self.csrf();doc=BeautifulSoup(self.client.get('/panel/c/'+self.token).data,'html.parser');form=doc.select_one('#renewal-form')
  order=[el for el in form.find_all(['section','div']) if el.get('class') and ('payment-grid' in el['class'] or 'renew-wallet-payment' in el['class'])]
  self.assertEqual([el['class'][0] for el in order],['payment-grid','renew-wallet-payment'])
  self.assertTrue(form.select_one('.renew-wallet-payment>div>small [data-wallet-balance-number]'))
  self.assertTrue(doc.select_one('.portal-renew-cta.rainbow-button'))

if __name__=='__main__':unittest.main()
