#!/usr/bin/env bash
# Run after install_node_bridge.sh on the remote node.
set -Eeuo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.'; exit 1; }
read -rp 'Node API domain (A record pointing to this VPS): ' node_domain
[[ "$node_domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$ && ${#node_domain} -le 253 ]] || { echo 'Invalid domain.'; exit 1; }
read -rp 'Email for certificate renewal: ' email
[[ "$email" =~ ^[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || exit 1
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx certbot python3-certbot-nginx
site=/etc/nginx/sites-available/beeny-node-bridge
if [[ -e "$site" ]]; then cp -p "$site" "$site.backup-$(date +%s)"; fi
cat > "$site" <<CONF
server {
 listen 80;
 server_name $node_domain;
 client_max_body_size 4M;
 location / { proxy_pass http://127.0.0.1:6201; proxy_set_header Host \$host; proxy_read_timeout 30s; }
}
CONF
ln -sfn "$site" /etc/nginx/sites-enabled/beeny-node-bridge
nginx -t
systemctl reload nginx
certbot --nginx -d "$node_domain" --email "$email" --agree-tos --non-interactive --redirect
nginx -t
systemctl reload nginx
printf 'In the MAIN panel, edit this node and set its API/host address to: https://%s\n' "$node_domain"
printf 'Verify Node health and a suspend/resume operation before closing the old public API port.\n'
printf 'The VPN port and existing client certificates are unchanged.\n'
