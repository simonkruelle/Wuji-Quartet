#!/usr/bin/env bash
# The second hand through a USB Ethernet adapter. The RDK X5 has one Ethernet port: one hand goes in it, the other into a
# USB-Ethernet adapter in a USB-A port (the USB-C port is device-only: an adapter there gets no power).
# Gives the adapter its own address (192.168.1.12/32, so it does not compete with the Ethernet port for 192.168.1.x) and routes the
# hand that answers through it (right 192.168.1.111, left 192.168.1.110). Lasts until a reboot or a replug: then run it again.
# The Studio's Hands page runs it with one click.
#   bash scripts/hand_adapter.sh                    # the USB Ethernet adapter with a cable in it
#   bash scripts/hand_adapter.sh enxc8a36223d317    # a given one; list them with: ip -br link
set -u
ADDR=192.168.1.12
carrier() { cat "/sys/class/net/$1/carrier" 2>/dev/null; }
IF="${1:-}"
if [ -z "$IF" ]; then
  cands=$(for n in /sys/class/net/*; do i=${n##*/}; case $i in enx*|eth[1-9]*) echo "$i";; esac; done)
  [ -n "$cands" ] || { echo "no USB Ethernet adapter found: plug it into a USB-A port (not USB-C). Interfaces:"; ip -br link; exit 1; }
  for i in $cands; do [ "$(carrier "$i")" = 1 ] && { IF=$i; break; }; done
  IF=${IF:-$(echo "$cands" | head -n 1)}
fi
ip link show "$IF" >/dev/null 2>&1 || { echo "no interface '$IF'. Interfaces:"; ip -br link; exit 1; }
echo "adapter: $IF"
sudo -n true 2>/dev/null || { echo "sudo asks for a password here: run 'bash scripts/hand_adapter.sh' in a terminal on the robot computer"; exit 1; }
command -v nmcli >/dev/null && sudo -n nmcli device set "$IF" managed no 2>/dev/null   # NetworkManager would keep asking for DHCP on it
sudo -n ip link set "$IF" up
for _ in 1 2 3 4 5 6 7 8; do [ "$(carrier "$IF")" = 1 ] && break; sleep 0.5; done
[ "$(carrier "$IF")" = 1 ] || { echo "no link on $IF: is the cable from the hand in the adapter, and the hand powered?"; exit 2; }
ip -4 addr show dev "$IF" | grep -q "inet $ADDR/" || sudo -n ip addr add "$ADDR/32" dev "$IF"
found=0
for pair in "192.168.1.110 left" "192.168.1.111 right"; do
  set -- $pair
  dev=$(ip -o route get "$1" 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p')
  case $dev in "$IF"|wl*|"") ;;               # through Wi-Fi a stranger may answer for 192.168.1.x: try the adapter
    *) if ping -c 1 -W 1 "$1" >/dev/null 2>&1; then echo "$2 hand ($1) answers through $dev already"; continue; fi;; esac
  sudo -n ip route replace "$1/32" dev "$IF" src "$ADDR"
  if ping -c 2 -W 1 "$1" >/dev/null 2>&1; then echo "$2 hand ($1) answers through the adapter $IF"; found=1
  else sudo -n ip route del "$1/32" dev "$IF" 2>/dev/null; fi
done
[ "$found" = 1 ] || { echo "no hand answers through $IF: is the hand powered, the cable from the hand in the adapter?"; exit 2; }
