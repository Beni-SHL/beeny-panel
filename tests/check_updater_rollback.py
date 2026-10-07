"""Run the real updater control flow against a temporary installation and fake systemd."""
import os,shutil,subprocess,tempfile
from pathlib import Path
source=Path(__file__).resolve().parents[1]
import sys
python=sys.executable
for failure in ('database', 'health'):
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); dest=root/'panel'; etc=root/'etc'; run=root/'run'; bins=root/'bin'; release=root/'release'
  shutil.copytree(source,release,ignore=shutil.ignore_patterns('.git','__pycache__','instance','venv','backups'))
  shutil.copytree(release,dest)
  for directory in (etc/'systemd/system',etc/'beeny-panel',run,bins,dest/'instance',dest/'venv/bin'):directory.mkdir(parents=True,exist_ok=True)
  (dest/'app.py').write_text('OLD_APPLICATION = True\n')
  (dest/'config.json').write_text('{"panel_path":"/panel"}')
  (etc/'beeny-panel/panel.env').write_text('BEENY_PORT=8080\n')
  (etc/'systemd/system/beeny-panel.service').write_text('old systemd unit\n')
  (dest/'venv/bin/python').symlink_to(python)
  if failure=='database':(dest/'instance/beeny.db').write_text('invalid database')
  else:
   subprocess.run([python,'-c',f"import sqlite3;sqlite3.connect({str(dest/'instance/beeny.db')!r}).execute('CREATE TABLE sentinel (id INTEGER)')"],check=True)
  (bins/'systemctl').write_text('#!/bin/bash\necho "$*" >> "'+str(root/'systemctl.log')+'"\nexit 0\n')
  # Package staging is prevalidated separately; emulate an already prepared venv.
  (bins/'python3').write_text('#!/bin/bash\nif [[ "${1:-}" == -m && "${2:-}" == venv ]]; then mkdir -p "$3/bin"; cp "'+str(bins/'stage-python')+'" "$3/bin/python"; else exec '+python+' "$@"; fi\n')
  (bins/'stage-python').write_text('#!/bin/bash\nif [[ "${1:-}" == -m && "${2:-}" == pip ]]; then exit 0; fi\nif [[ "${1:-}" == - && "${2:-}" == "'+str(dest)+'" ]]; then cat >/dev/null; exit 1; fi\nexec '+python+' "$@"\n')
  for file in bins.iterdir():file.chmod(0o755)
  script=(release/'scripts/update_panel.sh').read_text().replace('DEST=/opt/beeny-panel','DEST='+str(dest)).replace('/etc/',str(etc)+'/').replace('/run/',str(run)+'/').replace('[[ $EUID == 0 ]]', '[[ 0 == 0 ]]')
  (release/'scripts/update_panel.sh').write_text(script)
  env=dict(os.environ,PATH=str(bins)+':'+os.environ['PATH'])
  result=subprocess.run(['bash',str(release/'scripts/update_panel.sh')],env=env,capture_output=True,text=True)
  assert result.returncode!=0,(failure,result.stdout,result.stderr)
  assert (dest/'app.py').read_text()=='OLD_APPLICATION = True\n',result.stderr
  assert (dest/'venv/bin/python').exists(),result.stderr
  assert (etc/'systemd/system/beeny-panel.service').read_text()=='old systemd unit\n'
  assert 'start beeny-panel' in (root/'systemctl.log').read_text(),result.stderr
  assert list((dest/'backups').glob('update-*')),result.stderr
  print(f'{failure} failure: application, Python environment and prior service restored')
