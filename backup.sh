#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

# backup.sh — Back up all RichSinkhole persistent data to a single archive.
#
# What's backed up:
#   ./data/           → query logs, blocklist DB, captive whitelist, updater status
#   ./data/config/    → config.yml (DNS settings, YouTube redirect, captive portal)
#   updater/sources.yml → blocklist source URLs and whitelist
#   nginx/certs/      → CA certificate and private key
#
# Usage:
#   ./backup.sh                        # saves to ./backups/richsinkhole-YYYY-MM-DD.tar.gz
#   ./backup.sh /path/to/output.tar.gz # saves to specified path

set -e

OUTFILE="${1:-./backups/richsinkhole-$(date +%Y-%m-%d).tar.gz}"
mkdir -p "$(dirname "$OUTFILE")"

echo "==> Backing up RichSinkhole data..."
echo "    Output: $OUTFILE"

tar czf "$OUTFILE" \
  -C "$(pwd)" \
  data/ \
  updater/sources.yml \
  nginx/certs/

echo "==> Done: $OUTFILE ($(du -sh "$OUTFILE" | cut -f1))"
