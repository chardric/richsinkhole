# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import re
import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

BLOCKLIST_DB = "/data/blocklist.db"
DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$")

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS allowed_domains (
        domain   TEXT PRIMARY KEY,
        note     TEXT DEFAULT '',
        added_at TEXT DEFAULT (datetime('now'))
    )
"""


def _validate(domain: str) -> str:
    domain = domain.lower().strip().rstrip(".")
    if not domain or not DOMAIN_RE.match(domain):
        raise HTTPException(status_code=400, detail=f"Invalid domain: {domain!r}")
    return domain


class AllowIn(BaseModel):
    domain: str
    note: str = ""


@router.get("/allowlist")
async def list_allowlist():
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            "SELECT domain, note, added_at FROM allowed_domains ORDER BY domain ASC"
        )
    return [{"domain": r[0], "note": r[1], "added_at": r[2]} for r in rows]


@router.post("/allowlist", status_code=201)
async def add_allowlist(body: AllowIn):
    domain = _validate(body.domain)
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        await db.execute(_ENSURE_TABLE)
        try:
            await db.execute(
                "INSERT INTO allowed_domains (domain, note) VALUES (?, ?)",
                (domain, body.note.strip()[:120]),
            )
            await db.commit()
        except Exception:
            raise HTTPException(status_code=409, detail="Domain already in allowlist")
    return {"domain": domain, "status": "added"}


@router.delete("/allowlist/{domain:path}")
async def remove_allowlist(domain: str):
    domain = _validate(domain)
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        cur = await db.execute("DELETE FROM allowed_domains WHERE domain = ?", (domain,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Domain not found")
    return {"domain": domain, "status": "removed"}
