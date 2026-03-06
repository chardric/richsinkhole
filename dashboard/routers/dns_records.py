# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import re
import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SINKHOLE_DB = "/data/sinkhole.db"
HOSTNAME_RE = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.?)+$")
IP_RE       = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS dns_records (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT    NOT NULL UNIQUE,
        type     TEXT    NOT NULL DEFAULT 'A',
        value    TEXT    NOT NULL,
        ttl      INTEGER NOT NULL DEFAULT 300,
        enabled  INTEGER NOT NULL DEFAULT 1
    )
"""


class RecordIn(BaseModel):
    hostname: str
    type: str = "A"
    value: str
    ttl: int = 300
    enabled: bool = True


def _validate(body: RecordIn) -> tuple[str, str, str]:
    hostname = body.hostname.lower().strip().rstrip(".")
    if not hostname or not HOSTNAME_RE.match(hostname):
        raise HTTPException(status_code=400, detail=f"Invalid hostname: {hostname!r}")
    rtype = body.type.upper()
    if rtype not in ("A", "CNAME"):
        raise HTTPException(status_code=400, detail="type must be A or CNAME")
    value = body.value.strip()
    if rtype == "A" and not IP_RE.match(value):
        raise HTTPException(status_code=400, detail="A record value must be an IPv4 address")
    if rtype == "CNAME":
        value = value.lower().rstrip(".")
    if body.ttl < 0 or body.ttl > 86400:
        raise HTTPException(status_code=400, detail="TTL must be 0–86400")
    return hostname, rtype, value


@router.get("/dns-records")
async def list_records():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            "SELECT id, hostname, type, value, ttl, enabled FROM dns_records ORDER BY hostname ASC"
        )
    return [{"id": r[0], "hostname": r[1], "type": r[2], "value": r[3], "ttl": r[4], "enabled": bool(r[5])} for r in rows]


@router.post("/dns-records", status_code=201)
async def create_record(body: RecordIn):
    hostname, rtype, value = _validate(body)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        try:
            cur = await db.execute(
                "INSERT INTO dns_records (hostname, type, value, ttl, enabled) VALUES (?,?,?,?,?)",
                (hostname, rtype, value, body.ttl, int(body.enabled)),
            )
            await db.commit()
        except Exception:
            raise HTTPException(status_code=409, detail="Hostname already has a record")
    return {"id": cur.lastrowid, "hostname": hostname, "type": rtype, "value": value}


@router.patch("/dns-records/{record_id}")
async def update_record(record_id: int, body: RecordIn):
    hostname, rtype, value = _validate(body)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute(
            "UPDATE dns_records SET hostname=?, type=?, value=?, ttl=?, enabled=? WHERE id=?",
            (hostname, rtype, value, body.ttl, int(body.enabled), record_id),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Record not found")
    return {"id": record_id, "hostname": hostname, "type": rtype, "value": value}


@router.delete("/dns-records/{record_id}")
async def delete_record(record_id: int):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute("DELETE FROM dns_records WHERE id=?", (record_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Record not found")
    return {"deleted": record_id}
