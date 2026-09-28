#!/usr/bin/env bash
# Update an installed panel without touching its database, VPN keys or environment.
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/beeny-panel
FILES=(app.py cluster.py renewal.py traffic_ledger.py serve.py scripts/create_vpn_user.sh scripts/check_users.py templates/login.html templates/layout.html templates/dashboard.html templates/traffic.html templates/customer_portal.html templates/user_form.html templates/user_profile.html templates/users.html templates/nodes.html static/css/account.css static/css/style.css static/css/brand.css static/css/light-pages.css static/css/login.css static/css/portal.css static/fonts/Vazirmatn-variable.woff2 static/beeny-mark.svg)
if [[ "${1:-}" != '' && "${1:-}" != '--check' && "${1:-}" != '--verify' ]]; then
  echo 'Usage: sudo bash scripts/update_panel.sh [--check|--verify]' >&2; exit 2
fi
for rel in "${FILES[@]}"; do
  [[ -f "$ROOT_DIR/$rel" ]] || { echo "Missing update file: $rel" >&2; exit 1; }
done
python3 -m py_compile "$ROOT_DIR/app.py" "$ROOT_DIR/cluster.py" "$ROOT_DIR/renewal.py" "$ROOT_DIR/traffic_ledger.py" "$ROOT_DIR/serve.py"
bash -n "$ROOT_DIR/scripts/create_vpn_user.sh"
[[ -f "$DEST/app.py" && -f "$DEST/config.json" && -f /etc/beeny-panel/panel.env &&
   -d "$DEST/instance" && -x "$DEST/venv/bin/python" ]] || {
  echo 'The installed panel was not found; refusing to update.' >&2; exit 1
}
"$DEST/venv/bin/python" - "$ROOT_DIR/templates" <<'PY'
from jinja2 import Environment, FileSystemLoader
import sys
env = Environment(loader=FileSystemLoader(sys.argv[1]))
for name in ('login.html', 'layout.html', 'dashboard.html', 'traffic.html', 'customer_portal.html', 'user_form.html', 'user_profile.html', 'users.html', 'nodes.html'):
    env.get_template(name)
print('Account templates compile successfully.')
PY
verify_deployed() {
  local rel
  for rel in "${FILES[@]}"; do
    cmp -s "$ROOT_DIR/$rel" "$DEST/$rel" || {
      echo "Installed file differs from update: $rel" >&2; return 1;
    }
  done
  "$DEST/venv/bin/python" - "$DEST" <<'PY'
import json, pathlib, sqlite3, sys, time, urllib.request
root = pathlib.Path(sys.argv[1])
cfg = json.loads((root / 'config.json').read_text())
path = cfg['panel_path'].rstrip('/')
env = dict(line.split('=', 1) for line in pathlib.Path('/etc/beeny-panel/panel.env').read_text().splitlines() if '=' in line)
url = f"http://127.0.0.1:{env['BEENY_PORT']}{path}/login"
for attempt in range(6):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            html = response.read().decode('utf-8')
        if 'Remember me on this device' not in html or 'Your network,' not in html:
            raise RuntimeError('The running login page is an older template')
        break
    except (OSError, RuntimeError):
        if attempt == 5:
            raise
        time.sleep(1)
db_path = root / 'instance' / 'beeny.db'
with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
    count = db.execute("SELECT COUNT(*) FROM nodes WHERE api_key='__beeny_local_primary__'").fetchone()[0]
if count != 1:
    raise RuntimeError('Primary server node was not registered')
print('Live English login and primary node verified.')
PY
}
if [[ "${1:-}" == '--check' ]]; then echo 'Update source and installed panel found.'; exit 0; fi
if [[ "${1:-}" == '--verify' ]]; then verify_deployed; exit; fi
[[ $EUID == 0 ]] || { echo 'Run with sudo or as root.' >&2; exit 1; }
backup_dir="$DEST/backups/update-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup_dir"
for rel in "${FILES[@]}"; do
  install -d -m 755 "$DEST/$(dirname "$rel")"
  if [[ -f "$DEST/$rel" ]]; then
    install -d -m 700 "$backup_dir/$(dirname "$rel")"
    cp -p "$DEST/$rel" "$backup_dir/$rel"
  fi
  install -m 644 "$ROOT_DIR/$rel" "$DEST/$rel"
done
chmod 700 "$DEST/scripts/create_vpn_user.sh"
systemctl restart beeny-panel || true
if ! systemctl is-active --quiet beeny-panel || ! verify_deployed; then
  for rel in "${FILES[@]}"; do
    if [[ -f "$backup_dir/$rel" ]]; then cp -p "$backup_dir/$rel" "$DEST/$rel"; else rm -f "$DEST/$rel"; fi
  done
  systemctl restart beeny-panel || true
  echo 'Panel update failed; code restored from backup. Check journalctl -u beeny-panel -n 100.' >&2
  exit 1
fi
printf 'Panel updated. Previous code: %s\n' "$backup_dir"
echo 'Database, VPN certificates and panel.env were preserved.'
