"""Exercise the exact login health predicate embedded in the updater."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin
import unittest
import test_customer as fixture
from test_customer import panel
source=(Path(__file__).resolve().parents[1]/'scripts/update_panel.sh').read_text()
namespace=dict(HTMLParser=HTMLParser,urljoin=urljoin)
exec(source[source.index('class LoginFormParser'):source.index('root=pathlib.Path(sys.argv[1]); cfg=')],namespace)
healthy=namespace['login_form_healthy']
URL='http://127.0.0.1:8080/panel/login'
FORM='<form method="post" action="/panel/login"><input name="username"><input type="password" name="password"><input type="hidden" name="csrf" value="test-token"><button>Sign in</button></form>'

class LoginHealthTests(unittest.TestCase):
    def test_copy_and_language_are_not_health_dependencies(self):
        for copy in ['Remember me','Remember me on this device','مرا به خاطر بسپار','']:
            self.assertTrue(healthy(FORM+copy,URL))

    def test_static_text_and_incomplete_forms_fail(self):
        for html in ['Remember me on this device','<h1>Internal Server Error</h1>',FORM.replace('name="username"','name="other"'),FORM.replace('type="password"','type="text"'),FORM.replace('value="test-token"','value=""'),FORM.replace('method="post"','method="get"')]:
            self.assertFalse(healthy(html,URL),html)

    def test_wrong_target_and_disabled_controls_fail(self):
        for html in [FORM.replace('/panel/login','/other/login'),FORM.replace('/panel/login','https://other.test/login'),FORM.replace('name="username"','disabled name="username"')]:
            self.assertFalse(healthy(html,URL))

    def test_real_latest_login_passes_exact_updater_predicate(self):
        case=fixture.CustomerFlowTests();case.setUp()
        try:
            response=case.client.get('/panel/login')
            self.assertEqual(response.status_code,200)
            self.assertTrue(healthy(response.get_data(as_text=True),URL))
        finally:case.tearDown()
