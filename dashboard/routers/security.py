# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import asyncio
import json
import time
import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

SINKHOLE_DB          = "/data/sinkhole.db"
BLOCKLIST_DB         = "/data/blocklist.db"
THREAT_INTEL_STATUS  = "/data/threat_intel_status.json"

router = APIRouter()

_sec_stats_cache: dict | None = None
_sec_stats_ts: float = 0.0
_SEC_TTL = 20.0

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS client_blocks (
        ip          TEXT PRIMARY KEY,
        blocked_at  TEXT NOT NULL,
        expires_at  TEXT NOT NULL,
        reason      TEXT DEFAULT 'rate_limit',
        query_count INTEGER DEFAULT 0
    )
"""

_REASON_LABELS = {
    "rate_limit":    "Query flood",
    "nxdomain_flood": "DNS recon (NXDOMAIN flood)",
    "iot_flood":     "IoT burst (queries/s exceeded)",
    "burst_limit":   "Burst limit (queries/s exceeded)",
    "blocked":       "Blocked",
}


@router.get("/security/blocks")
async def list_blocks():
    """Return all currently active client blocks."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            """SELECT ip, blocked_at, expires_at, reason, query_count
               FROM client_blocks
               WHERE expires_at > datetime('now')
               ORDER BY blocked_at DESC"""
        )
    return [
        {
            "ip": r[0],
            "blocked_at": r[1],
            "expires_at": r[2],
            "reason": r[3],
            "reason_label": _REASON_LABELS.get(r[3], r[3]),
            "query_count": r[4],
        }
        for r in rows
    ]


@router.delete("/security/blocks/{ip}")
async def unblock_client(ip: str):
    """Manually remove a client block."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute(
            "DELETE FROM client_blocks WHERE ip = ? AND expires_at > datetime('now')", (ip,)
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="IP not found in active block list")
    return {"ip": ip, "status": "unblocked"}


async def _empty_sec_row():
    return [(0, 0, 0)]


@router.get("/security/stats")
async def security_stats():
    """Security summary: active blocks + rate-limited queries last 24h."""
    global _sec_stats_cache, _sec_stats_ts
    if _sec_stats_cache and time.monotonic() - _sec_stats_ts < _SEC_TTL:
        return _sec_stats_cache

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        has_sec = await _table_exists(db, "security_events")
        # Count ratelimited / nxdomain in last 24h (use ts filter to avoid full scan)
        ql_row = (await db.execute_fetchall("""
            SELECT
                SUM(action='ratelimited'),
                SUM(action='nxdomain')
            FROM query_log
            WHERE ts >= datetime('now','-24 hours')
        """))[0]
        (blocks_row, sec_row) = await asyncio.gather(
            db.execute_fetchall("""
                SELECT
                    SUM(expires_at > datetime('now')),
                    COUNT(*)
                FROM client_blocks
            """),
            db.execute_fetchall("""
                SELECT
                    SUM(event_type='rebinding'                                AND ts >= datetime('now','-24 hours')),
                    SUM(event_type IN ('query_burst','dga_suspect')            AND ts >= datetime('now','-24 hours')),
                    SUM(event_type IN ('iot_flood','burst_limit')              AND ts >= datetime('now','-24 hours'))
                FROM security_events
            """) if has_sec else _empty_sec_row(),
        )

    active, total      = (int(v or 0) for v in blocks_row[0])
    ratelimited_24h, nxdomain_24h = (int(v or 0) for v in ql_row)
    rebinding_24h, anomaly_24h, iot_flood_24h = (int(v or 0) for v in sec_row[0])

    _sec_stats_cache = {
        "active_blocks":   active,
        "total_blocks":    total,
        "ratelimited_24h": ratelimited_24h,
        "nxdomain_24h":    nxdomain_24h,
        "rebinding_24h":   rebinding_24h,
        "anomaly_24h":     anomaly_24h,
        "iot_flood_24h":   iot_flood_24h,
    }
    _sec_stats_ts = time.monotonic()
    return _sec_stats_cache


async def _table_exists(db, name: str) -> bool:
    row = await db.execute_fetchall(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return bool(row)


@router.get("/security/events")
async def security_events(limit: int = 100):
    """Recent security events: rebinding attacks, DGA suspects, query bursts."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        if not await _table_exists(db, "security_events"):
            return []
        rows = await db.execute_fetchall(
            """SELECT ts, event_type, client_ip, domain, detail, resolved_ip
               FROM security_events
               ORDER BY ts DESC LIMIT ?""",
            (min(limit, 500),),
        )
    return [
        {
            "ts": r[0], "event_type": r[1], "client_ip": r[2],
            "domain": r[3], "detail": r[4], "resolved_ip": r[5],
        }
        for r in rows
    ]


@router.get("/security/threat-intel")
async def threat_intel_status():
    """Threat intel feed status and domain count."""
    try:
        with open(THREAT_INTEL_STATUS) as f:
            status = json.load(f)
    except FileNotFoundError:
        status = {"status": "never_run", "total_domains": 0, "last_updated": None, "feeds": []}
    except Exception:
        status = {"status": "error", "total_domains": 0, "last_updated": None, "feeds": []}

    # Live count from DB
    try:
        async with aiosqlite.connect(BLOCKLIST_DB) as db:
            rows = await db.execute_fetchall(
                "SELECT COUNT(*) FROM blocked_domains WHERE source='threat_intel'"
            )
            status["total_domains"] = rows[0][0]
    except Exception:
        pass

    return status
