#!/usr/bin/env bash
# Update the secured bridge, preserving node credentials; never restart OpenVPN.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.'; exit 1; }
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/beeny-node-bridge
[[ -f "$DEST/bridge.py" && -f /etc/beeny-node-bridge/bridge.env ]] || { echo 'Secured node bridge is missing. Use scripts/install_node_bridge.sh and scripts/secure_node_api.sh first.'; exit 1; }
command -v tc >/dev/null || { apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -y iproute2; }
backup="$DEST/backups/speed-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup"
for file in bridge.py vpn_runtime.py tunnel_engines.py tunnel_manager.py network_policy.py warp_manager.py host_metrics.py traffic_ledger.py crl_sync.py bandwidth.py terminal_traffic.py host_traffic.py vpn_sessions.py privileged.py; do
  [[ ! -f "$DEST/$file" ]] || cp "$DEST/$file" "$backup/$file"
done
cp /etc/beeny-node-bridge/bridge.env "$backup/bridge.env"
rollback(){ for file in "$backup"/*.py; do install -m 644 "$file" "$DEST/$(basename "$file")"; done; systemctl restart beeny-node-bridge; }
trap rollback ERR
install -m 644 "$ROOT_DIR/node_agent/bridge.py" "$DEST/bridge.py"
for file in vpn_runtime.py tunnel_engines.py tunnel_manager.py network_policy.py warp_manager.py host_metrics.py traffic_ledger.py crl_sync.py bandwidth.py terminal_traffic.py host_traffic.py vpn_sessions.py privileged.py; do install -m 644 "$ROOT_DIR/$file" "$DEST/$file"; done
install -m 644 "$ROOT_DIR/integration-sources.json" "$DEST/integration-sources.json"
install -d -m 755 "$DEST/scripts"
for script in install_integrations.py install_tunnel.py collect_vpn_diagnostics.py vpn_disconnect.py vpn_admission.py vpn_maintenance.py configure_vpn_core.py; do install -m 755 "$ROOT_DIR/scripts/$script" "$DEST/scripts/$script"; done
"$DEST/venv/bin/python" -m pip install 'cryptography>=46,<49'
"$DEST/venv/bin/python" -m compileall -q "$DEST"
sed 's@/opt/beeny-panel@/opt/beeny-node-bridge@g' "$ROOT_DIR/beeny-network-policy.service" > /etc/systemd/system/beeny-network-policy.service
sed 's@/opt/beeny-panel@/opt/beeny-node-bridge@g' "$ROOT_DIR/beeny-vpn-recovery.service" > /etc/systemd/system/beeny-vpn-recovery.service
systemctl daemon-reload
systemctl enable beeny-vpn-recovery.service
systemctl enable beeny-network-policy.service
systemctl restart beeny-node-bridge
systemctl is-active --quiet beeny-node-bridge
"$DEST/venv/bin/python" - <<'HEALTH'
from pathlib import Path
import time,requests
settings=dict(line.split('=',1) for line in Path('/etc/beeny-node-bridge/bridge.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
token=settings.get('BEENY_AGENT_KEY','').strip().strip('"').strip("'")
session=requests.Session();session.trust_env=False
for attempt in range(10):
    try:
        response=session.get('http://127.0.0.1:6201/api/node/stats',headers={'Authorization':'Bearer '+token},timeout=3)
        body=response.json()
        if response.status_code==200 and body.get('agent_version')=='3.7.6' and 'speed-policy' in body.get('capabilities',[]):break
    except (requests.RequestException,ValueError):pass
    time.sleep(.3)
else:raise SystemExit('Updated node API health verification failed; restoring previous bridge.')
HEALTH
trap - ERR
printf 'Node bridge 3.7.6 updated. VPN was not restarted. Backup: %s\n' "$backup"
