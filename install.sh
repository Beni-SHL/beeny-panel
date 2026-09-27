chmod 600 /etc/openvpn/ta.key
ok 'Certificates generated on this server'
phase 4 'Configure OpenVPN and routing'
cat > /etc/openvpn/server/server.conf <<CONF
port $vpn_port
proto tcp-server
dev tun
topology subnet
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist /var/log/openvpn-ipp.txt
client-config-dir /etc/openvpn/ccd
ca /etc/openvpn/ca.crt
cert /etc/openvpn/server/server.crt
key /etc/openvpn/server/server.key
dh /etc/openvpn/dh.pem
tls-auth /etc/openvpn/ta.key 0
tls-version-min 1.2
data-ciphers AES-256-GCM:AES-128-GCM
cipher AES-256-GCM
auth SHA256
remote-cert-tls client
keepalive 10 120
persist-key
persist-tun
duplicate-cn
push "redirect-gateway def1"
push "dhcp-option DNS 1.1.1.1"
push "dhcp-option DNS 1.0.0.1"
status /var/log/openvpn-status.log 10
status-version 2
management 127.0.0.1 7505
verb 3
CONF
cat > /etc/sysctl.d/99-beeny-vpn.conf <<'CONF'
net.ipv4.ip_forward=1
CONF
sysctl -p /etc/sysctl.d/99-beeny-vpn.conf
printf 'BEENY_NET_IFACE=%s\n' "$iface" > /etc/beeny-panel/vpn.env
chmod 600 /etc/beeny-panel/vpn.env
install -m 750 "$ROOT_DIR/scripts/vpn-firewall.sh" /usr/local/sbin/beeny-vpn-firewall
install -m 644 "$ROOT_DIR/beeny-vpn-firewall.service" /etc/systemd/system/beeny-vpn-firewall.service
systemctl daemon-reload
systemctl enable --now beeny-vpn-firewall
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow "$vpn_port/tcp"
  ufw route allow in on tun0 out on "$iface"
fi
systemctl enable --now openvpn-server@server
systemctl is-active --quiet openvpn-server@server || { echo 'OpenVPN failed. Check: journalctl -u openvpn-server@server -n 100' >&2; exit 1; }
ok 'OpenVPN service is running'

phase 5 'Install Beeny Panel'
mkdir -p "$DEST"
rsync -a --exclude='venv/' --exclude='instance/' --exclude='backups/' --exclude='ca/' --exclude='config.json' --exclude='*.key' --exclude='*.db*' --exclude='.git/' "$ROOT_DIR/" "$DEST/"
chmod 700 "$DEST/scripts/create_vpn_user.sh"
mkdir -p "$DEST/instance" "$DEST/backups"
chmod 700 "$DEST/instance" "$DEST/backups"
python3 -m venv "$DEST/venv"
run_quiet 'Update Python package manager' "$DEST/venv/bin/python" -m pip install --upgrade pip
run_quiet 'Install panel dependencies' "$DEST/venv/bin/python" -m pip install -r "$DEST/requirements.txt"
secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
printf 'BEENY_SECRET_KEY=%s\nBEENY_PUBLIC_HOST=%s\nBEENY_VPN_PORT=%s\nBEENY_BIND=127.0.0.1\nBEENY_PORT=%s\nBEENY_PUBLIC_HTTPS=%s\n' "$secret" "$vpn_host" "$vpn_port" "$panel_port" "${panel_domain:+1}" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
python3 - "$DEST/config.json" "$panel_path" "$panel_port" <<'PY'
import json,sys
with open(sys.argv[1], 'w') as f:
    json.dump({'panel_path': sys.argv[2], 'panel_url': f'http://127.0.0.1:{sys.argv[3]}'}, f)
PY
chmod 600 "$DEST/config.json"
export BEENY_SECRET_KEY="$secret" BEENY_PUBLIC_HOST="$vpn_host" BEENY_VPN_PORT="$vpn_port"
printf '%s\n' "$admin_pass" | "$DEST/venv/bin/python" "$DEST/scripts/init_admin.py" "$admin_user"
unset admin_pass secret BEENY_SECRET_KEY
install -m 644 "$DEST/beeny-panel.service" /etc/systemd/system/beeny-panel.service
systemctl daemon-reload
systemctl enable --now beeny-panel
systemctl is-active --quiet beeny-panel || { echo 'Panel failed. Check: journalctl -u beeny-panel -n 100' >&2; exit 1; }
ok 'Beeny Panel service is running'

phase 6 'Secure panel access'
if [[ -n "$panel_domain" ]]; then
  # Certbot standalone binds port 80; Nginx begins serving only after the certificate exists.
  systemctl stop nginx || true
  if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
    ufw allow 80/tcp
    ufw allow 443/tcp
  fi
  run_quiet 'Request HTTPS certificate' certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email -d "$panel_domain"
  cat > /etc/nginx/sites-available/beeny-panel <<CONF
server {
    listen 80;
    server_name $panel_domain;
    return 301 https://\$host\$request_uri;
}
server {
    listen 443 ssl;
    server_name $panel_domain;
    ssl_certificate /etc/letsencrypt/live/$panel_domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$panel_domain/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:$panel_port;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
CONF
  ln -s /etc/nginx/sites-available/beeny-panel /etc/nginx/sites-enabled/beeny-panel
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable --now nginx
  panel_url="https://$panel_domain$panel_path/login"
else
  panel_url="http://127.0.0.1:$panel_port$panel_path/login"
  info 'Panel listens locally; use an SSH tunnel or configure HTTPS.'
fi
printf '\n%s╭───────────────── INSTALLATION COMPLETE ─────────────────╮%s\n' "$GREEN" "$RESET"
printf '  Panel:   %s\n  OpenVPN: %s:%s/TCP\n  Logs:    %s\n' "$panel_url" "$vpn_host" "$vpn_port" "$LOG"
printf '%s╰─────────────────────────────────────────────────────────╯%s\n\n' "$GREEN" "$RESET"
