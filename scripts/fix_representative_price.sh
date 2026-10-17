#!/usr/bin/env bash
# Narrow 3.6.1 price-save fix: no database changes or service restarts.
set -Eeuo pipefail
python3 - <<'PY'
from pathlib import Path
from datetime import datetime, timezone
import shutil
root=Path('/opt/beeny-panel')
p=root/'static/js/representative-credit.js'
if not p.is_file():raise SystemExit('Installed representative JavaScript not found.')
s=p.read_text()
old="fetch(form.action,{method:'POST'"
new="fetch(new URL(form.getAttribute('action')||location.href,document.baseURI).href,{method:'POST'"
if old not in s:
    if new in s:print('The price action URL is already fixed.');raise SystemExit(0)
    raise SystemExit('Expected 3.6.1 code not found; no changes made. Use the full compatible update.')
fixed=s.replace(old,new)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup=root/'backups'/('price-hotfix-'+stamp)
backup.mkdir(parents=True,mode=0o700)
shutil.copy2(p,backup/'representative-credit.js')
p.write_text(fixed)
# Bust the cached browser script using the actual filename attribute.
for name in ['representative_shell.html','representative_credit_admin.html','representative_login.html']:
    template=root/'templates'/name
    if not template.is_file():continue
    content=template.read_text()
    marker="filename='js/representative-credit.js')"
    if marker in content:
        shutil.copy2(template,backup/name)
        template.write_text(content.replace(marker,"filename='js/representative-credit.js',v='price-action-hotfix-362')"))
print('Representative price URL fixed. Backup:',backup)
print('Reload the representative page with Ctrl+F5 and retry the price in Toman.')
print('No database changes or service restarts. VERSION remains unchanged; full 3.6.2 also improves error feedback.')
PY
