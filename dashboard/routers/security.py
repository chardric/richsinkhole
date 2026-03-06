import aiosqlite
from fastapi import APIRouter, HTTPException

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()

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


@router.get("/security/stats")
async def security_stats():
    """Security summary: active blocks + rate-limited queries last 24h."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        active = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM client_blocks WHERE expires_at > datetime('now')"
        ))[0][0]
        total = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM client_blocks"
        ))[0][0]
        ratelimited_24h = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM query_log WHERE action = 'ratelimited' AND ts >= datetime('now', '-24 hours')"
        ))[0][0]
        nxdomain_24h = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM query_log WHERE action = 'nxdomain' AND ts >= datetime('now', '-24 hours')"
        ))[0][0]
    return {
        "active_blocks": active,
        "total_blocks": total,
        "ratelimited_24h": ratelimited_24h,
        "nxdomain_24h": nxdomain_24h,
    }
