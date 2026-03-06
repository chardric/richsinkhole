import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SINKHOLE_DB = "/data/sinkhole.db"

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

_VALID_PROFILES = {"normal", "strict", "passthrough"}


@router.get("/devices")
async def list_devices():
    """All fingerprinted devices, ordered by last seen."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            """SELECT ip, device_type, confidence, first_seen, last_seen, label,
                      COALESCE(profile, 'normal')
               FROM device_fingerprints
               ORDER BY last_seen DESC"""
        )
    return [
        {
            "ip":          r[0],
            "device_type": r[1],
            "confidence":  r[2],
            "first_seen":  r[3],
            "last_seen":   r[4],
            "label":       r[5] or "",
            "profile":     r[6],
        }
        for r in rows
    ]


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
