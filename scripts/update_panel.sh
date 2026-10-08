#!/usr/bin/env bash
# Additive, backed-up upgrade for an existing /opt/beeny-panel installation.
set -Eeuo pipefail
DEST=/opt/beeny-panel
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --github ]]; then
  [[ $EUID == 0 ]] || { echo 'Run with sudo or as root.' >&2; exit 1; }
  command -v git >/dev/null || { echo 'Install git first: apt-get install -y git' >&2; exit 1; }
  checkout="$(mktemp -d /tmp/beeny-release.XXXXXXXX)"
  trap 'rm -rf -- "$checkout"' EXIT
  GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone --depth 1 --branch main https://github.com/Beni-SHL/beeny-panel.git "$checkout"
  if [[ "${2:-}" == --legacy ]]; then
    bash "$checkout/scripts/update_panel.sh" --legacy
  elif [[ -z "${2:-}" ]]; then
    bash "$checkout/scripts/update_panel.sh"
  else
    echo 'Usage: --github [--legacy]' >&2; exit 2
  fi
  exit
fi
MODE="${1:-}"
if [[ "$MODE" == --legacy ]]; then
  python3 "$ROOT_DIR/scripts/upgrade_legacy.py"
  exit
fi
[[ "$MODE" == '' || "$MODE" == --check || "$MODE" == --verify ]] || { echo 'Usage: sudo bash scripts/update_panel.sh [--github [--legacy]|--legacy|--check|--verify]' >&2; exit 2; }
FILES=(app.py cluster.py renewal.py traffic_ledger.py serve.py experience.py customer_features.py customer_worker.py vpn_sessions.py migrations.py VERSION requirements.txt beeny-panel.service beeny-customer-worker.service scripts/create_vpn_user.sh scripts/check_users.py scripts/init_admin.py scripts/manage_user_config.py scripts/update_panel.sh scripts/upgrade_legacy.py scripts/configure_uploads.py)
while IFS= read -r -d '' path; do FILES+=("${path#"$ROOT_DIR/"}"); done < <(find "$ROOT_DIR/templates" "$ROOT_DIR/static" -type f ! -name '*.pyc' -print0)
for rel in "${FILES[@]}"; do [[ -f "$ROOT_DIR/$rel" ]] || { echo "Missing update source: $rel" >&2; exit 1; }; done
[[ -f "$DEST/app.py" && -f "$DEST/config.json" && -f /etc/beeny-panel/panel.env && -f "$DEST/instance/beeny.db" && -d "$DEST/instance" && -x "$DEST/venv/bin/python" ]] || { echo 'Compatible installed panel not found at /opt/beeny-panel.' >&2; exit 1; }
python3 - "$ROOT_DIR" "$DEST/config.json" <<'PY'
import ast, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for name in ('app.py','experience.py','customer_features.py','customer_worker.py','migrations.py','serve.py'):
    ast.parse((root/name).read_text())
config = json.loads(pathlib.Path(sys.argv[2]).read_text())
assert 'panel_path' in config, 'Existing configuration is incompatible'
PY
bash -n "$ROOT_DIR/scripts/create_vpn_user.sh"
verify_deployed() {
  systemctl is-active --quiet beeny-panel || return 1
  "$DEST/venv/bin/python" - "$DEST" <<'PY'
import json, pathlib, sqlite3, sys, time, urllib.request
root=pathlib.Path(sys.argv[1]); cfg=json.loads((root/'config.json').read_text())
env=dict(line.split('=',1) for line in pathlib.Path('/etc/beeny-panel/panel.env').read_text().splitlines() if '=' in line)
url=f"http://127.0.0.1:{env['BEENY_PORT']}{cfg['panel_path'].rstrip('/')}/login"
for attempt in range(10):
    try:
        with urllib.request.urlopen(url,timeout=2) as response:
            html=response.read().decode()
        assert 'Remember me on this device' in html, 'Login health check failed'
        break
    except Exception:
        if attempt==9: raise
        time.sleep(1)
with sqlite3.connect(f'file:{root/"instance/beeny.db"}?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'customer_profiles','renewal_requests','telegram_accounts','customer_settings','account_notifications','admin_notification_reads'}.issubset(tables)
print('Running login and database upgrade verified.')
PY
}
if [[ "$MODE" == --verify ]]; then verify_deployed; systemctl is-active --quiet beeny-customer-worker; exit; fi
if [[ "$MODE" == --check ]]; then echo 'Update source and compatible installation found.'; exit; fi
[[ $EUID == 0 ]] || { echo 'Run with sudo or as root.' >&2; exit 1; }
# Serialize upgrades, including GitHub invocations from multiple terminals.
if [[ "${BEENY_UPDATE_LOCK_FD:-}" == 9 ]]; then
  [[ "$(readlink /proc/self/fd/9)" == /run/beeny-panel-update.lock ]] || { echo 'Invalid inherited update lock.' >&2; exit 1; }
else
  exec 9>/run/beeny-panel-update.lock
fi
flock -n 9 || { echo 'Another Beeny update is running.' >&2; exit 1; }
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup="$DEST/backups/update-$stamp"
next_venv="$DEST/.venv-releases/$stamp"
install -d -m 700 "$backup" "$DEST/.venv-releases"
python3 -m venv "$next_venv"
"$next_venv/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
"$next_venv/bin/python" - "$ROOT_DIR" <<'PY'
import pathlib, sys
from jinja2 import Environment, FileSystemLoader
root=pathlib.Path(sys.argv[1]); env=Environment(loader=FileSystemLoader(root/'templates'))
for file in (root/'templates').rglob('*.html'):
    env.parse(file.read_text())
print('Templates parsed successfully.')
PY
for rel in "${FILES[@]}"; do
  if [[ -f "$DEST/$rel" ]]; then
    install -d -m 700 "$backup/code/$(dirname "$rel")"
    cp -p "$DEST/$rel" "$backup/code/$rel"
  else
    printf '%s\n' "$rel" >> "$backup/new-files"
  fi
done
cp -p "$DEST/config.json" "$backup/config.json"
cp -p /etc/beeny-panel/panel.env "$backup/panel.env"
cp -p "$DEST/.release.json" "$backup/release.json" 2>/dev/null || true
cp -p /etc/systemd/system/beeny-panel.service "$backup/panel-unit"
worker_existed=0
if [[ -f /etc/systemd/system/beeny-customer-worker.service ]]; then worker_existed=1; cp -p /etc/systemd/system/beeny-customer-worker.service "$backup/worker-unit"; fi
panel_was_active=0; worker_was_active=0
systemctl is-active --quiet beeny-panel && panel_was_active=1
systemctl is-active --quiet beeny-customer-worker && worker_was_active=1
swapped=0
rollback() {
  result=$?
  trap - ERR INT TERM
  echo "Update failed; restoring application. Backup: $backup" >&2
  systemctl stop beeny-panel beeny-customer-worker 2>/dev/null || true
  if [[ "$swapped" == 1 ]]; then rm -f "$DEST/venv"; mv "$backup/previous-venv" "$DEST/venv"; fi
  for rel in "${FILES[@]}"; do
    if [[ -f "$backup/code/$rel" ]]; then cp -p "$backup/code/$rel" "$DEST/$rel"; else rm -f "$DEST/$rel"; fi
  done
  if [[ -f "$backup/release.json" ]]; then cp -p "$backup/release.json" "$DEST/.release.json"; else rm -f "$DEST/.release.json"; fi
  install -m 644 "$backup/panel-unit" /etc/systemd/system/beeny-panel.service
  if [[ "$worker_existed" == 1 ]]; then install -m 644 "$backup/worker-unit" /etc/systemd/system/beeny-customer-worker.service; else systemctl disable beeny-customer-worker 2>/dev/null || true; rm -f /etc/systemd/system/beeny-customer-worker.service; fi
  systemctl daemon-reload
  [[ "$panel_was_active" == 0 ]] || systemctl start beeny-panel
  [[ "$worker_was_active" == 0 ]] || systemctl start beeny-customer-worker
  # Keep additive database changes and any new customer writes. Snapshot is for manual recovery.
  [[ "$result" != 0 ]] || result=1
  exit "$result"
}
trap rollback ERR INT TERM
systemctl stop beeny-customer-worker 2>/dev/null || true
systemctl stop beeny-panel
python3 - "$DEST/instance/beeny.db" "$backup/beeny.db" <<'PY'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    assert source.execute('PRAGMA quick_check').fetchone()[0]=='ok', 'Database integrity check failed'
    source.backup(target)
PY
for rel in "${FILES[@]}"; do
  install -d -m 755 "$DEST/$(dirname "$rel")"
  install -m 644 "$ROOT_DIR/$rel" "$DEST/$rel"
done
chmod 700 "$DEST/scripts/create_vpn_user.sh" "$DEST/scripts/update_panel.sh"
mv "$DEST/venv" "$backup/previous-venv"
swapped=1
ln -s "$next_venv" "$DEST/venv"
install -m 644 "$DEST/beeny-panel.service" /etc/systemd/system/beeny-panel.service
install -m 644 "$DEST/beeny-customer-worker.service" /etc/systemd/system/beeny-customer-worker.service
systemctl daemon-reload
systemctl enable --now beeny-panel
verify_deployed
systemctl enable --now beeny-customer-worker
systemctl is-active --quiet beeny-customer-worker
commit="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo local-package)"
"$DEST/venv/bin/python" - "$DEST/.release.json" "$commit" <<'PY'
import datetime,json,pathlib,sys
pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(commit=sys.argv[2],updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())))
PY
trap - ERR INT TERM
python3 "$DEST/scripts/configure_uploads.py" || echo 'Panel updated; configure Nginx upload limit 24M manually.' >&2
printf 'Panel updated successfully. Backup: %s\n' "$backup"
echo 'VPN certificates, user data, panel settings, avatars and receipts were preserved.'
echo 'Next: set customer passwords and configure Customer & payments.'
