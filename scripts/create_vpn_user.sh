#!/bin/bash

set -euo pipefail
USER_NAME="${1:-}"
[[ "$USER_NAME" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || { echo 'Invalid username' >&2; exit 2; }
[[ "${BEENY_PUBLIC_HOST:-}" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || { echo 'BEENY_PUBLIC_HOST is missing or invalid' >&2; exit 2; }
[[ "${BEENY_VPN_PORT:-}" =~ ^[0-9]{1,5}$ ]] && (( BEENY_VPN_PORT >= 1 && BEENY_VPN_PORT <= 65535 )) || { echo 'BEENY_VPN_PORT is missing or invalid' >&2; exit 2; }
[[ -r /etc/openvpn/ta.key ]] || { echo 'VPN tls-auth key is missing: /etc/openvpn/ta.key' >&2; exit 1; }
mkdir -p /etc/openvpn/clients
umask 077
export EASYRSA_BATCH=1

cd /etc/openvpn/easy-rsa || exit 1

pki=/etc/openvpn/easy-rsa/pki
cert="$pki/issued/$USER_NAME.crt"
key="$pki/private/$USER_NAME.key"
request_file="$pki/reqs/$USER_NAME.req"
if [[ -f "$cert" ]]; then
    # A previous panel version issued certificates but wrote an incomplete
    # profile. Reuse only the matching, signed certificate and private key.
    [[ -r "$key" ]] || { echo 'Issued certificate exists but its private key is missing.' >&2; exit 1; }
    openssl verify -CAfile "$pki/ca.crt" "$cert" >/dev/null || {
        echo 'Existing client certificate failed CA verification.' >&2; exit 1;
    }
    subject="$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253)"
    [[ "$subject" == "subject=CN=$USER_NAME" ]] || {
        echo 'Existing certificate belongs to a different username.' >&2; exit 1;
    }
    cert_pub="$(openssl x509 -in "$cert" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum)"
    key_pub="$(openssl pkey -in "$key" -pubout -outform DER | sha256sum)"
    [[ "${cert_pub%% *}" == "${key_pub%% *}" ]] || {
        echo 'Existing certificate and private key do not match.' >&2; exit 1;
    }
elif [[ -e "$key" || -e "$request_file" ]]; then
    echo 'Incomplete client PKI files already exist; refusing to overwrite them.' >&2
    exit 1
else
    ./easyrsa build-client-full "$USER_NAME" nopass
fi

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
$(cat /etc/openvpn/ta.key)
</tls-auth>
EOF

echo "/etc/openvpn/clients/${USER_NAME}.ovpn"
