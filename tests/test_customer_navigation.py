import copy,json,unittest
from bs4 import BeautifulSoup
import test_customer as fixture
from theme_settings import DEFAULT,clean
from test_customer import panel
class CustomerNavigation(unittest.TestCase):
 setUp=fixture.CustomerFlowTests.setUp
 tearDown=fixture.CustomerFlowTests.tearDown
 csrf=fixture.CustomerFlowTests.csrf
 admin=fixture.CustomerFlowTests.admin
 def test_legacy_theme_migrates_preserving_custom_values(self):
  old=copy.deepcopy(DEFAULT);old['customer'].pop('avatar');old['customer'].pop('navigation');old['customer']['background_intensity']=37
  for mode in ('dark','light'):old['customer'][mode].pop('background_intensity')
  old['customer']['dark']['icons']='#123456'
  result=clean(old);self.assertEqual(result['customer']['dark']['icons'],'#123456');self.assertEqual(result['customer']['dark']['background_intensity'],37);self.assertEqual(result['customer']['navigation'],DEFAULT['customer']['navigation'])
 def test_navigation_rejects_unknown_duplicates_empty_and_avatar_ranges(self):
  for items in ([],['overview','overview'],['https://example.com'],['__proto__'],[1]):
   cfg=copy.deepcopy(DEFAULT);cfg['customer']['navigation']['items']=items
   with self.assertRaises(ValueError):clean(cfg)
  for value in (-1,101,True,float('nan')):
   cfg=copy.deepcopy(DEFAULT);cfg['customer']['avatar']['strength']=value
   with self.assertRaises(ValueError):clean(cfg)
 def test_saved_order_materials_and_body_dock_on_wallet_and_portal(self):
  self.admin();cfg=copy.deepcopy(DEFAULT);cfg['customer']['navigation']={'items':['wallet','renew','overview','configs','devices','tickets'],'liquid_background':False,'liquid_buttons':True};cfg['customer']['light']['background_intensity']=23;cfg['customer']['dark']['background_intensity']=61
  csrf=self.csrf();res=self.client.post('/panel/settings/theme',json=cfg,headers={'X-CSRF-Token':csrf});self.assertEqual(res.status_code,200)
  for suffix in ('','/wallet','/devices','/tickets'):
   res=self.client.get('/panel/c/'+self.token+suffix);self.assertEqual(res.status_code,200)
   doc=BeautifulSoup(res.data,'html.parser');nav=doc.select_one('body>.account-dock');self.assertIsNotNone(nav,suffix)
   self.assertEqual([a['data-dock-section'] for a in nav.select('a')],cfg['customer']['navigation']['items']);self.assertEqual(nav['data-liquid-background'],'false');self.assertEqual(nav['data-liquid-buttons'],'true')
   self.assertEqual(nav.select_one('[data-dock-section=renew]')['href'],'/panel/c/'+self.token+'#renew')
   if suffix:self.assertEqual(nav.select_one('[aria-current=page]')['data-dock-section'],suffix[1:])
   self.assertEqual(json.loads(doc.select_one('#beeny-theme-config').string)['customer']['dark']['background_intensity'],61)
 def test_native_visible_theme_glyphs_and_add_icon(self):
  self.admin();self.csrf()
  for path in ('/panel/users','/panel/c/'+self.token,'/panel/c/'+self.token+'/wallet'):
   doc=BeautifulSoup(self.client.get(path).data,'html.parser');self.assertTrue(doc.select_one('.control-sun svg path'),path);self.assertTrue(doc.select_one('.control-moon svg path'),path)
   if path=='/panel/users':self.assertTrue(doc.select_one('.users-add-button svg path'));self.assertFalse(doc.select('#themeToggle .fa'))
 def test_studio_exposes_navigation_and_avatar_controls(self):
  self.admin();doc=BeautifulSoup(self.client.get('/panel/settings/theme').data,'html.parser')
  self.assertEqual(len(doc.select('[data-nav-choice] option')),6)
  self.assertEqual(len(doc.select('[data-customer-group=avatar]')),7)
  self.assertEqual(len(doc.select('[data-customer-group=navigation]')),2)
if __name__=='__main__':unittest.main()
