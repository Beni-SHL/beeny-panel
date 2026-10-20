#!/usr/bin/env bash
# Run on a REMOTE NODE. Existing agent, keys and VPN configuration remain in place.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root on the remote VPN node.'; exit 1; }
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
read -rp 'Existing agent port [6200]: ' legacy_port; legacy_port=${legacy_port:-6200}
[[ "$legacy_port" =~ ^[0-9]{1,5}$ ]] && ((legacy_port>=1&&legacy_port<=65535&&legacy_port!=6201)) || { echo 'Invalid agent port.'; exit 1; }
read -rp 'OpenVPN management port [7505]: ' management_port; management_port=${management_port:-7505}
[[ "$management_port" =~ ^[0-9]{1,5}$ ]] && ((management_port>=1&&management_port<=65535)) || exit 1
read -rsp 'Existing node API key (same key in main panel): ' agent_key; printf '\n'
[[ "$agent_key" =~ ^[A-Za-z0-9_=-]{16,255}$ ]] || { echo 'Invalid key. Copy the existing node key from its settings.'; exit 1; }
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv iproute2 nftables curl
DEST=/opt/beeny-node-bridge
install -d -m 755 "$DEST"
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/python" -m pip install 'Flask>=3.1,<4' 'requests>=2.32,<3' 'psutil>=7,<8' 'waitress>=3,<4' 'cryptography>=46,<49'
install -m 644 "$ROOT_DIR/node_agent/bridge.py" "$DEST/bridge.py"
install -m 644 "$ROOT_DIR/vpn_runtime.py" "$DEST/vpn_runtime.py"
install -m 644 "$ROOT_DIR/tunnel_manager.py" "$DEST/tunnel_manager.py"
install -m 644 "$ROOT_DIR/tunnel_engines.py" "$DEST/tunnel_engines.py"
install -m 644 "$ROOT_DIR/integration-sources.json" "$DEST/integration-sources.json"
install -m 644 "$ROOT_DIR/network_policy.py" "$DEST/network_policy.py"
install -m 644 "$ROOT_DIR/warp_manager.py" "$DEST/warp_manager.py"
install -m 644 "$ROOT_DIR/host_metrics.py" "$DEST/host_metrics.py"
install -m 644 "$ROOT_DIR/traffic_ledger.py" "$DEST/traffic_ledger.py"
install -m 644 "$ROOT_DIR/host_traffic.py" "$DEST/host_traffic.py"
install -m 644 "$ROOT_DIR/vpn_sessions.py" "$DEST/vpn_sessions.py"
install -m 644 "$ROOT_DIR/crl_sync.py" "$DEST/crl_sync.py"
install -m 644 "$ROOT_DIR/bandwidth.py" "$DEST/bandwidth.py"
install -m 644 "$ROOT_DIR/terminal_traffic.py" "$DEST/terminal_traffic.py"
install -m 644 "$ROOT_DIR/privileged.py" "$DEST/privileged.py"
install -d -m 755 "$DEST/scripts"
for script in install_integrations.py install_tunnel.py collect_vpn_diagnostics.py vpn_disconnect.py vpn_admission.py vpn_maintenance.py configure_vpn_core.py; do install -m 755 "$ROOT_DIR/scripts/$script" "$DEST/scripts/$script"; done

install -d -m 700 /etc/beeny-node-bridge
printf 'BEENY_AGENT_KEY=%s\nBEENY_LEGACY_AGENT_PORT=%s\nBEENY_MANAGEMENT_PORT=%s\n' "$agent_key" "$legacy_port" "$management_port" > /etc/beeny-node-bridge/bridge.env
chmod 600 /etc/beeny-node-bridge/bridge.env
set -a
source /etc/beeny-node-bridge/bridge.env
set +a
"$DEST/venv/bin/python" - <<'PYCHECK'
import os,requests
session=requests.Session();session.trust_env=False
try:
    response=session.get("http://127.0.0.1:"+os.environ["BEENY_LEGACY_AGENT_PORT"]+"/api/node/stats",headers={"Authorization":"Bearer "+os.environ["BEENY_AGENT_KEY"]},timeout=10)
    if response.status_code!=200:raise ValueError("Legacy agent did not accept the configured key.")
except Exception:
    raise SystemExit("Existing agent verification failed. Check its port and API key before installing the bridge.")
PYCHECK
unset agent_key BEENY_AGENT_KEY
cat > /etc/systemd/system/beeny-node-bridge.service <<'UNIT'
[Unit]
Description=Beeny node telemetry and session control bridge
After=network.target
[Service]
User=root
WorkingDirectory=/opt/beeny-node-bridge
EnvironmentFile=/etc/beeny-node-bridge/bridge.env
ExecStart=/opt/beeny-node-bridge/venv/bin/python /opt/beeny-node-bridge/bridge.py
Restart=on-failure
NoNewPrivileges=true
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
sed 's@/opt/beeny-panel@/opt/beeny-node-bridge@g' "$ROOT_DIR/beeny-network-policy.service" > /etc/systemd/system/beeny-network-policy.service
sed 's@/opt/beeny-panel@/opt/beeny-node-bridge@g' "$ROOT_DIR/beeny-vpn-recovery.service" > /etc/systemd/system/beeny-vpn-recovery.service
systemctl daemon-reload
systemctl enable beeny-vpn-recovery.service
systemctl enable beeny-network-policy.service
systemctl enable --now beeny-node-bridge
systemctl is-active --quiet beeny-node-bridge
printf 'Bridge ready on loopback port 6201. Next run: bash %s/scripts/secure_node_api.sh\n' "$ROOT_DIR"
