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
  python3 - "$checkout/VERSION" "$DEST/VERSION" <<'PYVERSION'
import pathlib,sys,re
new=pathlib.Path(sys.argv[1]).read_text().strip();installed=pathlib.Path(sys.argv[2]);old=installed.read_text().strip() if installed.is_file() else '0.0.0'
if not re.fullmatch(r'\d+\.\d+\.\d+',new) or not re.fullmatch(r'\d+\.\d+\.\d+',old):raise SystemExit('Unrecognized release version; use a verified local update.')
if tuple(map(int,new.split('.')))<tuple(map(int,old.split('.'))):raise SystemExit('GitHub version is older than the installed release. Update refused.')
PYVERSION
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
if [[ "$MODE" == '' ]]; then
  exec 9>/run/lock/beeny-panel-update.lock
  flock -n 9 || { echo 'Another panel update is running.' >&2; exit 1; }
fi
FILES=(notification_locale.py theme_settings.py panel_update.py asset_delivery.py dns_services.py tunnel_engines.py integration-sources.json scripts/install_integrations.py scripts/build_script_pins.py RELEASE.json SOURCE-SHA256.json beeny-vpn-recovery.service vpn_runtime.py transport_settings.py tunnel_manager.py tunnel_settings.py scripts/install_tunnel.py scripts/manage_admin.py maintenance.py scripts/beenyctl.py scripts/bootstrap.sh scripts/install_cli.sh scripts/collect_vpn_diagnostics.py connection_guard.py session_identity.py warp_manager.py iran_network.py removal_guard.py network_settings.py network_policy.py beeny-network-policy.service representative_removal.py admin_i18n.py https_maintenance.py monitoring.py host_metrics.py crl_sync.py scripts/preflight_364.py style-bundles.json scripts/build_style_bundles.py scripts/enable_pki_audit.sh admission.py scripts/vpn_admission.py scripts/export_admission.py sales_engine.py financial_reporting.py session_limits.py terminal_traffic.py node_snapshots.py scripts/vpn_maintenance.py scripts/vpn_disconnect.py scripts/configure_vpn_core.py scripts/migrate_sales.py beeny-pki.service beeny-pki.timer sales_reporting.py representative_catalog.py representative_actions.py representative_credit.py balepay_bridge.py commissions.py scripts/update_node_speed.sh bandwidth.py speed_policy.py portal_i18n.py portal_content.py resellers.py scripts/repair_local_access.py node_agent/bridge.py node_agent/host_traffic.py scripts/reset_admin_access.py scripts/close_legacy_node_api.sh scripts/install_node_bridge.sh scripts/secure_node_api.sh scripts/cleanup_storage.py beeny-cleanup.service beeny-cleanup.timer bulk.py host_traffic.py devices.py scripts/harden_services.sh scripts/enable_backups.sh scripts/decrypt_backup.py beeny-privileged.service commerce.py beeny-backup.service beeny-backup.timer scripts/scheduled_backup.py health.py support.py security.py backup_engine.py privileged.py privileged_server.py app.py cluster.py renewal.py traffic_ledger.py serve.py admin_sessions.py pricing.py experience.py customer_features.py customer_worker.py vpn_sessions.py migrations.py VERSION requirements.txt beeny-panel.service beeny-customer-worker.service scripts/create_vpn_user.sh scripts/check_users.py scripts/init_admin.py scripts/manage_user_config.py scripts/update_panel.sh scripts/upgrade_legacy.py scripts/configure_uploads.py)
# Documentation is copied when published, but must not block application updates.
OPTIONAL_DOCS=(README.md SECURITY-REVIEW-3.7.1.md)
for rel in "${OPTIONAL_DOCS[@]}"; do
  if [[ -f "$ROOT_DIR/$rel" ]]; then FILES+=("$rel"); fi
done
while IFS= read -r -d '' path; do FILES+=("${path#"$ROOT_DIR/"}"); done < <(find "$ROOT_DIR/templates" "$ROOT_DIR/static" -type f ! -name '*.pyc' -print0)
RETIRED=(static/index-CmGPzBYL.js static/js/index-CmGPzBYL.js)
for rel in "${FILES[@]}"; do [[ -f "$ROOT_DIR/$rel" ]] || { echo "Missing update source: $rel" >&2; exit 1; }; done
[[ -f "$DEST/app.py" && -f "$DEST/config.json" && -f /etc/beeny-panel/panel.env && -f "$DEST/instance/beeny.db" && -d "$DEST/instance" && -x "$DEST/venv/bin/python" ]] || { echo 'Compatible installed panel not found at /opt/beeny-panel.' >&2; exit 1; }
python3 - "$ROOT_DIR" "$DEST/config.json" <<'PY'
import ast, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
for name in ('app.py','sales_engine.py','financial_reporting.py','session_limits.py','terminal_traffic.py','node_snapshots.py','sales_reporting.py','representative_catalog.py','representative_actions.py','representative_credit.py','balepay_bridge.py','commissions.py','resellers.py','support.py','commerce.py','admin_sessions.py','pricing.py','experience.py','customer_features.py','customer_worker.py','migrations.py','serve.py'):
    ast.parse((root/name).read_text())
config = json.loads(pathlib.Path(sys.argv[2]).read_text())
assert 'panel_path' in config, 'Existing configuration is incompatible'
PY
bash -n "$ROOT_DIR/scripts/create_vpn_user.sh"
verify_deployed() {
  systemctl is-active --quiet beeny-panel || return 1
  "$DEST/venv/bin/python" - "$DEST" <<'PY'
import json, pathlib, sqlite3, sys, time, urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

class LoginFormParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.forms=[]; self.current=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=="form":
            self.current=dict(method=attrs.get("method","get").lower(), action=attrs.get("action",""), inputs={})
            self.forms.append(self.current)
        elif tag=="input" and self.current is not None and attrs.get("name"):
            self.current["inputs"][attrs["name"]]=attrs
    def handle_endtag(self, tag):
        if tag=="form": self.current=None

def login_form_healthy(html, url):
    parser=LoginFormParser(); parser.feed(html)
    for form in parser.forms:
        fields=form["inputs"]
        if form["method"]!="post" or urljoin(url,form["action"])!=url: continue
        if not {"username","password","csrf"}.issubset(fields): continue
        if fields["password"].get("type","").lower()!="password": continue
        if fields["csrf"].get("type","").lower()!="hidden" or not fields["csrf"].get("value"): continue
        if any("disabled" in fields[n] for n in ("username","password","csrf")): continue
        return True
    return False

root=pathlib.Path(sys.argv[1]); cfg=json.loads((root/'config.json').read_text())
env=dict(line.split('=',1) for line in pathlib.Path('/etc/beeny-panel/panel.env').read_text().splitlines() if '=' in line)
url=f"http://127.0.0.1:{env['BEENY_PORT']}{cfg['panel_path'].rstrip('/')}/login"
for attempt in range(10):
    try:
        with urllib.request.urlopen(url,timeout=2) as response:
            html=response.read().decode()
        assert response.status==200 and response.geturl()==url, 'Login health check: unexpected HTTP status or redirect'
        assert login_form_healthy(html,url), 'Login health check: valid same-endpoint POST form, username, password or CSRF token missing'
        break
    except Exception:
        if attempt==9: raise
        time.sleep(1)
with sqlite3.connect(f'file:{root/"instance/beeny.db"}?mode=ro',uri=True) as db:
    assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'customer_profiles','renewal_requests','telegram_accounts','customer_settings','account_notifications','admin_notification_reads','panel_login_sessions','commission_policies','commission_sales','commission_earnings','commission_settlements','balepay_orders','balepay_gateway_config','receipt_grants','representative_credit_accounts','representative_credit_entries','representative_credit_margins','representative_credit_statements','representative_delivery_credentials','representative_sale_cancellations','representative_custom_tariffs'}.issubset(tables)
    assert 'offset_used' in {c[1] for c in db.execute('PRAGMA table_info(commission_earnings)')}
    assert 'encrypted_payment_settings' in {c[1] for c in db.execute('PRAGMA table_info(balepay_gateway_config)')}
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
if ! command -v ffprobe >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
backup="$DEST/backups/update-$stamp"
next_venv="$DEST/.venv-releases/$stamp"
install -d -m 700 "$backup"
install -d -m 755 "$DEST/.venv-releases"
# The root update worker uses UMask=0077. Dependencies are public code and must
# be traversable/readable by the unprivileged beeny services. Keep this umask
# scoped to the new virtualenv; backups and environment secrets stay private.
(
  umask 022
  python3 -m venv "$next_venv"
  "$next_venv/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
)
"$next_venv/bin/python" - "$ROOT_DIR" <<'PY'
import pathlib, sys
from jinja2 import Environment, FileSystemLoader
root=pathlib.Path(sys.argv[1]); env=Environment(loader=FileSystemLoader(root/'templates'))
for file in (root/'templates').rglob('*.html'):
    env.parse(file.read_text())
print('Templates parsed successfully.')
PY
echo 'Checking staged Python as the beeny service user.'
runuser -u beeny -- "$next_venv/bin/python" -c 'import flask, flask_sqlalchemy, flask_login, psutil, requests, waitress, PIL, cryptography; print("Service-user Python preflight passed.")'
for rel in "${FILES[@]}" "${RETIRED[@]}"; do
  if [[ -f "$DEST/$rel" ]]; then
    install -d -m 700 "$backup/code/$(dirname "$rel")"
    cp -p "$DEST/$rel" "$backup/code/$rel"
  else
    printf '%s\n' "$rel" >> "$backup/new-files"
  fi
done
cp -p "$DEST/config.json" "$backup/config.json"
helper_existed=0
if [[ -f /etc/systemd/system/beeny-privileged.service ]]; then helper_existed=1; cp -p /etc/systemd/system/beeny-privileged.service "$backup/helper-unit"; fi
cp -p /etc/beeny-panel/panel.env "$backup/panel.env"
cp -p "$DEST/.release.json" "$backup/release.json" 2>/dev/null || true
cp -p /etc/systemd/system/beeny-panel.service "$backup/panel-unit"
worker_existed=0
if [[ -f /etc/systemd/system/beeny-customer-worker.service ]]; then worker_existed=1; cp -p /etc/systemd/system/beeny-customer-worker.service "$backup/worker-unit"; fi
recovery_unit_existed=0
if [[ -f /etc/systemd/system/beeny-vpn-recovery.service ]]; then recovery_unit_existed=1; cp -p /etc/systemd/system/beeny-vpn-recovery.service "$backup/recovery-unit"; fi
network_unit_existed=0
if [[ -f /etc/systemd/system/beeny-network-policy.service ]]; then network_unit_existed=1; cp -p /etc/systemd/system/beeny-network-policy.service "$backup/network-unit"; fi
panel_was_active=0; worker_was_active=0
systemctl is-active --quiet beeny-panel && panel_was_active=1
systemctl is-active --quiet beeny-customer-worker && worker_was_active=1
cli_existed=0
if [[ -e /usr/local/bin/beeny || -L /usr/local/bin/beeny ]]; then cli_existed=1; cp -a /usr/local/bin/beeny "$backup/cli"; fi
swapped=0
stage='stopping application services'
rollback() {
  result=$?
  trap - ERR INT TERM
  echo "Update failed during $stage (exit $result); restoring application. Backup: $backup" >&2
  systemctl stop beeny-panel beeny-customer-worker beeny-privileged 2>/dev/null || true
  if [[ "$swapped" == 1 ]]; then rm -f "$DEST/venv"; mv "$backup/previous-venv" "$DEST/venv"; fi
  for rel in "${FILES[@]}" "${RETIRED[@]}"; do
    if [[ -f "$backup/code/$rel" ]]; then cp -p "$backup/code/$rel" "$DEST/$rel"; else rm -f "$DEST/$rel"; fi
  done
  if [[ -f "$backup/release.json" ]]; then cp -p "$backup/release.json" "$DEST/.release.json"; else rm -f "$DEST/.release.json"; fi
  cp -p "$backup/panel.env" /etc/beeny-panel/panel.env
  if [[ "$helper_existed" == 1 ]]; then install -m 644 "$backup/helper-unit" /etc/systemd/system/beeny-privileged.service; else systemctl disable beeny-privileged 2>/dev/null || true; rm -f /etc/systemd/system/beeny-privileged.service; fi
  install -m 644 "$backup/panel-unit" /etc/systemd/system/beeny-panel.service
  if [[ "$worker_existed" == 1 ]]; then install -m 644 "$backup/worker-unit" /etc/systemd/system/beeny-customer-worker.service; else systemctl disable beeny-customer-worker 2>/dev/null || true; rm -f /etc/systemd/system/beeny-customer-worker.service; fi
  if [[ "$recovery_unit_existed" == 1 ]]; then install -m 644 "$backup/recovery-unit" /etc/systemd/system/beeny-vpn-recovery.service; else systemctl disable beeny-vpn-recovery.service 2>/dev/null || true; rm -f /etc/systemd/system/beeny-vpn-recovery.service; fi
  if [[ "$network_unit_existed" == 1 ]]; then install -m 644 "$backup/network-unit" /etc/systemd/system/beeny-network-policy.service; else systemctl disable beeny-network-policy.service 2>/dev/null || true; rm -f /etc/systemd/system/beeny-network-policy.service; fi
  rm -f /usr/local/bin/beeny
  if [[ "$cli_existed" == 1 ]]; then cp -a "$backup/cli" /usr/local/bin/beeny; fi
  systemctl daemon-reload
  [[ "$helper_existed" == 0 ]] || systemctl start beeny-privileged
  [[ "$panel_was_active" == 0 ]] || systemctl start beeny-panel
  [[ "$worker_was_active" == 0 ]] || systemctl start beeny-customer-worker
  # Keep additive database changes and any new customer writes. Snapshot is for manual recovery.
  [[ "$result" != 0 ]] || result=1
  exit "$result"
}
trap rollback ERR INT TERM
for rel in "${RETIRED[@]}"; do rm -f -- "$DEST/$rel"; done
systemctl stop beeny-customer-worker 2>/dev/null || true
systemctl stop beeny-panel
stage='database snapshot'
python3 - "$DEST/instance/beeny.db" "$backup/beeny.db" <<'PY'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    assert source.execute('PRAGMA quick_check').fetchone()[0]=='ok', 'Database integrity check failed'
    source.backup(target)
PY
stage='installing application source'
for rel in "${FILES[@]}"; do
  install -d -m 755 "$DEST/$(dirname "$rel")"
  install -m 644 "$ROOT_DIR/$rel" "$DEST/$rel"
done
chmod 700 "$DEST/scripts/create_vpn_user.sh" "$DEST/scripts/update_panel.sh"
mv "$DEST/venv" "$backup/previous-venv"
swapped=1
ln -s "$next_venv" "$DEST/venv"
stage='configuring service permissions'
bash "$DEST/scripts/harden_services.sh"
bash "$DEST/scripts/install_cli.sh"
install -m 644 "$DEST/beeny-panel.service" /etc/systemd/system/beeny-panel.service
install -m 644 "$DEST/beeny-customer-worker.service" /etc/systemd/system/beeny-customer-worker.service
install -m 644 "$DEST/beeny-network-policy.service" /etc/systemd/system/beeny-network-policy.service
systemctl daemon-reload
systemctl enable beeny-network-policy.service
stage='database migrations'
systemd-run --quiet --wait --pipe --property=User=beeny --property=EnvironmentFile=/etc/beeny-panel/panel.env "$DEST/venv/bin/python" "$DEST/scripts/migrate_sales.py"
stage='panel startup and health check'
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
python3 "$DEST/scripts/configure_uploads.py" || echo 'Panel updated; configure Nginx upload limit 224M manually.' >&2
printf 'Panel updated successfully. Backup: %s\n' "$backup"
echo 'VPN certificates, user data, panel settings, avatars and receipts were preserved.'
echo 'Next: set customer passwords and configure Customer & payments.'
