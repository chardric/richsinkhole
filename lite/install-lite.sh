#!/usr/bin/env bash
# RichSinkhole Lite — native installer for ARMv6 (Raspberry Pi Zero v1.3).
#
# What it does, in order:
#   1. Sanity-check (root, network, ports).
#   2. apt installs (dnsmasq, python3-venv, log2ram, logrotate).
#   3. Creates the rs-lite system user + state/log directories.
#   4. Installs source tree to /opt/rs-lite, builds a venv, installs requirements.
#   5. Drops dnsmasq.d, systemd, logrotate, polkit configs.
#   6. Points /etc/resolv.conf at 127.0.0.1.
#   7. Enables + starts services. Runs first updater pass synchronously.
#   8. Prints the dashboard URL and a generated first-run setup hint.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="/opt/rs-lite"
STATE_DIR="/var/lib/rs-lite"
LOG_DIR="/var/log/rs-lite"
CONFIG_DIR="/etc/rs-lite"
USER_NAME="rs-lite"

log()   { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m %s\n'    "$*"; }
fail()  { printf '\033[1;31m[fail]\033[0m %s\n'    "$*" >&2; exit 1; }

# ---- 1. Sanity ----
[[ $EUID -eq 0 ]] || fail "Run as root (sudo bash install-lite.sh)."
command -v systemctl >/dev/null || fail "systemd is required."
command -v apt-get   >/dev/null || fail "Debian/DietPi expected (apt-get not found)."

if ss -ltnp 2>/dev/null | grep -q ':53 '; then
  warn "Something is already listening on :53 — install-lite will configure dnsmasq to take it."
fi

# ---- 2. apt ----
log "Installing apt packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  dnsmasq python3 python3-venv python3-pip logrotate ca-certificates curl

# log2ram is optional — DietPi has it; some Debian images don't ship it.
if apt-cache show log2ram >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends log2ram || warn "log2ram install failed (continuing)."
else
  warn "log2ram not in apt — SD-wear protection skipped. Consider installing manually."
fi

# ---- 3. user + dirs ----
log "Creating user and directories…"
if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home-dir "$PREFIX" --shell /usr/sbin/nologin "$USER_NAME"
fi
# /var/lib/rs-lite must be world-traversable so the `dnsmasq` user can read
# blocked.hosts via addn-hosts. The DB is mode 0644 (non-sensitive bcrypt
# hashes only); blocked.hosts is non-sensitive too.
install -d -o "$USER_NAME" -g "$USER_NAME" -m 0755 "$STATE_DIR"
install -d -o "$USER_NAME" -g "$USER_NAME" -m 0750 "$LOG_DIR"
install -d -o root         -g root         -m 0755 "$CONFIG_DIR"
install -d -o root         -g root         -m 0755 "$PREFIX"

# Re-apply on re-install: install -d does not chmod existing dirs.
chmod 0755 "$STATE_DIR"
chown "$USER_NAME:$USER_NAME" "$STATE_DIR"

# dnsmasq writes the query log itself, so it must own the file.
# rs-lite (the dashboard user) only needs to read it.
usermod -a -G "$USER_NAME" dnsmasq 2>/dev/null || true

# ---- 4. source + venv ----
log "Copying source tree to $PREFIX…"
rm -rf "$PREFIX/rs_lite"
cp -a  "$SRC_DIR/rs_lite" "$PREFIX/rs_lite"
cp     "$SRC_DIR/requirements.txt" "$PREFIX/requirements.txt"
chown -R root:root "$PREFIX"
find "$PREFIX" -type d -exec chmod 0755 {} +
find "$PREFIX" -type f -exec chmod 0644 {} +

if [[ ! -d "$PREFIX/venv" ]]; then
  log "Creating Python venv (this is the slow step on a Pi Zero — ~3 min)…"
  python3 -m venv "$PREFIX/venv"
fi
log "Installing Python deps into venv…"
"$PREFIX/venv/bin/pip" install --upgrade pip wheel
"$PREFIX/venv/bin/pip" install -r "$PREFIX/requirements.txt"

# Seed an empty sources.yml if not present (updater falls back to defaults).
if [[ ! -f "$CONFIG_DIR/sources.yml" ]]; then
  cat >"$CONFIG_DIR/sources.yml" <<'YML'
# RichSinkhole Lite — extra blocklist sources (optional).
# Format:
#   sources:
#     - https://example.com/hosts.txt
#     - { url: "https://example.com/list.csv", format: threatfox_csv }
# Built-in defaults (StevenBlack, AdAway, anudeepND, Hagezi fake/popupads,
# curbengh phishing-filter) are always merged in.
sources: []

# Domains never to block, no matter what feed they appear in.
whitelist: []

# Informational only — change /etc/dnsmasq.d/rs-lite.conf to actually use these.
upstream_resolvers:
  - 1.1.1.1
  - 9.9.9.9
YML
  chown root:root "$CONFIG_DIR/sources.yml"
  chmod 0644 "$CONFIG_DIR/sources.yml"
fi

# ---- 5. system configs ----
log "Detecting current upstream resolvers (used as fallback)…"
DETECTED_UPSTREAMS=()
if [[ -r /etc/resolv.conf ]]; then
  while read -r ns; do
    [[ -n "$ns" && "$ns" != "127.0.0.1" && "$ns" != "::1" ]] && DETECTED_UPSTREAMS+=("$ns")
  done < <(awk '/^nameserver[[:space:]]+/ {print $2}' /etc/resolv.conf)
fi
if (( ${#DETECTED_UPSTREAMS[@]} == 0 )); then
  DETECTED_UPSTREAMS=(1.1.1.1 9.9.9.9)
  log "  No usable upstreams in /etc/resolv.conf — falling back to ${DETECTED_UPSTREAMS[*]}."
else
  log "  Detected: ${DETECTED_UPSTREAMS[*]}"
fi

log "Installing dnsmasq, systemd, logrotate, polkit configs…"

# Generate /etc/dnsmasq.d/rs-lite.conf from the bundled template, swapping in
# the detected upstreams so dnsmasq forwards to a reachable resolver.
TMP_DNSMASQ_CONF="$(mktemp)"
{
  awk '/^server=/ {next} {print}' "$SRC_DIR/etc/dnsmasq.d/rs-lite.conf"
  for u in "${DETECTED_UPSTREAMS[@]}"; do
    echo "server=$u"
  done
} >"$TMP_DNSMASQ_CONF"
install -m 0644 "$TMP_DNSMASQ_CONF" /etc/dnsmasq.d/rs-lite.conf
rm -f "$TMP_DNSMASQ_CONF"

install -m 0644 "$SRC_DIR/etc/systemd/rs-lite-dashboard.service" /etc/systemd/system/rs-lite-dashboard.service
install -m 0644 "$SRC_DIR/etc/systemd/rs-lite-updater.service"   /etc/systemd/system/rs-lite-updater.service
install -m 0644 "$SRC_DIR/etc/systemd/rs-lite-updater.timer"     /etc/systemd/system/rs-lite-updater.timer

install -m 0644 "$SRC_DIR/etc/logrotate.d/rs-lite"               /etc/logrotate.d/rs-lite

# sudoers fragment lets rs-lite reload/restart dnsmasq without a password.
# (DBus/polkit is not always available on minimal DietPi/Raspbian images, so
# polkit alone is unreliable. We install both so whichever works, works.)
install -d -m 0755 /etc/sudoers.d
install -m 0440 "$SRC_DIR/etc/sudoers.d/rs-lite" /etc/sudoers.d/rs-lite
visudo -c -q -f /etc/sudoers.d/rs-lite || fail "sudoers fragment failed validation."

if [[ -d /etc/polkit-1/rules.d ]]; then
  install -m 0644 "$SRC_DIR/etc/polkit-1/rules.d/50-rs-lite-dnsmasq.rules" /etc/polkit-1/rules.d/50-rs-lite-dnsmasq.rules
fi

# Touch the log file with the right owner so dnsmasq + logrotate behave.
# dnsmasq writes; the rs-lite group reads.
touch "$LOG_DIR/dnsmasq.log"
chown dnsmasq:"$USER_NAME" "$LOG_DIR/dnsmasq.log"
chmod 0640 "$LOG_DIR/dnsmasq.log"
chmod 0750 "$LOG_DIR"

# ---- 6. resolv.conf ----
log "Pointing /etc/resolv.conf at 127.0.0.1…"
if [[ -L /etc/resolv.conf ]]; then
  warn "/etc/resolv.conf is a symlink (probably systemd-resolved); replacing with a static file."
  rm -f /etc/resolv.conf
fi
cat >/etc/resolv.conf <<'RCONF'
# Managed by rs-lite install-lite.sh — local dnsmasq is the resolver.
nameserver 127.0.0.1
options edns0
RCONF
chmod 0644 /etc/resolv.conf

# Disable systemd-resolved if active — it competes for :53.
if systemctl is-active --quiet systemd-resolved; then
  warn "Disabling systemd-resolved so dnsmasq can bind :53."
  systemctl disable --now systemd-resolved || true
fi

# ---- 7. enable + start ----
log "Reloading systemd + starting services…"
systemctl daemon-reload
systemctl restart dnsmasq
systemctl enable --now rs-lite-dashboard.service
systemctl enable --now rs-lite-updater.timer

log "Running first blocklist refresh (this can take ~1 min on the Zero)…"
systemctl start rs-lite-updater.service || warn "First refresh failed — check 'journalctl -u rs-lite-updater'."

# ---- 8. report ----
IP_GUESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "${IP_GUESS:-}" ]] || IP_GUESS="<this-pi-ip>"
echo
log "Done."
echo "  Dashboard: http://${IP_GUESS}:8080"
echo "  Open it in a browser on the LAN to set the admin password."
echo
echo "  Tail the log:    journalctl -fu rs-lite-dashboard"
echo "  Manual refresh:  sudo systemctl start rs-lite-updater"
echo "  Test DNS:        dig @${IP_GUESS} example.com"
