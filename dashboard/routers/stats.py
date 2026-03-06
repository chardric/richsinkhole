import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/data/sinkhole.db"
BLOCKLIST_DB = "/data/blocklist.db"

router = APIRouter()


@router.get("/stats")
async def get_stats():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        (total,) = (await db.execute_fetchall("SELECT COUNT(*) FROM query_log"))[0]
        (blocked,) = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM query_log WHERE action='blocked'"
        ))[0]
        (redirected,) = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM query_log WHERE action IN ('captive','youtube','redirected')"
        ))[0]
        (forwarded,) = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM query_log WHERE action IN ('forwarded','allowed','cached')"
        ))[0]
        (clients_seen,) = (await db.execute_fetchall(
            "SELECT COUNT(DISTINCT client_ip) FROM query_log"
        ))[0]
        top_blocked = await db.execute_fetchall("""
            SELECT domain, COUNT(*) AS cnt
            FROM query_log WHERE action='blocked'
            GROUP BY domain ORDER BY cnt DESC LIMIT 10
        """)
        top_clients = await db.execute_fetchall("""
            SELECT client_ip, COUNT(*) AS cnt
            FROM query_log
            GROUP BY client_ip ORDER BY cnt DESC LIMIT 10
        """)

    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        (total_blocked_domains,) = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM blocked_domains"
        ))[0]

    block_pct = round(blocked / total * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "blocked": blocked,
        "redirected": redirected,
        "forwarded": forwarded,
        "block_pct": block_pct,
        "clients_seen": clients_seen,
        "total_blocked_domains": total_blocked_domains,
        "top_blocked_domains": [
            {"domain": r[0], "count": r[1]} for r in top_blocked
        ],
        "top_clients": [
            {"ip": r[0], "count": r[1]} for r in top_clients
        ],
    }
