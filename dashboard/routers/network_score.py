# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Network Health Score — composite 0-100 score based on:
  - Sinkhole effectiveness (block rate)
  - Security posture (few threats/events)
  - DNS performance (response latency)
  - System health (services up, blocklist fresh)
"""
import json
import time
import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/local/sinkhole.db"
STATUS_PATH = "/data/updater_status.json"

router = APIRouter()

_score_cache: dict | None = None
_score_cache_ts: float = 0.0
_SCORE_TTL = 60.0


@router.get("/network-score")
async def network_score():
    global _score_cache, _score_cache_ts
    if _score_cache and time.monotonic() - _score_cache_ts < _SCORE_TTL:
        return _score_cache

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        # 1. Block effectiveness (last 24h)
        row = (await db.execute_fetchall("""
            SELECT
                COUNT(*) AS total,
                SUM(action = 'blocked') AS blocked,
                AVG(CASE WHEN response_ms IS NOT NULL AND response_ms > 0
                    THEN response_ms END) AS avg_ms
            FROM query_log
            WHERE ts >= datetime('now', 'localtime', '-24 hours')
        """))[0]
        total_24h = int(row[0] or 0)
        blocked_24h = int(row[1] or 0)
        avg_ms = float(row[2] or 0)

        # 2. Security events (last 24h)
        sec_count = (await db.execute_fetchall("""
            SELECT COUNT(*) FROM security_events
            WHERE ts >= datetime('now', 'localtime', '-24 hours')
        """))[0][0] or 0

        # 3. Active client blocks (only non-expired)
        active_blocks = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM client_blocks WHERE expires_at > datetime('now', 'localtime')"
        ))[0][0] or 0

        # Housekeeping: purge expired blocks
        await db.execute("DELETE FROM client_blocks WHERE expires_at <= datetime('now', 'localtime')")
        await db.commit()

    # 4. Updater status
    updater_ok = False
    try:
        with open(STATUS_PATH) as f:
            s = json.load(f)
        updater_ok = s.get("status") == "ok"
    except Exception:
        pass

    # ── Scoring (each component 0-25, total 0-100) ──

    # Protection score (0-25): higher block rate = better protection
    if total_24h > 0:
        block_pct = blocked_24h / total_24h * 100
        # Sweet spot: 10-40% block rate is healthy
        if block_pct < 5:
            protection = 15  # low blocking, might be misconfigured
        elif block_pct > 60:
            protection = 18  # very high, could be over-blocking
        else:
            protection = 25  # healthy range
    else:
        protection = 10  # no data

    # Security score (0-25): detections are positive (system working).
    # DGA/tunnel detectors are noisy (CDN subdomains, Firefox Sync), so
    # only true concern is a massive *actionable* event spike.
    # Typical busy home network: 1000-5000 events/day (mostly DGA noise).
    if sec_count == 0:
        security = 22          # quiet, no issues
    elif sec_count <= 500:
        security = 25          # healthy: threats detected & handled
    elif sec_count <= 2000:
        security = 23          # normal for active network with DGA detector
    elif sec_count <= 5000:
        security = 20          # busy but coping
    elif sec_count <= 10000:
        security = 15          # elevated — worth investigating
    else:
        security = 8           # extreme — likely active attack or misconfigured

    # Active blocks: only penalize beyond 3 simultaneous (rare)
    if active_blocks > 3:
        security = max(5, security - (active_blocks - 3) * 2)

    # Performance score (0-25): lower latency = better
    if avg_ms <= 0:
        performance = 20  # no data, assume ok
    elif avg_ms <= 20:
        performance = 25
    elif avg_ms <= 50:
        performance = 22
    elif avg_ms <= 100:
        performance = 18
    elif avg_ms <= 200:
        performance = 12
    else:
        performance = 5

    # System score (0-25): blocklist freshness + services
    system = 15  # base
    if updater_ok:
        system += 10

    total_score = min(100, protection + security + performance + system)

    # Grade
    if total_score >= 90:
        grade = "A"
    elif total_score >= 75:
        grade = "B"
    elif total_score >= 60:
        grade = "C"
    elif total_score >= 40:
        grade = "D"
    else:
        grade = "F"

    _score_cache = {
        "score": total_score,
        "grade": grade,
        "breakdown": {
            "protection": {"score": protection, "max": 25,
                           "detail": f"{blocked_24h:,} blocked / {total_24h:,} total (24h)"},
            "security":   {"score": security, "max": 25,
                           "detail": f"{sec_count} threats caught, {active_blocks} blocked clients (24h)"},
            "performance": {"score": performance, "max": 25,
                            "detail": f"{avg_ms:.0f}ms avg response"},
            "system":     {"score": system, "max": 25,
                           "detail": "Blocklist " + ("fresh" if updater_ok else "stale")},
        },
    }
    _score_cache_ts = time.monotonic()
    return _score_cache
