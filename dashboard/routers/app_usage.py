# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
App usage dashboard — estimates app usage time per device from DNS patterns.
Maps DNS queries to apps/services, clusters into sessions, estimates screen time.
"""

import time
import aiosqlite
from fastapi import APIRouter, Query

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()

_usage_cache: dict[str, tuple[float, dict]] = {}
_USAGE_TTL = 120.0  # cache for 2 minutes

# App definitions: service name -> domain suffixes
# Uses a curated subset of services_data.py for time-trackable apps
_APP_DOMAINS: dict[str, list[str]] = {
    "YouTube":    ["youtube.com", "youtu.be", "googlevideo.com", "ytimg.com"],
    "Facebook":   ["facebook.com", "fbcdn.net", "fb.com", "fbsbx.com"],
    "Instagram":  ["instagram.com", "cdninstagram.com"],
    "TikTok":     ["tiktok.com", "tiktokcdn.com", "bytedance.com", "byteimg.com"],
    "WhatsApp":   ["whatsapp.com", "whatsapp.net"],
    "Messenger":  ["messenger.com"],
    "Netflix":    ["netflix.com", "nflxvideo.net", "nflxext.com"],
    "Spotify":    ["spotify.com", "scdn.co", "spotifycdn.com"],
    "Twitter/X":  ["twitter.com", "x.com", "twimg.com"],
    "Snapchat":   ["snapchat.com", "snap.com"],
    "Reddit":     ["reddit.com", "redditmedia.com"],
    "Discord":    ["discord.com", "discordapp.com"],
    "Telegram":   ["telegram.org", "t.me"],
    "Google":     ["google.com", "googleapis.com", "gstatic.com"],
    "Shopee":     ["shopee.ph", "shopee.com", "shopeemobile.com"],
    "Lazada":     ["lazada.com.ph", "lazada.com"],
    "ChatGPT":    ["chatgpt.com", "openai.com"],
    "Gaming":     ["roblox.com", "steampowered.com", "epicgames.com"],
}

# Reverse mapping: domain suffix -> app name
_DOMAIN_TO_APP: list[tuple[str, str]] = []
for app, domains in _APP_DOMAINS.items():
    for d in domains:
        _DOMAIN_TO_APP.append((d, app))
_DOMAIN_TO_APP.sort(key=lambda x: -len(x[0]))  # longest first


def _classify_app(domain: str) -> str | None:
    for suffix, app in _DOMAIN_TO_APP:
        if domain == suffix or domain.endswith("." + suffix):
            return app
    return None


@router.get("/app-usage/{ip}")
async def device_app_usage(ip: str, range: str = Query("24h", pattern="^(24h|7d)$")):
    """Per-device app usage with estimated session time."""
    cache_key = f"{ip}:{range}"
    cached = _usage_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _USAGE_TTL:
        return cached[1]

    sql_range = "-24 hours" if range == "24h" else "-7 days"

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(f"""
            SELECT domain, ts FROM query_log
            WHERE client_ip=? AND ts >= datetime('now', '{sql_range}')
              AND action IN ('forwarded', 'allowed', 'cached')
            ORDER BY ts
        """, (ip,))

    # Classify queries into app sessions
    # Session = cluster of queries to same app within 5-minute gaps
    SESSION_GAP = 300  # seconds

    app_sessions: dict[str, list[list[str]]] = {}  # app -> [[ts1, ts2, ...], ...]
    for domain, ts in rows:
        app = _classify_app(domain)
        if not app:
            continue
        sessions = app_sessions.setdefault(app, [[]])
        last_session = sessions[-1]
        if last_session and ts:
            # Compare timestamps
            from datetime import datetime
            try:
                last_ts = datetime.strptime(last_session[-1], "%Y-%m-%d %H:%M:%S")
                curr_ts = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                gap = (curr_ts - last_ts).total_seconds()
                if gap > SESSION_GAP:
                    sessions.append([ts])
                else:
                    last_session.append(ts)
            except (ValueError, TypeError):
                last_session.append(ts)
        else:
            last_session.append(ts)

    # Calculate estimated usage time per app
    # Minimum 5 queries per app to count as real usage (filters out
    # background prefetches, embedded widgets, and browser hints)
    _MIN_QUERIES = 5

    result = []
    for app, sessions in app_sessions.items():
        total_queries = sum(len(s) for s in sessions)
        if total_queries < _MIN_QUERIES:
            continue  # likely a prefetch or embedded widget, not real usage
        session_count = len([s for s in sessions if s])
        # Estimate time: each session = (last_ts - first_ts) + 2 min baseline
        total_minutes = 0
        for session in sessions:
            if len(session) >= 2:
                from datetime import datetime
                try:
                    start = datetime.strptime(session[0], "%Y-%m-%d %H:%M:%S")
                    end = datetime.strptime(session[-1], "%Y-%m-%d %H:%M:%S")
                    total_minutes += (end - start).total_seconds() / 60 + 2
                except (ValueError, TypeError):
                    total_minutes += 2
            elif session:
                total_minutes += 2  # single-query session = ~2 min baseline

        result.append({
            "app": app,
            "queries": total_queries,
            "sessions": session_count,
            "estimated_minutes": round(total_minutes, 1),
        })

    result.sort(key=lambda x: -x["estimated_minutes"])

    response = {"ip": ip, "range": range, "apps": result}
    _usage_cache[cache_key] = (time.monotonic(), response)
    return response
