"""Private uploaded tutorials: actual media probe, range serving and cleanup."""
import io,json,tempfile,subprocess,shutil,unittest
from pathlib import Path
import test_customer as fixture
from test_customer import panel

class VideoUploadTests(unittest.TestCase):
    setUp=fixture.CustomerFlowTests.setUp
    tearDown=fixture.CustomerFlowTests.tearDown
    csrf=fixture.CustomerFlowTests.csrf
    admin=fixture.CustomerFlowTests.admin
    @classmethod
    def setUpClass(cls):
        if not shutil.which('ffmpeg'):raise unittest.SkipTest('ffmpeg unavailable')
        cls.temp=tempfile.TemporaryDirectory();path=Path(cls.temp.name)/'tiny.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=160x90:d=0.3','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart','-y',str(path)],check=True)
        cls.movie=path.read_bytes()
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def add(self,**changes):
        self.admin()
        with self.client.session_transaction() as state:self.csrf_token=state['_customer_csrf']
        data=dict(csrf=self.csrf_token,action='video',title='Android',title_en='Android guide',url='',video_file=(io.BytesIO(self.movie),'tutorial.mp4'),cover=(io.BytesIO(fixture.jpeg()),'cover.jpg'))
        data.update(changes)
        return self.client.post('/panel/settings/portal-content',data=data,headers={'Accept':'application/json'})
    def test_upload_validates_real_file_and_saves_landscape_cover(self):
        response=self.add();self.assertEqual(response.status_code,200);self.assertTrue(response.json['ok'])
        video=panel.portal_content.config()['videos'][0]
        self.assertEqual(video['url'],'');self.assertTrue(video['file'].endswith('.mp4'))
        self.assertEqual((panel.portal_content.video_storage/video['file']).read_bytes(),self.movie)
        from PIL import Image
        self.assertEqual(Image.open(self.features.storage/video['cover']).size,(1280,720))
        self.assertEqual((panel.portal_content.video_storage/video['file']).stat().st_mode&0o777,0o600)
    def test_private_video_requires_login_and_supports_range(self):
        self.add();video=panel.portal_content.config()['videos'][0];url='/panel/c/'+self.token+'/video/'+video['id']
        self.assertEqual(panel.app.test_client().get(url).status_code,302)
        self.csrf();response=self.client.get(url,headers={'Range':'bytes=0-31'})
        self.assertEqual(response.status_code,206);self.assertEqual(response.data,self.movie[:32]);self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(self.client.get('/panel/c/'+self.token+'/video/nonexistent').status_code,404)
    def test_owner_preview_and_delete_remove_video_and_cover(self):
        self.add();video=panel.portal_content.config()['videos'][0]
        self.assertEqual(self.client.get('/panel/settings/portal-content/videos/'+video['id']).status_code,200)
        response=self.client.post('/panel/settings/portal-content',data={'csrf':self.csrf_token,'action':'delete_video','id':video['id']})
        self.assertEqual(response.status_code,302)
        self.assertFalse((panel.portal_content.video_storage/video['file']).exists());self.assertFalse((self.features.storage/video['cover']).exists())
    def test_invalid_file_or_two_sources_cannot_create_tutorial(self):
        before=set(panel.portal_content.video_storage.glob('*'))
        self.assertEqual(self.add(video_file=(io.BytesIO(b'not a video'),'fake.mp4')).status_code,400)
        self.assertEqual(self.add(video_file=(io.BytesIO(b'print(1)'),'bad.py')).status_code,400)
        self.assertEqual(self.add(url='https://cdn.example/video.mp4').status_code,400)
        self.assertEqual(panel.portal_content.config().get('videos',[]),[]);self.assertEqual(set(panel.portal_content.video_storage.glob('*')),before)
    def test_bad_cover_cleans_new_video_and_preserves_previous_source(self):
        self.add();old=panel.portal_content.config()['videos'][0];before=set(panel.portal_content.video_storage.glob('*'))
        result=self.add(id=old['id'],cover=(io.BytesIO(b'invalid image'),'fake.png'))
        self.assertEqual(result.status_code,400);self.assertEqual(panel.portal_content.config()['videos'][0]['file'],old['file'])
        self.assertEqual(set(panel.portal_content.video_storage.glob('*')),before)
    def test_switch_to_external_url_removes_previous_upload(self):
        self.add();old=panel.portal_content.config()['videos'][0]
        self.assertEqual(self.add(id=old['id'],url='https://cdn.example/new.mp4',video_file=(io.BytesIO(b''),'')).status_code,200)
        new=panel.portal_content.config()['videos'][0];self.assertNotIn('file',new);self.assertEqual(new['url'],'https://cdn.example/new.mp4')
        self.assertFalse((panel.portal_content.video_storage/old['file']).exists())
    def test_total_request_limit_runs_before_csrf_form_parsing(self):
        self.admin();response=self.client.post('/panel/settings/portal-content',data=b'x',content_type='multipart/form-data; boundary=x',environ_overrides={'CONTENT_LENGTH':str(230*1024*1024)})
        self.assertEqual(response.status_code,413)
    def test_nonowner_cannot_upload_or_preview(self):
        self.add();video=panel.portal_content.config()['videos'][0]
        owner=panel.Admin.query.first();owner.role='support';panel.db.session.commit()
        self.assertEqual(self.client.get('/panel/settings/portal-content/videos/'+video['id']).status_code,403)
        self.assertEqual(self.client.post('/panel/settings/portal-content',data={'csrf':self.csrf_token,'action':'video'}).status_code,403)
