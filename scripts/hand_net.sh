#!/usr/bin/env bash
# Put this computer's wired port on the hand's subnet (lasts until reboot) and check that the hand answers.
# The hand has a fixed address and no DHCP: right hand 192.168.1.111, left hand 192.168.1.110, mask 255.255.255.0.
#   bash scripts/hand_net.sh              # eth0, 192.168.1.50
#   bash scripts/hand_net.sh enx00e04c68  # another interface (a USB Ethernet adapter); list them with: ip -br link
set -u
IF="${1:-eth0}"; ADDR="${2:-192.168.1.50}"
ip link show "$IF" >/dev/null 2>&1 || { echo "no interface '$IF'. Available:"; ip -br link; exit 1; }
if ! ip -4 addr show dev "$IF" | grep -q "inet $ADDR/"; then sudo ip addr add "$ADDR/24" dev "$IF" || exit 1; fi
sudo ip link set "$IF" up
if ip -4 route | grep -v " dev $IF " | grep -q "^192\.168\.1\.0/24"; then
  echo "WARNING: another network here (Wi-Fi?) also uses 192.168.1.x. The hand may be unreachable: use a different Wi-Fi or a phone hotspot."
fi
ip -br addr show dev "$IF"
found=0
for h in 192.168.1.111 192.168.1.110; do
  if ping -c 2 -W 1 -I "$IF" "$h" >/dev/null 2>&1; then echo "hand answers at $h ($([ "$h" = 192.168.1.111 ] && echo right || echo left) hand)"; found=1; fi
done
[ "$found" = 1 ] || { echo "no answer from 192.168.1.111 / .110: is the hand powered and the cable in?"; exit 2; }
