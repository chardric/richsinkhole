#!/bin/bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.
#
# Scheduled backup for RichSinkhole — invoked daily by cron from the host
# via `docker exec -u root richsinkhole-sinkhole-1 /usr/local/bin/sinkhole-backup.sh`,
# and on demand from the dashboard (Backup Now). Runs INSIDE the sinkhole
# container so /local and /data resolve to the live volume mounts.
#
# Storage protocols (read from /config/config.yml -> backup_protocol):
#   local      — write to backup_dir on the host's local filesystem
#   nfs / smb  — write to backup_dir, which is a host mount point
#                (mount itself is set up by install.sh, not this script)
#   rsync-ssh  — stage in /tmp, rsync over SSH to a remote host using
#                /local/config/backup_ssh_ed25519
#
# Source-of-truth paths (must match dns/server.py and dashboard/routers/backup.py):
#   /local/sinkhole.db        — query log, security events, fingerprints
#   /local/blocklist.db       — blocked_domains, allowed_domains, feeds
#   /local/geoip-country.csv  — geo-block dataset
#   /local/config/config.yml  — runtime config

set -uo pipefail

LOCAL_DIR=/local
DATA_DIR=/data
CONFIG=/config/config.yml
BACKUP_DEFAULT=/mnt/nas/richsinkhole-backups
SSH_KEY=/local/config/backup_ssh_ed25519
TIMESTAMP=$(date +%Y-%m-%d_%H-%M)

# ---------------------------------------------------------------------------
# Read every config value we need in a single python invocation.
# ---------------------------------------------------------------------------
eval "$(python3 -c "
import yaml, shlex
try:
    with open('$CONFIG') as f:
        cfg = yaml.safe_load(f) or {}
except Exception:
    cfg = {}
def s(k, d):
    v = cfg.get(k, d)
    return shlex.quote(str(v) if v is not None else '')
print(f'PROTOCOL={s(\"backup_protocol\", \"nfs\")}')
print(f'BACKUP_ROOT={s(\"backup_dir\", \"$BACKUP_DEFAULT\")}')
print(f'KEEP_DAYS={s(\"backup_retention_days\", 30)}')
print(f'SSH_HOST={s(\"backup_ssh_host\", \"\")}')
print(f'SSH_USER={s(\"backup_ssh_user\", \"\")}')
print(f'SSH_PORT={s(\"backup_ssh_port\", 22)}')
print(f'SSH_PATH={s(\"backup_ssh_path\", \"\")}')
")"

# ---------------------------------------------------------------------------
# Stage to a temp dir for rsync-ssh; otherwise write directly to backup_dir.
# ---------------------------------------------------------------------------
case "$PROTOCOL" in
    rsync-ssh)
        STAGE_DIR=$(mktemp -d "/tmp/sinkhole-backup-XXXXXX")
        BACKUP_DIR="$STAGE_DIR/$TIMESTAMP"
        ;;
    local|nfs|smb)
        BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
        ;;
    *)
        echo "$(date): FAILED — unknown backup_protocol '$PROTOCOL'" >&2
        exit 2
        ;;
esac

mkdir -p "$BACKUP_DIR"

# ---------------------------------------------------------------------------
# SQLite online backup API (consistent across writes).
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
# Static files.
# ---------------------------------------------------------------------------
cp "$LOCAL_DIR/geoip-country.csv" "$BACKUP_DIR/geoip-country.csv" 2>/dev/null

if [ -f "$LOCAL_DIR/config/config.yml" ]; then
    cp "$LOCAL_DIR/config/config.yml" "$BACKUP_DIR/config.yml"
elif [ -f "$DATA_DIR/config/config.yml" ]; then
    cp "$DATA_DIR/config/config.yml" "$BACKUP_DIR/config.yml"
fi

if [ -f "$DATA_DIR/config/extra_routes.yml" ]; then
    cp "$DATA_DIR/config/extra_routes.yml" "$BACKUP_DIR/extra_routes.yml" 2>/dev/null
fi

# ---------------------------------------------------------------------------
# Sanity check — refuse to keep a 0-byte backup. Better no backup than a
# silent empty one that gives false confidence.
# ---------------------------------------------------------------------------
TOTAL_BYTES=$(du -sb "$BACKUP_DIR" 2>/dev/null | cut -f1)
FILE_COUNT=$(find "$BACKUP_DIR" -maxdepth 1 -type f | wc -l)

if [ "$DB_RC" -ne 0 ] || [ "$TOTAL_BYTES" -lt 1024 ] || [ "$FILE_COUNT" -eq 0 ]; then
    echo "$(date): FAILED backup at $BACKUP_DIR — db_rc=$DB_RC bytes=$TOTAL_BYTES files=$FILE_COUNT" >&2
    rm -rf "$BACKUP_DIR"
    [ -n "${STAGE_DIR:-}" ] && rm -rf "$STAGE_DIR"
    exit 1
fi

# ---------------------------------------------------------------------------
# Protocol-specific transfer + retention.
# ---------------------------------------------------------------------------
case "$PROTOCOL" in
    local|nfs|smb)
        # Already written to final destination; just sweep retention.
        find "$BACKUP_ROOT" -maxdepth 1 -type d -name '20*' -mtime "+$KEEP_DAYS" -exec rm -rf {} +
        ;;

    rsync-ssh)
        if [ -z "$SSH_HOST" ] || [ -z "$SSH_USER" ] || [ -z "$SSH_PATH" ]; then
            echo "$(date): FAILED — rsync-ssh missing SSH_HOST/USER/PATH in config" >&2
            rm -rf "$STAGE_DIR"
            exit 1
        fi
        if [ ! -f "$SSH_KEY" ]; then
            echo "$(date): FAILED — SSH key $SSH_KEY missing (generate via dashboard)" >&2
            rm -rf "$STAGE_DIR"
            exit 1
        fi

        # Push the new backup; -a preserves metadata, --partial saves work on a
        # broken connection. StrictHostKeyChecking=accept-new auto-trusts a new
        # remote host on first use (TOFU); after that, MITM attempts fail.
        if ! rsync -aq --partial \
                --rsh="ssh -i $SSH_KEY -p $SSH_PORT \
                    -o StrictHostKeyChecking=accept-new \
                    -o UserKnownHostsFile=/local/config/backup_ssh_known_hosts \
                    -o ConnectTimeout=15" \
                "$BACKUP_DIR" "${SSH_USER}@${SSH_HOST}:${SSH_PATH}/" ; then
            echo "$(date): FAILED — rsync to ${SSH_USER}@${SSH_HOST}:${SSH_PATH} failed" >&2
            rm -rf "$STAGE_DIR"
            exit 1
        fi

        # Remote retention sweep (best-effort — non-fatal if it fails).
        ssh -i "$SSH_KEY" -p "$SSH_PORT" \
            -o StrictHostKeyChecking=accept-new \
            -o UserKnownHostsFile=/local/config/backup_ssh_known_hosts \
            -o ConnectTimeout=15 \
            "${SSH_USER}@${SSH_HOST}" \
            "find '$SSH_PATH' -maxdepth 1 -type d -name '20*' -mtime +$KEEP_DAYS -exec rm -rf {} +" \
            2>/dev/null || true

        rm -rf "$STAGE_DIR"
        BACKUP_DIR="${SSH_USER}@${SSH_HOST}:${SSH_PATH}/$TIMESTAMP"
        ;;
esac

echo "$(date): backup OK [$PROTOCOL] at $BACKUP_DIR ($((TOTAL_BYTES / 1024 / 1024)) MB, $FILE_COUNT files, retention=${KEEP_DAYS}d)"
