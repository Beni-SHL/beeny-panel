#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 ]] || exit 1
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install -m 644 "$ROOT_DIR/beeny-pki.service" /etc/systemd/system/beeny-pki.service
install -m 644 "$ROOT_DIR/beeny-pki.timer" /etc/systemd/system/beeny-pki.timer
systemctl daemon-reload
systemctl enable --now beeny-pki.timer
echo 'Daily expiration audit and CRL refresh enabled. VPN was not restarted.'
