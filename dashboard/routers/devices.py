# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SINKHOLE_DB = "/local/sinkhole.db"

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS device_fingerprints (
        ip          TEXT PRIMARY KEY,
        device_type TEXT NOT NULL,
        confidence  INTEGER DEFAULT 0,
        first_seen  TEXT NOT NULL,
        last_seen   TEXT NOT NULL,
        label       TEXT DEFAULT '',
        profile     TEXT NOT NULL DEFAULT 'normal'
    )
"""

_VALID_PROFILES = {"normal", "strict", "passthrough", "quarantine", "guest"}


@router.get("/devices")
async def list_devices():
    """All fingerprinted devices, ordered by last seen."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            """SELECT d.ip, d.device_type, d.confidence, d.first_seen, d.last_seen,
                      d.label, COALESCE(d.profile, 'normal'),
                      COALESCE(d.parental_enabled, 0),
                      CASE WHEN w.ip IS NOT NULL THEN 1 ELSE 0 END
               FROM device_fingerprints d
               LEFT JOIN captive_whitelist w ON d.ip = w.ip
               ORDER BY d.last_seen DESC"""
        )
    return [
        {
            "ip":              r[0],
            "device_type":     r[1],
            "confidence":      r[2],
            "first_seen":      r[3],
            "last_seen":       r[4],
            "label":           r[5] or "",
            "profile":         r[6],
            "parental_enabled": bool(r[7]),
            "cert_installed":  bool(r[8]),
        }
        for r in rows
    ]


@router.get("/whitelist")
async def list_whitelist():
    """Devices that have installed the CA cert (captive portal whitelist)."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(
            """SELECT w.ip, w.ts, d.label, d.device_type
               FROM captive_whitelist w
               LEFT JOIN device_fingerprints d ON w.ip = d.ip
               ORDER BY w.ts DESC"""
        )
    return [
        {"ip": r[0], "whitelisted_at": r[1], "label": r[2] or "", "device_type": r[3] or ""}
        for r in rows
    ]


@router.delete("/whitelist/{ip}")
async def remove_from_whitelist(ip: str):
    """Remove a device from the captive whitelist (revoke cert trust)."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute("DELETE FROM captive_whitelist WHERE ip=?", (ip,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "IP not in whitelist")
    return {"ip": ip, "removed": True}


class LabelIn(BaseModel):
    label: str


class ProfileIn(BaseModel):
    profile: str


@router.patch("/devices/{ip}")
async def update_device_label(ip: str, body: LabelIn):
    """Set a friendly label for a device IP."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute(
            "UPDATE device_fingerprints SET label=? WHERE ip=?",
            (body.label.strip()[:64], ip),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
    return {"ip": ip, "label": body.label.strip()}


@router.patch("/devices/{ip}/profile")
async def update_device_profile(ip: str, body: ProfileIn):
    """Set blocking profile for a device: normal | strict | passthrough."""
    if body.profile not in _VALID_PROFILES:
        raise HTTPException(status_code=400, detail=f"profile must be one of: {', '.join(_VALID_PROFILES)}")
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute(
            "UPDATE device_fingerprints SET profile=? WHERE ip=?",
            (body.profile, ip),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
    return {"ip": ip, "profile": body.profile}


@router.delete("/devices/{ip}")
async def delete_device(ip: str):
    """Delete a device and all associated records (logs, parental, blocks, etc.)."""
    async with aiosqlite.connect(SINKHOLE_DB, timeout=120) as db:
        # Verify device exists
        row = await db.execute_fetchall(
            "SELECT ip FROM device_fingerprints WHERE ip=?", (ip,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Device not found")

        # Purge all related records (query_log can be large, do it in batches)
        while True:
            cur = await db.execute(
                "DELETE FROM query_log WHERE rowid IN "
                "(SELECT rowid FROM query_log WHERE client_ip=? LIMIT 50000)",
                (ip,),
            )
            await db.commit()
            if cur.rowcount == 0:
                break

        for tbl, col in [
            ("security_events", "client_ip"),
            ("client_blocks", "ip"),
            ("parental_usage", "ip"),
            ("parental_snooze", "ip"),
            ("captive_whitelist", "ip"),
            ("schedule_rules", "client_ip"),
        ]:
            await db.execute(f"DELETE FROM {tbl} WHERE {col}=?", (ip,))

        await db.execute("DELETE FROM device_fingerprints WHERE ip=?", (ip,))
        await db.commit()

    return {"ip": ip, "status": "deleted"}
