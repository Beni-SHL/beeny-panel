#!/bin/bash

set -euo pipefail
USER_NAME="${1:-}"
[[ "$USER_NAME" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || { echo 'Invalid username' >&2; exit 2; }
[[ "${BEENY_PUBLIC_HOST:-}" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo 'BEENY_PUBLIC_HOST is missing or invalid' >&2; exit 2; }
[[ "${BEENY_VPN_PORT:-}" =~ ^[0-9]{1,5}$ ]] && (( BEENY_VPN_PORT >= 1 && BEENY_VPN_PORT <= 65535 )) || { echo 'BEENY_VPN_PORT is missing or invalid' >&2; exit 2; }
mkdir -p /etc/openvpn/clients
umask 077
export EASYRSA_BATCH=1

cd /etc/openvpn/easy-rsa || exit 1

./easyrsa build-client-full "$USER_NAME" nopass

cat > /etc/openvpn/clients/${USER_NAME}.ovpn <<EOF
client
dev tun
proto tcp
remote ${BEENY_PUBLIC_HOST} ${BEENY_VPN_PORT}

resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server

cipher AES-256-GCM
auth SHA256

key-direction 1

verb 3

<ca>
$(cat /etc/openvpn/easy-rsa/pki/ca.crt)
</ca>

<cert>
$(sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p' \
/etc/openvpn/easy-rsa/pki/issued/${USER_NAME}.crt)
</cert>

<key>
$(cat /etc/openvpn/easy-rsa/pki/private/${USER_NAME}.key)
</key>

<tls-auth>
$(cat /etc/openvpn/easy-rsa/ta.key)
</tls-auth>
EOF

echo "/etc/openvpn/clients/${USER_NAME}.ovpn"
