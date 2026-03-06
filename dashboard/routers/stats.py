import asyncio
import time
import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/data/sinkhole.db"
BLOCKLIST_DB = "/data/blocklist.db"

router = APIRouter()

_stats_cache: dict | None = None
_stats_cache_ts: float = 0.0
_STATS_TTL = 15.0  # seconds


@router.get("/stats")
async def get_stats():
    global _stats_cache, _stats_cache_ts
    if _stats_cache and time.monotonic() - _stats_cache_ts < _STATS_TTL:
        return _stats_cache

    # Single aggregation pass over query_log — one table scan instead of five
    async def _query_sinkhole():
        async with aiosqlite.connect(SINKHOLE_DB) as db:
            row = (await db.execute_fetchall("""
                SELECT
                    COUNT(*)                                                        AS total,
                    SUM(action = 'blocked')                                         AS blocked,
                    SUM(action IN ('captive','youtube','redirected'))                AS redirected,
                    SUM(action IN ('forwarded','allowed','cached'))                  AS forwarded,
                    COUNT(DISTINCT client_ip)                                        AS clients_seen
                FROM query_log
            """))[0]
            top_blocked, top_clients = await asyncio.gather(
                db.execute_fetchall("""
                    SELECT domain, COUNT(*) AS cnt FROM query_log
                    WHERE action='blocked'
                    GROUP BY domain ORDER BY cnt DESC LIMIT 10
                """),
                db.execute_fetchall("""
                    SELECT client_ip, COUNT(*) AS cnt FROM query_log
                    GROUP BY client_ip ORDER BY cnt DESC LIMIT 10
                """),
            )
        return row, top_blocked, top_clients

    async def _query_blocklist():
        async with aiosqlite.connect(BLOCKLIST_DB) as db:
            return (await db.execute_fetchall("SELECT COUNT(*) FROM blocked_domains"))[0][0]

    (row, top_blocked, top_clients), total_blocked_domains = await asyncio.gather(
        _query_sinkhole(), _query_blocklist()
    )

    total, blocked, redirected, forwarded, clients_seen = (int(v or 0) for v in row)
    block_pct          = round(blocked / total * 100, 1) if total > 0 else 0.0
    bandwidth_saved_mb = round(blocked * 75 / 1024, 1)
    time_saved_min     = round(blocked * 1.5 / 60, 1)
    ad_revenue_denied  = round(blocked * 0.0035, 2)

    _stats_cache = {
        "total": total,
        "blocked": blocked,
        "redirected": redirected,
        "forwarded": forwarded,
        "block_pct": block_pct,
        "clients_seen": clients_seen,
        "total_blocked_domains": total_blocked_domains,
        "bandwidth_saved_mb": bandwidth_saved_mb,
        "time_saved_min": time_saved_min,
        "ad_revenue_denied": ad_revenue_denied,
        "top_blocked_domains": [{"domain": r[0], "count": r[1]} for r in top_blocked],
        "top_clients":         [{"ip": r[0],     "count": r[1]} for r in top_clients],
    }
    _stats_cache_ts = time.monotonic()
    return _stats_cache
