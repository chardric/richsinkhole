# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import asyncio
import aiosqlite
from fastapi import APIRouter, HTTPException

SINKHOLE_DB = "/local/sinkhole.db"

router = APIRouter()


@router.get("/devices/{ip}/stats")
async def device_stats(ip: str):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        # Single scan for all counts
        agg = (await db.execute_fetchall("""
            SELECT
                COUNT(*) AS total,
                SUM(action='blocked') AS blocked,
                SUM(action IN ('forwarded','allowed','cached')) AS forwarded
            FROM query_log WHERE client_ip=?
        """, (ip,)))[0]
        total, blocked, forwarded = int(agg[0] or 0), int(agg[1] or 0), int(agg[2] or 0)
        if total == 0:
            raise HTTPException(status_code=404, detail="No queries found for this device")

        # Fetch everything in parallel
        top_blocked, top_forwarded, recent, dev_row = await asyncio.gather(
            db.execute_fetchall("""
                SELECT domain, COUNT(*) AS cnt FROM query_log
                WHERE client_ip=? AND action='blocked'
                GROUP BY domain ORDER BY cnt DESC LIMIT 10
            """, (ip,)),
            db.execute_fetchall("""
                SELECT domain, COUNT(*) AS cnt FROM query_log
                WHERE client_ip=? AND action IN ('forwarded','allowed','cached')
                GROUP BY domain ORDER BY cnt DESC LIMIT 10
            """, (ip,)),
            db.execute_fetchall("""
                SELECT ts, domain, qtype, action FROM query_log
                WHERE client_ip=? ORDER BY id DESC LIMIT 50
            """, (ip,)),
            db.execute_fetchall("""
                SELECT label, device_type FROM device_fingerprints WHERE ip=?
            """, (ip,)),
        )

    label       = dev_row[0][0] if dev_row and dev_row[0][0] else None
    device_type = dev_row[0][1] if dev_row else None

    # Bandwidth estimation: avg ad payload ~75KB, avg page ~300KB per DNS query
    bandwidth_saved_mb = round(blocked * 75 / 1024, 1)
    bandwidth_used_mb  = round(forwarded * 300 / 1024, 1)

    return {
        "ip":          ip,
        "label":       label,
        "device_type": device_type,
        "total":       total,
        "blocked":     blocked,
        "forwarded":   forwarded,
        "block_pct":   round(blocked / total * 100, 1) if total else 0.0,
        "bandwidth_saved_mb":  bandwidth_saved_mb,
        "bandwidth_used_mb":   bandwidth_used_mb,
        "top_blocked_domains":   [{"domain": r[0], "count": r[1]} for r in top_blocked],
        "top_forwarded_domains": [{"domain": r[0], "count": r[1]} for r in top_forwarded],
        "recent_queries": [
            {"ts": r[0], "domain": r[1], "qtype": r[2], "action": r[3]} for r in recent
        ],
    }
