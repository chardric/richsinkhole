#!/usr/bin/env bash
# restore.sh — Restore RichSinkhole data from a backup archive.
#
# Usage:
#   ./restore.sh ./backups/richsinkhole-2026-03-05.tar.gz
#
# WARNING: This overwrites existing data. Stop containers first or data may be corrupted.

set -e

ARCHIVE="${1:-}"

if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "Usage: $0 <backup.tar.gz>"
  echo ""
  echo "Available backups:"
  ls -lh ./backups/*.tar.gz 2>/dev/null || echo "  (none found in ./backups/)"
  exit 1
fi

echo "==> Restoring from: $ARCHIVE"
echo ""
echo "WARNING: This will overwrite all current data (query logs, blocklist, config, certs)."
read -r -p "Continue? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

echo ""
echo "==> Stopping containers..."
docker compose down

echo "==> Restoring data..."
tar xzf "$ARCHIVE" -C "$(pwd)"

echo "==> Starting containers..."
docker compose up -d

echo ""
echo "==> Restore complete. Verify services:"
docker compose ps
