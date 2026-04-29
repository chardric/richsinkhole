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

REMOTE="${RS_REMOTE:-richard@10.254.254.4}"

# All services run inside one unified container. Each "service" is a source
# subdir on the host; everything is copied into /app/<svc> in the container.
UNIFIED_CTR="richsinkhole-sinkhole-1"

declare -A SRC=( [dashboard]="dashboard" [dns]="dns" [updater]="updater" [sinkhole]="sinkhole" )
declare -A DST=( [dashboard]="/app/dashboard" [dns]="/app/dns" [updater]="/app/updater" [sinkhole]="/app/sinkhole" )

SERVICES=("${@}")
if [ ${#SERVICES[@]} -eq 0 ]; then
  echo "Usage: ./hotdeploy.sh <service> [service...]"
  echo "  services: dashboard dns updater sinkhole"
  echo "  override target host: RS_REMOTE=user@host ./hotdeploy.sh ..."
  exit 1
fi

restart_needed=0
for svc in "${SERVICES[@]}"; do
  src="${SRC[$svc]}"
  dst="${DST[$svc]}"

  if [ -z "$src" ]; then
    echo "Unknown service: $svc"
    exit 1
  fi

  echo "==> Hot-deploying $svc..."

  rsync -az --delete --exclude='__pycache__' --exclude='*.pyc' \
    "./${src}/" "${REMOTE}:/tmp/hotdeploy_${svc}/"

  ssh "$REMOTE" "docker cp /tmp/hotdeploy_${svc}/. ${UNIFIED_CTR}:${dst}/ && rm -rf /tmp/hotdeploy_${svc}"

  echo "  ✓ $svc copied"
  restart_needed=1
done

if [ "$restart_needed" -eq 1 ]; then
  echo "==> Restarting ${UNIFIED_CTR}..."
  ssh "$REMOTE" "docker restart ${UNIFIED_CTR}"
  echo "  ✓ container restarted"
  echo
  echo "  NOTE: hot-deploys are ephemeral. To persist across container"
  echo "  recreations, rebuild the image: ./deploy.sh sinkhole"
fi
