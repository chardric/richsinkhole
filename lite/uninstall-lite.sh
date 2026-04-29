#!/usr/bin/env bash
# RichSinkhole Lite — uninstaller.
# Removes the rs-lite user, services, configs, and (optionally) state.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

set -euo pipefail

PREFIX="/opt/rs-lite"
STATE_DIR="/var/lib/rs-lite"
LOG_DIR="/var/log/rs-lite"
CONFIG_DIR="/etc/rs-lite"
USER_NAME="rs-lite"

log()  { printf '\033[1;34m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n'      "$*"; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n'      "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Run as root."

KEEP_STATE=1
case "${1:-}" in
  --purge) KEEP_STATE=0 ;;
  "")      KEEP_STATE=1 ;;
  *)       fail "Unknown arg: $1 (use --purge to also delete state and logs)" ;;
esac

log "Stopping services…"
systemctl disable --now rs-lite-dashboard.service 2>/dev/null || true
systemctl disable --now rs-lite-updater.timer     2>/dev/null || true
systemctl stop          rs-lite-updater.service   2>/dev/null || true

log "Removing systemd, logrotate, polkit, sudoers, dnsmasq drop-in…"
rm -f /etc/systemd/system/rs-lite-dashboard.service
rm -f /etc/systemd/system/rs-lite-updater.service
rm -f /etc/systemd/system/rs-lite-updater.timer
rm -f /etc/logrotate.d/rs-lite
rm -f /etc/polkit-1/rules.d/50-rs-lite-dnsmasq.rules
rm -f /etc/sudoers.d/rs-lite
rm -f /etc/dnsmasq.d/rs-lite.conf
systemctl daemon-reload
systemctl restart dnsmasq 2>/dev/null || true

log "Removing $PREFIX…"
rm -rf "$PREFIX"

if (( KEEP_STATE == 0 )); then
  log "Purging state, logs, configs…"
  rm -rf "$STATE_DIR" "$LOG_DIR" "$CONFIG_DIR"
  if id -u "$USER_NAME" >/dev/null 2>&1; then
    userdel "$USER_NAME" || warn "userdel $USER_NAME failed."
  fi
else
  log "Keeping $STATE_DIR and $LOG_DIR (use --purge to delete them)."
fi

log "Done. /etc/resolv.conf was NOT restored — fix it manually if needed."
