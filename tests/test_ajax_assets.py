"""Release consistency checks supplement the browser injection/SRI tests."""
import base64
import hashlib
import json
import re
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AjaxAssetTests(unittest.TestCase):
    def test_pinned_program_bytes_match_release(self):
        source=(ROOT/'static/js/admin-forms.js').read_text()
        pins=json.loads(re.search(r'const approvedScripts=(\{.*?\});',source,re.S)[1])
        self.assertIn('users-page.js',pins)
        self.assertIn('dashboard-page.js',pins)
        for name,expected in pins.items():
            self.assertEqual(Path(name).name,name)
            digest=hashlib.sha256((ROOT/'static/js'/name).read_bytes()).digest()
            self.assertEqual('sha256-'+base64.b64encode(digest).decode(),expected,name)
    def test_page_runtime_values_are_inert_json(self):
        for name in ('users','dashboard'):
            source=(ROOT/'templates'/f'{name}.html').read_text()
            programs=re.findall(r'<script([^>]*)>(.*?)</script>',source,re.S)
            for attrs,body in programs:
                if 'src=' not in attrs:self.assertIn('application/json',attrs)
            self.assertNotIn('{{',(ROOT/'static/js'/f'{name}-page.js').read_text())
