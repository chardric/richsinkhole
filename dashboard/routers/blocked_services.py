# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

from typing import List

import aiosqlite
from fastapi import APIRouter
from pydantic import BaseModel

from services_data import GROUPS, SERVICES, SERVICES_BY_ID

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS blocked_services (
        service_id TEXT PRIMARY KEY,
        enabled_at TEXT DEFAULT (datetime('now'))
    )
"""


class BlockedServicesIn(BaseModel):
    ids: List[str]


async def _enabled_ids() -> set:
    """Return the set of currently-enabled (blocked) service IDs."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall("SELECT service_id FROM blocked_services")
    return {r[0] for r in rows}


@router.get("/blocked-services")
async def list_blocked_services():
    """All available services with their enabled state."""
    enabled = await _enabled_ids()
    return {
        "groups": GROUPS,
        "services": [
            {
                "id": s["id"],
                "name": s["name"],
                "group": s["group"],
                "domain_count": len(s["domains"]),
                "enabled": s["id"] in enabled,
            }
            for s in SERVICES
        ],
    }


@router.put("/blocked-services")
async def update_blocked_services(body: BlockedServicesIn):
    """Replace the set of blocked service IDs."""
    valid_ids = [sid for sid in body.ids if sid in SERVICES_BY_ID]
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        await db.execute("DELETE FROM blocked_services")
        for sid in valid_ids:
            await db.execute(
                "INSERT INTO blocked_services (service_id) VALUES (?)", (sid,)
            )
        await db.commit()
    return {"status": "saved", "count": len(valid_ids)}


@router.get("/blocked-services/domains")
async def blocked_services_domains():
    """All domains currently blocked by enabled services."""
    enabled = await _enabled_ids()
    domains = []
    for sid in enabled:
        svc = SERVICES_BY_ID.get(sid)
        if svc:
            domains.extend(svc["domains"])
    return {"domains": sorted(set(domains))}
