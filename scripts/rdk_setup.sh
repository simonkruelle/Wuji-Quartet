#!/usr/bin/env bash
# One-time setup of a fresh D-Robotics RDK X5 (RDK OS 3.x = Ubuntu 22.04, arm64) for this project.
# Run ON THE BOARD, from the repo folder, after Wi-Fi is connected:
#
#     sudo bash scripts/rdk_setup.sh
#
# What it does: installs Docker the way D-Robotics' own installer does (Ubuntu's docker.io, plus the fixes their
# kernel needs: legacy iptables, and two daemon settings when kernel modules are missing), lets your login user run
# docker, and tests it. It leaves out that installer's China-only registry mirror and DNS servers.
# It does not change the network setup of eth0 or wlan0. Safe to run again.
# Reference: https://gitea.d-robotics.cc/chao.wu/RDK_Docker_Tools (install_docker/install_docker.sh)
set -u
say()  { printf '\n== %s\n' "$*"; }
ok()   { printf '   ok: %s\n' "$*"; }
warn() { printf '   WARNING: %s\n' "$*"; }
die()  { printf '\nSTOP: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run with sudo:  sudo bash scripts/rdk_setup.sh"
USER_NAME="${SUDO_USER:-sunrise}"
DAEMON_JSON=/etc/docker/daemon.json

say "1/6 System"
PRETTY_NAME="unknown OS"; [ -r /etc/os-release ] && . /etc/os-release
echo "   $(uname -m), kernel $(uname -r), $PRETTY_NAME"
[ "$(uname -m)" = aarch64 ] || warn "this is not an ARM64 machine; the script is written for the RDK X5"
if command -v rdkos_info >/dev/null 2>&1; then rdkos_info 2>/dev/null | sed -n '1,30p' | sed 's/^/   /'; fi
free_gb="$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9')"
if [ "${free_gb:-0}" -ge 5 ]; then ok "${free_gb} GB free on /"; else warn "only ${free_gb:-?} GB free on / (the image needs about 3 GB while it builds)"; fi
if [ "$(date +%Y)" -ge 2026 ]; then ok "clock: $(date)"; else warn "the clock is wrong ($(date)). It sets itself once the board is online; downloads fail until then"; fi

say "2/6 Internet"
if timeout 8 bash -c '</dev/tcp/ports.ubuntu.com/80' 2>/dev/null; then ok "package server reachable"
else die "no internet. Connect Wi-Fi first:  sudo wifi_connect \"NETWORK NAME\" \"PASSWORD\""; fi

say "3/6 Packages (docker.io, docker-buildx, git)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || warn "apt update reported a problem (for NO_PUBKEY see docs/RDK_X5_SETUP.md); continuing"
apt-get install -y -qq docker.io git ca-certificates curl iptables rsync || die "package install failed (see the apt messages above)"
apt-get install -y -qq docker-buildx || warn "docker-buildx not available; the classic builder will be used, which is fine"
ok "$(docker --version)"

say "4/6 Docker fixes for the RDK kernel"
# (a) the kernel has no nf_tables backend that Docker can use: switch to legacy iptables, as D-Robotics does
if update-alternatives --list iptables 2>/dev/null | grep -q legacy; then
  update-alternatives --set iptables /usr/sbin/iptables-legacy >/dev/null 2>&1
  update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy >/dev/null 2>&1
  ok "iptables backend: $(iptables --version 2>/dev/null)"
else
  warn "no iptables-legacy alternative found; if Docker does not start, this is the first thing to check"
fi
# (b) daemon settings, only where a kernel module is missing
ver="$(docker version --format '{{.Client.Version}}' 2>/dev/null)"; major="${ver%%.*}"; rest="${ver#*.}"; minor="${rest%%.*}"
case "$major" in ''|*[!0-9]*) major=0 ;; esac; case "$minor" in ''|*[!0-9]*) minor=0 ;; esac
has_mod() { modprobe "$1" 2>/dev/null || grep -q "^$1 " /proc/modules 2>/dev/null; }
keys=()
if ! has_mod iptable_raw; then
  if [ "$major" -gt 28 ] || { [ "$major" -eq 28 ] && [ "$minor" -ge 2 ]; }; then keys+=('"allow-direct-routing": true'); echo "   kernel has no iptable_raw: setting allow-direct-routing"; fi
fi
if ! has_mod ip6table_raw; then keys+=('"ip6tables": false'); echo "   kernel has no ip6table_raw: setting ip6tables false"; fi
keys+=('"log-driver": "json-file"' '"log-opts": {"max-size": "10m", "max-file": "3"}')
write_daemon_json() {   # arguments: JSON "key": value pairs
  mkdir -p /etc/docker
  if [ -f "$DAEMON_JSON" ] && [ ! -f "$DAEMON_JSON.before-wuji-quartet" ]; then cp "$DAEMON_JSON" "$DAEMON_JSON.before-wuji-quartet"; fi
  { printf '{\n'; n=$#; i=0; for k in "$@"; do i=$((i + 1)); if [ "$i" -lt "$n" ]; then printf '    %s,\n' "$k"; else printf '    %s\n' "$k"; fi; done; printf '}\n'; } > "$DAEMON_JSON"
  if command -v python3 >/dev/null 2>&1; then python3 -m json.tool "$DAEMON_JSON" >/dev/null || die "$DAEMON_JSON is not valid JSON"; fi
}
write_daemon_json "${keys[@]}"; ok "wrote $DAEMON_JSON"

say "5/6 Start Docker"
start_docker() {
  if command -v systemctl >/dev/null 2>&1 && systemctl cat docker.service >/dev/null 2>&1; then
    systemctl enable docker >/dev/null 2>&1; systemctl restart docker 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do systemctl is-active --quiet docker && docker info >/dev/null 2>&1 && return 0; sleep 1; done
  fi
  return 1
}
if start_docker; then ok "docker service is running"
else
  warn "Docker did not start with the standard settings. Retrying without Docker's own firewall and bridge."
  warn "(this project only uses host networking, so nothing is lost)"
  journalctl -u docker --no-pager -n 6 2>/dev/null | sed 's/^/     /'
  write_daemon_json '"iptables": false' '"ip6tables": false' '"bridge": "none"' '"log-driver": "json-file"' '"log-opts": {"max-size": "10m", "max-file": "3"}'
  start_docker || { journalctl -u docker --no-pager -n 25 2>/dev/null; die "Docker still does not start. Send the lines above to the team. D-Robotics lists RDK OS >= 3.3.3 and MiniBoot >= Sep-03-2025 as required (update the boot firmware with: sudo rdk-miniboot-update). Fallback without Docker: docs/RDK_X5_SETUP.md, 'install without it'."; }
  ok "docker service is running (host networking only)"
fi
if id "$USER_NAME" >/dev/null 2>&1; then usermod -aG docker "$USER_NAME" && ok "user '$USER_NAME' may run docker (after logging in again)"; fi

say "6/6 Test"
if docker run --rm --network host hello-world 2>/dev/null | grep -q "Hello from Docker"; then ok "docker pulled and ran a test container"
else warn "the test container did not run. Try:  sudo docker run --rm --network host hello-world"; fi

cat <<'TXT'

Done. Next:
  exit                                  # log out, then ssh in again so the docker group applies
  cd ~/Wuji-Quartet
  ./wq build                            # about 1 GB of downloads
  ./wq check                            # should print: streamed 5100 frames, skipped ...
  bash scripts/hand_net.sh              # once the hand is cabled and powered
  ./wq hand python scripts/hand_info.py
TXT
