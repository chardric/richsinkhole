# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Query Activity Heatmap — GitHub-style grid showing DNS query volume
by hour-of-day x day-of-week.
"""
import time
import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()

_heatmap_cache: dict | None = None
_heatmap_cache_ts: float = 0.0
_HEATMAP_TTL = 120.0


@router.get("/heatmap")
async def query_heatmap():
    """Returns 7x24 matrix of query counts (last 7 days)."""
    global _heatmap_cache, _heatmap_cache_ts
    if _heatmap_cache and time.monotonic() - _heatmap_cache_ts < _HEATMAP_TTL:
        return _heatmap_cache

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall("""
            SELECT
                CAST(strftime('%w', ts) AS INTEGER) AS dow,
                CAST(strftime('%H', ts) AS INTEGER) AS hour,
                COUNT(*) AS cnt
            FROM query_log
            WHERE ts >= datetime('now', '-7 days')
            GROUP BY dow, hour
        """)

    # Build 7x24 grid (dow 0=Sunday..6=Saturday, hour 0..23)
    grid = [[0] * 24 for _ in range(7)]
    peak = 0
    for dow, hour, cnt in rows:
        grid[dow][hour] = cnt
        if cnt > peak:
            peak = cnt

    _heatmap_cache = {"grid": grid, "peak": peak}
    _heatmap_cache_ts = time.monotonic()
    return _heatmap_cache
