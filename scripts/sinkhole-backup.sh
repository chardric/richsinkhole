#!/bin/bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.
#
# Scheduled backup for RichSinkhole — invoked daily by cron from the host
# via `docker exec richsinkhole-sinkhole-1 /usr/local/bin/sinkhole-backup.sh`,
# and on demand from the dashboard (Backup Now). Runs INSIDE the sinkhole
# container so /local and /data resolve to the live volume mounts.
#
# Source-of-truth paths (must match dns/server.py and dashboard/routers/backup.py):
#   /local/sinkhole.db        — query log, security events, fingerprints, schedules
#   /local/blocklist.db       — blocked_domains, allowed_domains, blocklist_feeds
#   /local/geoip-country.csv  — geo-block dataset
#   /local/config/config.yml  — runtime config (was /data/config/config.yml on the
#                               old layout; we copy from whichever exists for safety)

set -uo pipefail

LOCAL_DIR=/local
DATA_DIR=/data
CONFIG=/config/config.yml
BACKUP_DEFAULT=/mnt/nas/richsinkhole-backups
TIMESTAMP=$(date +%Y-%m-%d_%H-%M)

# ---------------------------------------------------------------------------
# Read backup_dir + retention from config (fall back to defaults).
# ---------------------------------------------------------------------------
BACKUP_ROOT=$(python3 -c "
import yaml
try:
    with open('$CONFIG') as f:
        cfg = yaml.safe_load(f) or {}
    print(cfg.get('backup_dir', '$BACKUP_DEFAULT'))
except Exception:
    print('$BACKUP_DEFAULT')
" 2>/dev/null)

KEEP_DAYS=$(python3 -c "
import yaml
try:
    with open('$CONFIG') as f:
        cfg = yaml.safe_load(f) or {}
    print(cfg.get('backup_retention_days', 30))
except Exception:
    print(30)
" 2>/dev/null)

BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

# ---------------------------------------------------------------------------
# Use SQLite's online backup API for the live DBs (consistent across writes).
# Files are sourced from /local — that's where DNS/blocker actually write.
# ---------------------------------------------------------------------------
python3 -c "
import sqlite3, sys
SOURCES = [
    ('/local/sinkhole.db',  '$BACKUP_DIR/sinkhole.db'),
    ('/local/blocklist.db', '$BACKUP_DIR/blocklist.db'),
]
errors = 0
for src_path, dst_path in SOURCES:
    try:
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dst_path)
        src.backup(dst)
        dst.close(); src.close()
    except Exception as exc:
        print(f'ERROR backing up {src_path}: {exc}', file=sys.stderr)
        errors += 1
sys.exit(1 if errors else 0)
"
DB_RC=$?

# ---------------------------------------------------------------------------
# Plain copies for static files. config.yml moved between layouts; try both.
# ---------------------------------------------------------------------------
cp "$LOCAL_DIR/geoip-country.csv" "$BACKUP_DIR/geoip-country.csv" 2>/dev/null

if [ -f "$LOCAL_DIR/config/config.yml" ]; then
    cp "$LOCAL_DIR/config/config.yml" "$BACKUP_DIR/config.yml"
elif [ -f "$DATA_DIR/config/config.yml" ]; then
    cp "$DATA_DIR/config/config.yml" "$BACKUP_DIR/config.yml"
fi

# Also back up the extra_routes.yml (managed by reconciler) if present.
if [ -f "$DATA_DIR/config/extra_routes.yml" ]; then
    cp "$DATA_DIR/config/extra_routes.yml" "$BACKUP_DIR/extra_routes.yml" 2>/dev/null
fi

# ---------------------------------------------------------------------------
# Sanity check — refuse to leave a 0-byte backup behind. A silent empty
# backup is worse than no backup; it gives a false sense of safety.
# ---------------------------------------------------------------------------
TOTAL_BYTES=$(du -sb "$BACKUP_DIR" 2>/dev/null | cut -f1)
FILE_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -type f | wc -l)

if [ "$DB_RC" -ne 0 ] || [ "$TOTAL_BYTES" -lt 1024 ] || [ "$FILE_COUNT" -eq 0 ]; then
    echo "$(date): FAILED backup at $BACKUP_DIR — db_rc=$DB_RC bytes=$TOTAL_BYTES files=$FILE_COUNT" >&2
    rm -rf "$BACKUP_DIR"
    exit 1
fi

# ---------------------------------------------------------------------------
# Retention sweep.
# ---------------------------------------------------------------------------
find "$BACKUP_ROOT" -maxdepth 1 -type d -name '20*' -mtime "+$KEEP_DAYS" -exec rm -rf {} +

echo "$(date): backup OK at $BACKUP_DIR ($((TOTAL_BYTES / 1024 / 1024)) MB, $FILE_COUNT files, retention=${KEEP_DAYS}d)"
