#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

# backup.sh — Back up all RichSinkhole persistent data to a single archive.
#
# What's backed up:
#   ./data/             → query logs, captive whitelist (NAS-backed)
#   ./local-data/       → blocklist.db, geoip-country.csv, config/ (SD-backed)
#   updater/sources.yml → blocklist source URLs and whitelist
#   nginx/certs/        → CA certificate and private key
#
# Usage:
#   ./backup.sh                        # saves to ./backups/richsinkhole-YYYY-MM-DD.tar.gz
#   ./backup.sh /path/to/output.tar.gz # saves to specified path

set -euo pipefail

OUTFILE="${1:-./backups/richsinkhole-$(date +%Y-%m-%d).tar.gz}"
mkdir -p "$(dirname "$OUTFILE")"

echo "==> Backing up RichSinkhole data..."
echo "    Output: $OUTFILE"

# Build list of existing paths (some may be absent on fresh installs)
PATHS=()
for p in data/ local-data/ updater/sources.yml nginx/certs/; do
    [ -e "$p" ] && PATHS+=("$p")
done

tar czf "$OUTFILE" -C "$(pwd)" "${PATHS[@]}"

echo "==> Done: $OUTFILE ($(du -sh "$OUTFILE" | cut -f1))"
