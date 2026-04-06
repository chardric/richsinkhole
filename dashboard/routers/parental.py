# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

from datetime import datetime, timedelta

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()
templates = Jinja2Templates(directory="/dashboard/templates")

# Hard-coded social media and gaming seed domains
_SOCIAL_DOMAINS = [
    "facebook.com", "www.facebook.com", "m.facebook.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com",
    "twitter.com", "www.twitter.com",
    "x.com", "www.x.com",
    "snapchat.com", "www.snapchat.com",
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "pinterest.com", "www.pinterest.com",
    "discord.com", "www.discord.com",
    "linkedin.com", "www.linkedin.com",
    "tumblr.com", "www.tumblr.com",
    "threads.net", "www.threads.net",
]

_GAMING_DOMAINS = [
    "store.steampowered.com", "steamcommunity.com", "steampowered.com",
    "roblox.com", "www.roblox.com",
    "epicgames.com", "www.epicgames.com",
    "minecraft.net", "www.minecraft.net",
    "xbox.com", "www.xbox.com",
    "playstation.com", "www.playstation.com",
    "ea.com", "www.ea.com",
    "battle.net", "www.battle.net",
    "leagueoflegends.com", "www.leagueoflegends.com",
    "twitch.tv", "www.twitch.tv",
    "fortnite.com", "www.fortnite.com",
    "valvesoftware.com",
]


async def ensure_tables(db: aiosqlite.Connection) -> None:
    """Create parental control tables and seed domain lists."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS parental_domains (
            domain   TEXT PRIMARY KEY,
            category TEXT NOT NULL CHECK(category IN ('social', 'gaming'))
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS parental_usage (
            ip          TEXT NOT NULL,
            category    TEXT NOT NULL,
            date        TEXT NOT NULL,
            query_count INTEGER DEFAULT 0,
            PRIMARY KEY (ip, category, date)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS parental_snooze (
            ip         TEXT NOT NULL,
            category   TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            PRIMARY KEY (ip, category)
        )
    """)
    # Seed social domains
    for d in _SOCIAL_DOMAINS:
        await db.execute(
            "INSERT OR IGNORE INTO parental_domains (domain, category) VALUES (?, 'social')", (d,)
        )
    # Seed gaming domains
    for d in _GAMING_DOMAINS:
        await db.execute(
            "INSERT OR IGNORE INTO parental_domains (domain, category) VALUES (?, 'gaming')", (d,)
        )
    # Add parental columns to device_fingerprints if not present
    for col, default in [
        ("parental_enabled",      0),
        ("parental_block_social", 1),
        ("parental_block_gaming", 0),
        ("parental_social_limit", 500),
        ("parental_gaming_limit", 500),
    ]:
        try:
            await db.execute(
                f"ALTER TABLE device_fingerprints ADD COLUMN {col} INTEGER DEFAULT {default}"
            )
        except Exception:
            pass  # column already exists
    await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _domain_category(blocked_host: str, social_set: set, gaming_set: set) -> str | None:
    """Return 'social', 'gaming', or None by matching domain suffixes."""
    parts = blocked_host.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in social_set:
            return "social"
        if suffix in gaming_set:
            return "gaming"
    return None


async def _get_warning_info(client_ip: str, blocked_host: str, db: aiosqlite.Connection):
    """
    Determine if this request should show a screen-time warning instead of a hard block.
    Returns (category, snoozed) where category is 'social'/'gaming'/None.
    If snoozed is True, the user already clicked "Continue" and DNS just hasn't refreshed yet.
    """
    if not client_ip or not blocked_host:
        return None, False

    row = await db.execute_fetchall(
        """SELECT parental_social_limit, parental_gaming_limit,
                  parental_block_social,  parental_block_gaming
           FROM device_fingerprints
           WHERE ip = ? AND parental_enabled = 1""",
        (client_ip,),
    )
    if not row:
        return None, False

    social_limit = row[0][0] or 0
    gaming_limit = row[0][1] or 0
    block_social = bool(row[0][2])
    block_gaming = bool(row[0][3])

    all_domains = await db.execute_fetchall(
        "SELECT domain, category FROM parental_domains"
    )
    social_set = {r[0] for r in all_domains if r[1] == "social"}
    gaming_set = {r[0] for r in all_domains if r[1] == "gaming"}

    category = _domain_category(blocked_host, social_set, gaming_set)
    if not category:
        return None, False

    # Hard-blocked category → always show block page, no warning
    if category == "social" and block_social:
        return None, False
    if category == "gaming" and block_gaming:
        return None, False

    limit = social_limit if category == "social" else gaming_limit
    if limit == 0:
        return None, False

    # Check snooze
    snooze_row = await db.execute_fetchall(
        "SELECT expires_at FROM parental_snooze WHERE ip=? AND category=?",
        (client_ip, category),
    )
    snoozed = False
    if snooze_row:
        try:
            expires = datetime.strptime(snooze_row[0][0], "%Y-%m-%d %H:%M:%S")
            snoozed = expires > datetime.now()
        except Exception:
            pass

    # Check today's usage
    today = datetime.now().strftime("%Y-%m-%d")
    usage_row = await db.execute_fetchall(
        "SELECT query_count FROM parental_usage WHERE ip=? AND category=? AND date=?",
        (client_ip, category, today),
    )
    today_count = usage_row[0][0] if usage_row else 0

    if today_count >= limit:
        return category, snoozed

    return None, False


# ── Block / Warning pages ──────────────────────────────────────────────────────

@router.get("/parental-block", response_class=HTMLResponse)
async def parental_block_page(request: Request):
    import re as _re
    raw_host = request.headers.get("x-blocked-host", "")
    # Sanitize — only allow valid hostname characters to prevent reflected XSS
    blocked_host = raw_host if _re.match(r'^[a-zA-Z0-9\.\-]+$', raw_host) else ""
    client_ip    = request.headers.get("x-real-ip", "")
    if not client_ip and request.client:
        client_ip = request.client.host

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        warning_category, snoozed = await _get_warning_info(client_ip, blocked_host, db)

    nonce = getattr(request.state, "csp_nonce", "")

    if warning_category and not snoozed:
        return templates.TemplateResponse(request, "screen_time_warning.html", context={
            "blocked_host": blocked_host,
            "category":     warning_category,
            "client_ip":    client_ip,
            "csp_nonce":    nonce,
        })

    return templates.TemplateResponse(request, "parental_block.html", context={
        "blocked_host": blocked_host,
        "csp_nonce":    nonce,
    })


# ── Per-device parental settings ──────────────────────────────────────────────

@router.get("/api/parental/settings/{ip}")
async def get_parental_settings(ip: str):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        row = await db.execute_fetchall(
            """SELECT parental_enabled, parental_block_social, parental_block_gaming,
                      COALESCE(parental_social_limit, 500),
                      COALESCE(parental_gaming_limit, 500)
               FROM device_fingerprints WHERE ip = ?""",
            (ip,),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")
    r = row[0]
    return {
        "ip":                    ip,
        "parental_enabled":      bool(r[0]),
        "parental_block_social": bool(r[1]),
        "parental_block_gaming": bool(r[2]),
        "parental_social_limit": r[3],
        "parental_gaming_limit": r[4],
    }


class ParentalSettingsIn(BaseModel):
    parental_enabled:      bool = False
    parental_block_social: bool = True
    parental_block_gaming: bool = False
    parental_social_limit: int  = 500
    parental_gaming_limit: int  = 500


@router.post("/api/parental/settings/{ip}")
async def save_parental_settings(ip: str, body: ParentalSettingsIn):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute(
            """UPDATE device_fingerprints
               SET parental_enabled       = ?,
                   parental_block_social  = ?,
                   parental_block_gaming  = ?,
                   parental_social_limit  = ?,
                   parental_gaming_limit  = ?
               WHERE ip = ?""",
            (int(body.parental_enabled),
             int(body.parental_block_social),
             int(body.parental_block_gaming),
             max(0, body.parental_social_limit),
             max(0, body.parental_gaming_limit),
             ip),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Device not found")
    return {"status": "saved", "ip": ip}


# ── Screen time snooze ─────────────────────────────────────────────────────────

@router.post("/api/parental/snooze/{ip}/{category}")
async def set_snooze(ip: str, category: str):
    if category not in ("social", "gaming"):
        raise HTTPException(status_code=400, detail="category must be 'social' or 'gaming'")
    expires_at = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(
            """INSERT INTO parental_snooze (ip, category, expires_at) VALUES (?, ?, ?)
               ON CONFLICT(ip, category) DO UPDATE SET expires_at = excluded.expires_at""",
            (ip, category, expires_at),
        )
        await db.commit()
    return {"status": "snoozed", "ip": ip, "category": category, "expires_at": expires_at}


# ── Screen time usage ──────────────────────────────────────────────────────────

@router.get("/api/parental/usage/{ip}")
async def get_usage(ip: str):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(
            "SELECT category, query_count FROM parental_usage WHERE ip=? AND date=?",
            (ip, today),
        )
    return {
        "ip":     ip,
        "date":   today,
        "social": next((r[1] for r in rows if r[0] == "social"), 0),
        "gaming": next((r[1] for r in rows if r[0] == "gaming"), 0),
    }
