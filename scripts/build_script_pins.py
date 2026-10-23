#!/usr/bin/env python3
"""Pin AJAX page programs to the exact local source bytes in this release.
Run after deliberately editing a page JavaScript file; this is not an AV bypass.
"""
import base64
import hashlib
import json
import re
from pathlib import Path
root = Path(__file__).resolve().parents[1]
customer_names=['portal.js','avatar-theme.js','bank-carousel.js','pricing.js','refinement.js','studio.js','portal-content.js','polish.js','release-344.js','commissions.js','experience.js','flags.js','notification-feed.js','customer-controls.js','action-buttons.js']
customer_pins={name:'sha256-'+base64.b64encode(hashlib.sha256((root/'static/js'/name).read_bytes()).digest()).decode() for name in customer_names}
loader=root/'static/js/customer-navigation.js'
text,count=re.subn(r'const programs=\{.*?\};','const programs='+json.dumps(customer_pins,indent=2)+';',loader.read_text(),count=1,flags=re.S)
if count!=1:raise SystemExit('Customer program manifest missing.')
loader.write_text(text)
names = set()
for page in (root / 'templates').rglob('*.html'):
    if page.name in {'system2.html', 'users2.html', 'users22.html', 'client.html'}:
        continue
    names.update(re.findall(r'''<script[^>]+src="{{\s*url_for\(['"]static['"],\s*filename=['"]js/([^'"]+)['"]''', page.read_text()))
names -= {'admin-forms.js', 'background-loader.js'}
pins = {name: 'sha256-' + base64.b64encode(hashlib.sha256((root / 'static/js' / name).read_bytes()).digest()).decode() for name in sorted(names)}
target = root / 'static/js/admin-forms.js'
text, count = re.subn(r'const approvedScripts=\{.*?\};', 'const approvedScripts=' + json.dumps(pins, indent=2) + ';', target.read_text(), count=1, flags=re.S)
if count != 1:
    raise SystemExit('Script pin manifest missing; no file written.')
target.write_text(text)
print(f'Pinned {len(pins)} local page programs.')
