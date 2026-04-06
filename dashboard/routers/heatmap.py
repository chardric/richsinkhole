# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Query Activity Heatmap — GitHub-style grid showing DNS query volume
by hour-of-day x day-of-week.
"""
import time
from datetime import datetime as _dt
import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/local/sinkhole.db"

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

    # Use substr() instead of strftime() — 50x faster on low-power hardware.
    # Group by (date, hour) in SQL; compute day-of-week in Python.
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall("""
            SELECT
                substr(ts, 1, 10) AS dt,
                CAST(substr(ts, 12, 2) AS INTEGER) AS hour,
                COUNT(*) AS cnt
            FROM query_log
            WHERE ts >= datetime('now', '-7 days')
            GROUP BY dt, hour
        """)

    # Build 7x24 grid (dow 0=Sunday..6=Saturday, hour 0..23)
    grid = [[0] * 24 for _ in range(7)]
    peak = 0
    for dt_str, hour, cnt in rows:
        # Python weekday: 0=Mon..6=Sun → convert to JS strftime('%w'): 0=Sun..6=Sat
        py_dow = _dt.strptime(dt_str, "%Y-%m-%d").weekday()  # 0=Mon
        dow = (py_dow + 1) % 7  # 0=Sun
        grid[dow][hour] += cnt
        if grid[dow][hour] > peak:
            peak = grid[dow][hour]

    _heatmap_cache = {"grid": grid, "peak": peak}
    _heatmap_cache_ts = time.monotonic()
    return _heatmap_cache
