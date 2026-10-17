#!/usr/bin/env bash
set -Eeuo pipefail
. /etc/beeny-panel/vpn.env
vpn_tun="${BEENY_TUN_INTERFACE:-tun0}"
vpn_subnet="${BEENY_VPN_SUBNET:-10.8.0.0/24}"
[[ "$vpn_tun" =~ ^[A-Za-z0-9_.-]{1,15}$ && "$BEENY_NET_IFACE" =~ ^[A-Za-z0-9_.-]{1,15}$ ]] || exit 2
python3 -c 'import ipaddress,sys; assert ipaddress.ip_network(sys.argv[1],strict=True).version==4' "$vpn_subnet"
case "${1:-}" in
start)
  iptables -t nat -C POSTROUTING -s "$vpn_subnet" -o "$BEENY_NET_IFACE" -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s "$vpn_subnet" -o "$BEENY_NET_IFACE" -j MASQUERADE
  iptables -C FORWARD -i "$vpn_tun" -o "$BEENY_NET_IFACE" -j ACCEPT 2>/dev/null || iptables -I FORWARD -i "$vpn_tun" -o "$BEENY_NET_IFACE" -j ACCEPT
  iptables -C FORWARD -i "$BEENY_NET_IFACE" -o "$vpn_tun" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || iptables -I FORWARD -i "$BEENY_NET_IFACE" -o "$vpn_tun" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  ;;
stop)
  iptables -t nat -D POSTROUTING -s "$vpn_subnet" -o "$BEENY_NET_IFACE" -j MASQUERADE 2>/dev/null || true
  iptables -D FORWARD -i "$vpn_tun" -o "$BEENY_NET_IFACE" -j ACCEPT 2>/dev/null || true
  iptables -D FORWARD -i "$BEENY_NET_IFACE" -o "$vpn_tun" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
  ;;
*) echo 'Usage: beeny-vpn-firewall start|stop' >&2; exit 2;;
esac
