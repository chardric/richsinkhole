# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""DNS Canary Tokens — hidden tripwire domains that trigger alerts when queried."""
import secrets

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS canary_tokens (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        token          TEXT    NOT NULL UNIQUE,
        label          TEXT    NOT NULL DEFAULT '',
        created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
        last_triggered TEXT    DEFAULT NULL,
        trigger_count  INTEGER NOT NULL DEFAULT 0
    )
"""

_CANARY_SUFFIX = ".rscanary"


class CanaryIn(BaseModel):
    label: str = ""


@router.get("/canary-tokens")
async def list_canary_tokens():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            "SELECT id, token, label, created_at, last_triggered, trigger_count "
            "FROM canary_tokens ORDER BY id DESC"
        )
    return [
        {
            "id":            r[0],
            "token":         r[1],
            "domain":        r[1] + _CANARY_SUFFIX,
            "label":         r[2],
            "created_at":    r[3],
            "last_triggered": r[4],
            "trigger_count": r[5],
        }
        for r in rows
    ]


@router.post("/canary-tokens", status_code=201)
async def create_canary_token(body: CanaryIn):
    token = secrets.token_hex(8)   # 16 hex chars → e.g. a1b2c3d4e5f60718
    domain = token + _CANARY_SUFFIX
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        await db.execute(
            "INSERT INTO canary_tokens (token, label) VALUES (?, ?)",
            (token, body.label.strip()[:64]),
        )
        await db.commit()
    return {"token": token, "domain": domain, "label": body.label}


@router.delete("/canary-tokens/{token_id}")
async def delete_canary_token(token_id: int):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute("DELETE FROM canary_tokens WHERE id=?", (token_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Token not found")
    return {"deleted": token_id}
