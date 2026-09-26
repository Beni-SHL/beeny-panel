#!/usr/bin/env bash
set -Eeuo pipefail
. /etc/beeny-panel/vpn.env
case "${1:-}" in
start)
  iptables -t nat -C POSTROUTING -s 10.8.0.0/24 -o "$BEENY_NET_IFACE" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o "$BEENY_NET_IFACE" -j MASQUERADE
  iptables -C FORWARD -i tun0 -o "$BEENY_NET_IFACE" -j ACCEPT 2>/dev/null || iptables -I FORWARD -i tun0 -o "$BEENY_NET_IFACE" -j ACCEPT
  iptables -C FORWARD -i "$BEENY_NET_IFACE" -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -I FORWARD -i "$BEENY_NET_IFACE" -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  ;;
stop)
  iptables -t nat -D POSTROUTING -s 10.8.0.0/24 -o "$BEENY_NET_IFACE" -j MASQUERADE 2>/dev/null || true
  iptables -D FORWARD -i tun0 -o "$BEENY_NET_IFACE" -j ACCEPT 2>/dev/null || true
  iptables -D FORWARD -i "$BEENY_NET_IFACE" -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
  ;;
*) echo 'Usage: beeny-vpn-firewall start|stop' >&2; exit 2;;
esac
