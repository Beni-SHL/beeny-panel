#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST=/opt/beeny-panel
ENV_FILE=/etc/beeny-panel/panel.env
LOG=/var/log/beeny-panel-install.log

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  CYAN=$'\033[38;5;51m'; PURPLE=$'\033[38;5;141m'; GREEN=$'\033[38;5;84m'
  YELLOW=$'\033[38;5;221m'; RED=$'\033[38;5;203m'; MUTED=$'\033[38;5;245m'
  BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  CYAN=''; PURPLE=''; GREEN=''; YELLOW=''; RED=''; MUTED=''; BOLD=''; RESET=''
fi

banner() {
  printf '\n%s╭──────────────────────────────────────────────────╮%s\n' "$PURPLE" "$RESET"
  printf '%s│%s  %s◆ BEENY PANEL%s     OpenVPN + Control Panel         %s│%s\n' "$PURPLE" "$RESET" "$BOLD$CYAN" "$RESET" "$PURPLE" "$RESET"
  printf '%s╰──────────────────────────────────────────────────╯%s\n\n' "$PURPLE" "$RESET"
}
phase() { printf '\n%s[%s/6]%s %s%s%s\n%s────────────────────────────────────────────────────%s\n' "$CYAN" "$1" "$RESET" "$BOLD" "$2" "$RESET" "$MUTED" "$RESET"; }
ok() { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
info() { printf '  %s•%s %s\n' "$CYAN" "$RESET" "$1"; }
fail() { printf '\n  %s✗%s %s\n' "$RED" "$RESET" "$1" >&2; }
ask() { local var=$1 label=$2; printf '%s  › %s%s ' "$CYAN" "$label" "$RESET"; IFS= read -r "$var"; }

spinner() {
  local pid=$1 label=$2 frames='|/-\\' n=0
  if [[ -t 1 ]]; then
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r  %s%s%s %s' "$PURPLE" "${frames:n++%4:1}" "$RESET" "$label"
      sleep .12
    done
    printf '\r\033[2K'
  fi
}

run_quiet() {
  local label=$1; shift
  "$@" >> "$LOG" 2>&1 &
  local pid=$!
  spinner "$pid" "$label"
  if wait "$pid"; then ok "$label"; else
    fail "$label failed. See $LOG"
    tail -n 12 "$LOG" >&2
    exit 1
  fi
}

generate_pki() {
  cd /etc/openvpn/easy-rsa
  export EASYRSA_BATCH=1 EASYRSA_REQ_CN='Beeny-VPN-CA' EASYRSA_PKI=/etc/openvpn/easy-rsa/pki
  ./easyrsa init-pki && ./easyrsa build-ca nopass &&
    ./easyrsa build-server-full server nopass && ./easyrsa gen-dh
}

demo() {
  banner
  phase 1 'Server preflight'; ok 'Ubuntu 24.04 / clean server'; info 'VPN address, ports, panel path and admin login'
  phase 2 'Install system packages'; ok 'OpenVPN, Easy-RSA and Python'
  phase 3 'Create VPN certificates'; ok 'New CA and server certificates'
  phase 4 'Configure the VPN'; ok 'Routing, firewall and OpenVPN service'
  phase 5 'Install Beeny Panel'; ok 'Database, admin account and panel service'
  phase 6 'Secure panel access'; ok 'HTTPS domain or local-only access'
  printf '\n%s✔ Installation complete%s\n\n' "$GREEN$BOLD" "$RESET"
  info 'Preview only: no changes were made.'
}

check_source() {
  local needed
  for needed in app.py cluster.py renewal.py serve.py requirements.txt beeny-panel.service beeny-vpn-firewall.service templates/login.html templates/user_form.html templates/dashboard.html static/css/style.css scripts/create_vpn_user.sh scripts/vpn-firewall.sh scripts/init_admin.py; do
    [[ -f "$ROOT_DIR/$needed" ]] || { echo "Missing: $needed" >&2; exit 1; }
  done
  python3 - "$ROOT_DIR" <<'PY'
import ast, pathlib, sys
root=pathlib.Path(sys.argv[1])
for p in [root/'app.py',root/'cluster.py',root/'renewal.py',root/'serve.py',root/'scripts/init_admin.py']:
    ast.parse(p.read_text())
PY
}
check_source
if [[ "${1:-}" == '--check' ]]; then ok 'Source validation passed'; exit 0; fi
if [[ "${1:-}" == '--demo' ]]; then demo; exit 0; fi
[[ $# == 0 ]] || { echo 'Usage: sudo bash install.sh [--check|--demo]' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run as root: sudo bash install.sh' >&2; exit 1; }
banner
phase 1 'Server preflight and settings'
. /etc/os-release
[[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) ]] || { echo 'Supported: Ubuntu 22.04/24.04' >&2; exit 1; }
[[ ! -e "$DEST" && ! -e "$ENV_FILE" && ! -e /etc/openvpn/server/server.conf && ! -e /etc/openvpn/easy-rsa/pki/ca.key ]] || {
  echo 'An existing panel/OpenVPN installation was detected. This installer is for a clean VPS only; nothing was overwritten.' >&2; exit 1;
}
[[ -t 0 ]] || { echo 'Run interactively to enter credentials.' >&2; exit 1; }
ask vpn_host 'Public VPS IP or VPN domain:'
[[ "$vpn_host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo 'Invalid host' >&2; exit 1; }
ask vpn_port 'VPN TCP port [110]:'; vpn_port="${vpn_port:-110}"
[[ "$vpn_port" =~ ^[0-9]{1,5}$ ]] && (( vpn_port >= 1 && vpn_port <= 65535 )) || { echo 'Invalid VPN port' >&2; exit 1; }
ask panel_port 'Panel local port [8080]:'; panel_port="${panel_port:-8080}"
[[ "$panel_port" =~ ^[0-9]{4,5}$ ]] && (( panel_port >= 1024 && panel_port <= 65535 && panel_port != vpn_port )) || { echo 'Invalid panel port' >&2; exit 1; }
ask panel_path 'Panel path/passcode (example /my-panel) [/panel]:'
panel_path="${panel_path:-/panel}"
[[ "$panel_path" =~ ^/[A-Za-z0-9_-]{3,48}$ ]] || { echo 'Invalid panel path' >&2; exit 1; }
ask admin_user 'Admin username:'
[[ "$admin_user" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || { echo 'Invalid username' >&2; exit 1; }
printf '%s  › Admin password (12+ characters): %s' "$CYAN" "$RESET"
IFS= read -rs admin_pass; echo
[[ ${#admin_pass} -ge 12 ]] || { echo 'Password too short' >&2; exit 1; }
ask panel_domain 'Panel domain for HTTPS (empty = local only):'
if [[ -n "$panel_domain" ]]; then
  [[ "$panel_domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}$ ]] || { echo 'Invalid domain' >&2; exit 1; }
  [[ ! -e /etc/nginx/sites-enabled/default && ! -e /etc/nginx/sites-enabled/beeny-panel ]] || {
    echo 'An nginx site already exists; set up HTTPS manually or start from a clean VPS.' >&2; exit 1;
  }
fi
iface="$(ip -4 route show default | awk '/default/ {print $5; exit}')"
[[ "$iface" =~ ^[a-zA-Z0-9_.:-]+$ ]] || { echo 'Cannot identify outbound network interface' >&2; exit 1; }
if [[ -n "$panel_domain" ]]; then
  resolved="$(getent ahostsv4 "$panel_domain" | awk 'NR==1{print $1}')"
  [[ -n "$resolved" ]] || { echo 'Panel domain must resolve in public DNS before installation.' >&2; exit 1; }
fi

ok 'All settings validated'
install -m 600 /dev/null "$LOG"
phase 2 'Install system packages'
run_quiet 'Refresh Ubuntu package lists' apt-get update
run_quiet 'Install OpenVPN, Easy-RSA and Python' env DEBIAN_FRONTEND=noninteractive apt-get install -y openvpn easy-rsa python3 python3-venv python3-pip rsync netcat-openbsd iptables ca-certificates
if [[ -n "$panel_domain" ]]; then
  run_quiet 'Install Nginx and Certbot' env DEBIAN_FRONTEND=noninteractive apt-get install -y nginx certbot
fi

# A fresh CA is created on this VPS; never reuse or publish the archived private keys.
phase 3 'Create new VPN certificates'
install -d -m 700 /etc/openvpn/easy-rsa /etc/openvpn/clients /etc/beeny-panel
install -d -m 755 /etc/openvpn/server /etc/openvpn/ccd
cp -a /usr/share/easy-rsa/. /etc/openvpn/easy-rsa/
run_quiet 'Generate CA, server certificate and DH parameters' generate_pki
install -m 644 /etc/openvpn/easy-rsa/pki/ca.crt /etc/openvpn/ca.crt
install -m 644 /etc/openvpn/easy-rsa/pki/issued/server.crt /etc/openvpn/server/server.crt
install -m 600 /etc/openvpn/easy-rsa/pki/private/server.key /etc/openvpn/server/server.key
install -m 644 /etc/openvpn/easy-rsa/pki/dh.pem /etc/openvpn/dh.pem
openvpn --genkey tls-auth /etc/openvpn/ta.key
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
