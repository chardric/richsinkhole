# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""Backup & restore API — lists backups, triggers manual backup, restores, deletes."""

import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import yaml

CONFIG_PATH = "/config/config.yml"
BACKUP_SCRIPT = "/usr/local/bin/sinkhole-backup.sh"
DATA_DIR = "/data"       # NAS-backed: sinkhole.db (query log)
LOCAL_DIR = "/local"     # SD-backed: blocklist.db, geoip-country.csv
DEFAULT_BACKUP_DIR = "/mnt/nas/richsinkhole-backups"


def _get_backup_root() -> str:
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("backup_dir", DEFAULT_BACKUP_DIR)
    except Exception:
        return DEFAULT_BACKUP_DIR

router = APIRouter()


@router.get("/backups")
async def list_backups():
    """List available backup folders sorted by date (newest first)."""
    if not os.path.isdir(_get_backup_root()):
        return {"backups": [], "backup_dir": _get_backup_root()}
    backups = []
    for entry in sorted(os.listdir(_get_backup_root()), reverse=True):
        path = os.path.join(_get_backup_root(), entry)
        if os.path.isdir(path) and entry[:4].isdigit():
            files = os.listdir(path)
            size_bytes = sum(os.path.getsize(os.path.join(path, f)) for f in files)
            backups.append({
                "date": entry,
                "files": files,
                "size_mb": round(size_bytes / 1024 / 1024, 1),
            })
    return {"backups": backups, "backup_dir": _get_backup_root()}


@router.post("/backups/run")
async def trigger_backup():
    """Run backup script immediately."""
    if not os.path.isfile(BACKUP_SCRIPT):
        raise HTTPException(status_code=503, detail="Backup script not found")
    try:
        result = subprocess.run(
            [BACKUP_SCRIPT],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr or "Backup failed")
        return {"status": "ok", "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Backup timed out")


class RestoreIn(BaseModel):
    date: str  # e.g. "2026-04-03"


@router.post("/backups/restore")
async def restore_backup(body: RestoreIn):
    """Restore from a dated backup folder."""
    if ".." in body.date or "/" in body.date:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    backup_path = os.path.join(_get_backup_root(), body.date)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup {body.date} not found")

    restored = []
    # File → target dir mapping (some files live on NAS, others on local SD)
    _restore_paths = {
        "sinkhole.db":        DATA_DIR,
        "blocklist.db":       LOCAL_DIR,
        "geoip-country.csv":  LOCAL_DIR,
        "config.yml":         os.path.join(LOCAL_DIR, "config"),
    }
    for filename, target_dir in _restore_paths.items():
        src = os.path.join(backup_path, filename)
        dst = os.path.join(target_dir, filename)
        if os.path.isfile(src):
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(filename)

    return {"status": "restored", "date": body.date, "files": restored}


@router.get("/backups/config")
async def get_backup_config():
    """Get backup configuration."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return {
        "backup_dir": cfg.get("backup_dir", DEFAULT_BACKUP_DIR),
        "backup_hour": cfg.get("backup_hour", 2),
        "backup_minute": cfg.get("backup_minute", 0),
        "backup_retention_days": cfg.get("backup_retention_days", 30),
    }


class BackupConfigIn(BaseModel):
    backup_dir: str = ""
    backup_hour: int = 2
    backup_minute: int = 0
    backup_retention_days: int = 30


@router.post("/backups/config")
async def save_backup_config(body: BackupConfigIn):
    """Save backup configuration and update cron schedule."""
    path = body.backup_dir.strip()
    if not path:
        raise HTTPException(status_code=400, detail="Backup directory cannot be empty")
    # Restrict to safe prefixes — prevent arbitrary filesystem access
    _SAFE_PREFIXES = ("/mnt/", "/data/backups", "/backups")
    resolved = os.path.realpath(path)
    if not any(resolved.startswith(p) for p in _SAFE_PREFIXES):
        raise HTTPException(status_code=400, detail="Backup directory must be under /mnt/, /data/backups, or /backups")
    if not (0 <= body.backup_hour <= 23):
        raise HTTPException(status_code=400, detail="Hour must be 0-23")
    if not (0 <= body.backup_minute <= 59):
        raise HTTPException(status_code=400, detail="Minute must be 0-59")
    if not (1 <= body.backup_retention_days <= 365):
        raise HTTPException(status_code=400, detail="Retention must be 1-365 days")
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        cfg["backup_dir"] = path
        cfg["backup_hour"] = body.backup_hour
        cfg["backup_minute"] = body.backup_minute
        cfg["backup_retention_days"] = body.backup_retention_days
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        # Update host cron via Docker socket
        _update_cron(body.backup_hour, body.backup_minute)

        return {"status": "saved"}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save backup config")


def _update_cron(hour: int, minute: int) -> None:
    """Update the backup cron schedule on the host.

    The cron entry must invoke the script INSIDE the sinkhole container
    (`docker exec -u root ...`) because the script's paths (/local, /data,
    /config, /mnt/nas/...) only resolve there. Running on the host directly
    silently produces 0-byte backups every night.
    """
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5,
        )
        lines = [l for l in result.stdout.splitlines() if "sinkhole-backup" not in l]
        lines.append(
            f"{minute} {hour} * * * docker exec -u root richsinkhole-sinkhole-1 "
            f"/usr/local/bin/sinkhole-backup.sh >> /var/log/sinkhole-backup.log 2>&1"
        )
        subprocess.run(
            ["crontab", "-"], input="\n".join(lines) + "\n",
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        pass  # cron update is best-effort from inside container


@router.delete("/backups/{date}")
async def delete_backup(date: str):
    """Delete a backup folder by date."""
    # Validate format to prevent path traversal (YYYY-MM-DD or YYYY-MM-DD_HH-MM)
    clean = date.replace("-", "").replace("_", "")
    if not clean.isdigit() or len(date) not in (10, 16) or ".." in date or "/" in date:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    backup_path = os.path.join(_get_backup_root(), date)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup {date} not found")
    shutil.rmtree(backup_path)
    return {"status": "deleted", "date": date}
