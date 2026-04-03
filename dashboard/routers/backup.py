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
DATA_DIR = "/data"
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
    backup_path = os.path.join(_get_backup_root(), body.date)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup {body.date} not found")

    restored = []
    for filename in ["sinkhole.db", "blocklist.db", "config.yml", "geoip-country.csv"]:
        src = os.path.join(backup_path, filename)
        if filename == "config.yml":
            dst = os.path.join(DATA_DIR, "config", filename)
        else:
            dst = os.path.join(DATA_DIR, filename)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            restored.append(filename)

    return {"status": "restored", "date": body.date, "files": restored}


@router.get("/backups/config")
async def get_backup_config():
    """Get backup configuration."""
    return {"backup_dir": _get_backup_root()}


class BackupConfigIn(BaseModel):
    backup_dir: str


@router.post("/backups/config")
async def save_backup_config(body: BackupConfigIn):
    """Save backup directory path."""
    path = body.backup_dir.strip()
    if not path:
        raise HTTPException(status_code=400, detail="Backup directory cannot be empty")
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        cfg["backup_dir"] = path
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        return {"status": "saved", "backup_dir": path}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/backups/{date}")
async def delete_backup(date: str):
    """Delete a backup folder by date."""
    # Validate date format to prevent path traversal
    if not date.replace("-", "").isdigit() or len(date) != 10:
        raise HTTPException(status_code=400, detail="Invalid date format")
    backup_path = os.path.join(_get_backup_root(), date)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup {date} not found")
    shutil.rmtree(backup_path)
    return {"status": "deleted", "date": date}
