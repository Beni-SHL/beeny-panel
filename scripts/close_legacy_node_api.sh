#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root on the remote node.'; exit 1; }
ENV_FILE=/etc/beeny-node-bridge/bridge.env
[[ -f "$ENV_FILE" ]] || { echo 'Install the node bridge first.'; exit 1; }
legacy_port=$(sed -n 's/^BEENY_LEGACY_AGENT_PORT=//p' "$ENV_FILE")
[[ "$legacy_port" =~ ^[0-9]{1,5}$ ]] && ((legacy_port>1024&&legacy_port<=65535&&legacy_port!=6201)) || exit 1
printf 'This closes PUBLIC access to legacy API port %s. The HTTPS proxy and local agent remain available.\n' "$legacy_port"
read -rp 'Have you saved the HTTPS node address and verified it in the main panel? [y/N]: ' verified
[[ "$verified" == y || "$verified" == Y ]] || exit 1
install -d -m 700 /etc/beeny-node-bridge
cat > /etc/beeny-node-bridge/api-firewall.sh <<RULES
#!/bin/bash
set -e
iptables -C INPUT -p tcp --dport $legacy_port ! -s 127.0.0.1 -j DROP 2>/dev/null || iptables -I INPUT -p tcp --dport $legacy_port ! -s 127.0.0.1 -j DROP
if command -v ip6tables >/dev/null; then
 ip6tables -C INPUT -p tcp --dport $legacy_port ! -s ::1 -j DROP 2>/dev/null || ip6tables -I INPUT -p tcp --dport $legacy_port ! -s ::1 -j DROP
fi
RULES
chmod 700 /etc/beeny-node-bridge/api-firewall.sh
cat > /etc/systemd/system/beeny-node-api-firewall.service <<'UNIT'
[Unit]
Description=Protect legacy Beeny node API behind HTTPS
After=network-pre.target
Before=beeny-node-bridge.service
[Service]
Type=oneshot
ExecStart=/bin/bash /etc/beeny-node-bridge/api-firewall.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now beeny-node-api-firewall
printf 'Old API port is now local-only. VPN port and SSH remain unchanged.\n'
