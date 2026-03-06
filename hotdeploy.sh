#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

# hotdeploy.sh — Fast dev deploy: rsync source into running container, restart.
# No image rebuild. Use only when Python/JS/HTML files changed, NOT dependencies.
#
# Usage:
#   ./hotdeploy.sh dashboard       # redeploy dashboard only
#   ./hotdeploy.sh dns             # redeploy dns only
#   ./hotdeploy.sh dashboard dns   # multiple

set -e

REMOTE="richard@10.254.254.4"

# Map service name → (local source dir, container name, container dest dir)
declare -A SRC=( [dashboard]="dashboard" [dns]="dns" [updater]="updater" [youtube-proxy]="youtube-proxy" )
declare -A CTR=( [dashboard]="richsinkhole-dashboard-1" [dns]="richsinkhole-dns-1" [updater]="richsinkhole-updater-1" [youtube-proxy]="richsinkhole-youtube-proxy-1" )
declare -A DST=( [dashboard]="/dashboard" [dns]="/dns" [updater]="/updater" [youtube-proxy]="/app" )

SERVICES=("${@}")
if [ ${#SERVICES[@]} -eq 0 ]; then
  echo "Usage: ./hotdeploy.sh <service> [service...]"
  echo "  services: dashboard dns updater youtube-proxy"
  exit 1
fi

for svc in "${SERVICES[@]}"; do
  src="${SRC[$svc]}"
  ctr="${CTR[$svc]}"
  dst="${DST[$svc]}"

  if [ -z "$src" ]; then
    echo "Unknown service: $svc"
    exit 1
  fi

  echo "==> Hot-deploying $svc..."

  # Rsync source to RPi tmp, then docker cp into container
  rsync -az --delete --exclude='__pycache__' --exclude='*.pyc' \
    "./${src}/" "${REMOTE}:/tmp/hotdeploy_${svc}/"

  ssh "$REMOTE" "docker cp /tmp/hotdeploy_${svc}/. ${ctr}:${dst}/ && docker restart ${ctr} && rm -rf /tmp/hotdeploy_${svc}"

  echo "  ✓ $svc hot-deployed"
done
