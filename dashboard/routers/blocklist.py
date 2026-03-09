# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiosqlite
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

BLOCKLIST_DB = "/data/blocklist.db"

DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)

router = APIRouter()

_yt_cache: dict | None = None
_yt_cache_ts: float = 0.0
_YT_TTL = 300.0

_HOSTS_SKIP = {"localhost", "localhost.localdomain", "broadcasthost", "local", "ip6-localhost"}


def _validate(domain: str) -> str:
    domain = domain.lower().strip().rstrip(".")
    if not domain or not DOMAIN_RE.match(domain):
        raise HTTPException(status_code=400, detail=f"Invalid domain: {domain!r}")
    return domain


def _feed_name(url: str) -> str:
    """Derive a human-readable name from a feed URL."""
    try:
        parsed = urlparse(url)
        host   = parsed.netloc
        parts  = parsed.path.strip("/").split("/")
        if "githubusercontent.com" in host or "github.com" in host:
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
        return host
    except Exception:
        return url[:60]


def _parse_hosts(text: str) -> list[str]:
    """Parse a hosts file or plain domain list into validated domain strings."""
    domains: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts     = line.split()
        candidate = (parts[1] if len(parts) >= 2 else parts[0]).lower().rstrip(".")
        if candidate in _HOSTS_SKIP:
            continue
        if DOMAIN_RE.match(candidate):
            domains.append(candidate)
    return domains


_schema_ready = False


async def _ensure_feeds_table(db: aiosqlite.Connection) -> None:
    """Create blocklist_feeds table and add source column if needed (lightweight DDL only)."""
    global _schema_ready
    if _schema_ready:
        return
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS blocklist_feeds (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            url          TEXT    NOT NULL UNIQUE,
            name         TEXT,
            domain_count INTEGER DEFAULT 0,
            last_synced  TEXT,
            enabled      INTEGER DEFAULT 1,
            is_builtin   INTEGER DEFAULT 0,
            created_at   TEXT    DEFAULT (datetime('now'))
        )
    """)
    try:
        await db.execute("ALTER TABLE blocked_domains ADD COLUMN source TEXT")
    except Exception:
        pass  # Column already exists
    await db.commit()
    _schema_ready = True


class DomainIn(BaseModel):
    domain: str


class ImportIn(BaseModel):
    url: str


class BatchCheckIn(BaseModel):
    domains: list[str]


# ── Feed subscriptions ────────────────────────────────────────────────────────

@router.get("/blocklist/feeds")
async def list_feeds():
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        await _ensure_feeds_table(db)
        rows = await db.execute_fetchall(
            """SELECT id, url, name, domain_count, last_synced, enabled, is_builtin
               FROM blocklist_feeds ORDER BY is_builtin DESC, id ASC"""
        )
    return [
        {
            "id":           r[0],
            "url":          r[1],
            "name":         r[2] or _feed_name(r[1]),
            "domain_count": r[3] or 0,
            "last_synced":  r[4],
            "enabled":      bool(r[5]),
            "is_builtin":   bool(r[6]),
        }
        for r in rows
    ]


@router.post("/blocklist/feeds", status_code=201)
async def add_feed(body: ImportIn):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http:// or https://")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Failed to fetch URL: {exc}")

    domains = _parse_hosts(text)
    if not domains:
        raise HTTPException(422, "No valid domains found in the provided content")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        await _ensure_feeds_table(db)
        existing = await db.execute_fetchall(
            "SELECT id FROM blocklist_feeds WHERE url = ?", (url,)
        )
        if existing:
            raise HTTPException(409, "This feed URL is already subscribed")

        cursor = await db.execute(
            "INSERT INTO blocklist_feeds (url, domain_count, last_synced, enabled, is_builtin) "
            "VALUES (?, ?, ?, 1, 0)",
            (url, len(domains), now),
        )
        feed_id = cursor.lastrowid
        source  = f"feed:{feed_id}"

        await db.executemany(
            "INSERT OR IGNORE INTO blocked_domains (domain, source) VALUES (?, ?)",
            [(d, source) for d in domains],
        )
        await db.commit()

    return {"id": feed_id, "imported": len(domains), "status": "added"}


@router.delete("/blocklist/feeds/{feed_id}")
async def remove_feed(feed_id: int):
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        await _ensure_feeds_table(db)
        rows = await db.execute_fetchall(
            "SELECT url, is_builtin FROM blocklist_feeds WHERE id = ?", (feed_id,)
        )
        if not rows:
            raise HTTPException(404, "Feed not found")
        _, is_builtin = rows[0]
        if is_builtin:
            raise HTTPException(
                400, "Built-in feeds are managed via sources.yml on the server"
            )
        source = f"feed:{feed_id}"
        await db.execute("DELETE FROM blocked_domains WHERE source = ?", (source,))
        await db.execute("DELETE FROM blocklist_feeds WHERE id = ?", (feed_id,))
        await db.commit()
    return {"status": "removed"}


@router.post("/blocklist/feeds/{feed_id}/sync")
async def sync_feed(feed_id: int):
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        await _ensure_feeds_table(db)
        rows = await db.execute_fetchall(
            "SELECT url, is_builtin FROM blocklist_feeds WHERE id = ?", (feed_id,)
        )
        if not rows:
            raise HTTPException(404, "Feed not found")
        url, is_builtin = rows[0]
        if is_builtin:
            raise HTTPException(
                400, "Built-in feeds sync automatically via the daily updater schedule."
            )

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Failed to fetch feed: {exc}")

    domains = _parse_hosts(text)
    source  = f"feed:{feed_id}"
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        await db.execute("DELETE FROM blocked_domains WHERE source = ?", (source,))
        await db.executemany(
            "INSERT OR IGNORE INTO blocked_domains (domain, source) VALUES (?, ?)",
            [(d, source) for d in domains],
        )
        await db.execute(
            "UPDATE blocklist_feeds SET domain_count = ?, last_synced = ? WHERE id = ?",
            (len(domains), now, feed_id),
        )
        await db.commit()

    return {"synced": len(domains), "status": "ok"}


# ── Custom (manually-added) domains ──────────────────────────────────────────

@router.get("/blocklist/custom")
async def list_custom(page: int = 1, limit: int = 100, search: str = ""):
    page   = max(1, page)
    limit  = min(max(1, limit), 500)
    offset = (page - 1) * limit
    where  = "FROM blocked_domains WHERE source = 'custom'"
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        await _ensure_feeds_table(db)
        if search:
            pattern = f"%{search}%"
            rows = await db.execute_fetchall(
                f"SELECT domain, added_at {where} AND domain LIKE ? ORDER BY domain ASC LIMIT ? OFFSET ?",
                (pattern, limit, offset),
            )
            total = (await db.execute_fetchall(
                f"SELECT COUNT(*) {where} AND domain LIKE ?", (pattern,)
            ))[0][0]
        else:
            rows = await db.execute_fetchall(
                f"SELECT domain, added_at {where} ORDER BY domain ASC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            total = (await db.execute_fetchall(f"SELECT COUNT(*) {where}"))[0][0]
    return {
        "total":   total,
        "page":    page,
        "pages":   max(1, -(-total // limit)),
        "domains": [{"domain": r[0], "added_at": r[1]} for r in rows],
    }


@router.post("/blocklist", status_code=201)
async def add_domain(body: DomainIn):
    domain = _validate(body.domain)
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        existing = await db.execute_fetchall(
            "SELECT 1 FROM blocked_domains WHERE domain = ?", (domain,)
        )
        if existing:
            raise HTTPException(status_code=409, detail="Domain already blocked")
        await db.execute(
            "INSERT INTO blocked_domains (domain, source) VALUES (?, 'custom')", (domain,)
        )
        await db.commit()
    return {"domain": domain, "status": "added"}


@router.delete("/blocklist/{domain:path}")
async def remove_domain(domain: str):
    domain = _validate(domain)
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        rows = await db.execute_fetchall(
            "SELECT source FROM blocked_domains WHERE domain = ?", (domain,)
        )
        if not rows:
            raise HTTPException(404, "Domain not found")
        source = rows[0][0]
        if source in ("blocklist", "threat_intel") or (source and source.startswith("feed:")):
            raise HTTPException(
                400,
                "This domain is from a subscription feed. "
                "Add it to the Allowlist to unblock it, or remove the entire feed.",
            )
        cur = await db.execute("DELETE FROM blocked_domains WHERE domain = ?", (domain,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Domain not found")
    return {"domain": domain, "status": "removed"}


# ── Domain lookup (full list, read-only) ──────────────────────────────────────

@router.get("/blocklist")
async def list_blocklist(page: int = 1, limit: int = 100, search: str = ""):
    page   = max(1, page)
    limit  = min(max(1, limit), 500)
    offset = (page - 1) * limit
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        if search:
            pattern = f"%{search}%"
            rows = await db.execute_fetchall(
                "SELECT domain, added_at FROM blocked_domains WHERE domain LIKE ? ORDER BY domain ASC LIMIT ? OFFSET ?",
                (pattern, limit, offset),
            )
            total = (await db.execute_fetchall(
                "SELECT COUNT(*) FROM blocked_domains WHERE domain LIKE ?", (pattern,)
            ))[0][0]
        else:
            rows = await db.execute_fetchall(
                "SELECT domain, added_at FROM blocked_domains ORDER BY domain ASC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            total = (await db.execute_fetchall("SELECT COUNT(*) FROM blocked_domains"))[0][0]
    return {
        "total":   total,
        "page":    page,
        "limit":   limit,
        "pages":   max(1, -(-total // limit)),
        "domains": [{"domain": r[0], "added_at": r[1]} for r in rows],
    }


@router.post("/blocklist/check")
async def batch_check(body: BatchCheckIn):
    """Return which of the given domains are currently in the blocklist."""
    cleaned = [d.lower().strip().rstrip(".") for d in body.domains if d.strip()]
    if not cleaned:
        return {}
    placeholders = ",".join("?" * len(cleaned))
    async with aiosqlite.connect(BLOCKLIST_DB, timeout=20) as db:
        rows = await db.execute_fetchall(
            f"SELECT domain FROM blocked_domains WHERE domain IN ({placeholders})",
            cleaned,
        )
    blocked_set = {r[0] for r in rows}
    return {d: d in blocked_set for d in cleaned}


@router.post("/blocklist/import")
async def import_blocklist(body: ImportIn):
    """Legacy import endpoint — creates a new feed subscription."""
    return await add_feed(body)


# ── YouTube CDN auto-blocked ──────────────────────────────────────────────────

_YT_RE = re.compile(
    r"^rr?\d+(?:---|\.)sn-[a-z0-9][-a-z0-9]*\.(googlevideo|c\.youtube)\.com$",
    re.IGNORECASE,
)


@router.get("/blocklist/yt-autoblocked")
async def yt_autoblocked():
    global _yt_cache, _yt_cache_ts
    if _yt_cache is not None and time.monotonic() - _yt_cache_ts < _YT_TTL:
        return _yt_cache

    async with aiosqlite.connect(BLOCKLIST_DB, timeout=10) as db:
        rows = await db.execute_fetchall(
            """SELECT domain, added_at FROM blocked_domains
               WHERE domain >= 'r' AND domain < 's'
                 AND (domain LIKE '%.googlevideo.com' OR domain LIKE '%.c.youtube.com')
               ORDER BY added_at DESC LIMIT 200"""
        )
    domains = [{"domain": r[0], "added_at": r[1]} for r in rows if _YT_RE.match(r[0])]
    result  = {"domains": domains, "total": len(domains)}
    _yt_cache    = result
    _yt_cache_ts = time.monotonic()
    return result
