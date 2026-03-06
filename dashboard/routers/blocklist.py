import re
import time

import aiosqlite
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

BLOCKLIST_DB = "/data/blocklist.db"

# RFC-compliant domain label validation (no leading/trailing hyphens)
DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)

router = APIRouter()

_yt_cache: dict | None = None
_yt_cache_ts: float = 0.0
_YT_TTL = 300.0  # 5 minutes — YT CDN nodes only change on updater runs


def _validate(domain: str) -> str:
    domain = domain.lower().strip().rstrip(".")
    if not domain or not DOMAIN_RE.match(domain):
        raise HTTPException(status_code=400, detail=f"Invalid domain: {domain!r}")
    return domain


class DomainIn(BaseModel):
    domain: str


class ImportIn(BaseModel):
    url: str


@router.get("/blocklist")
async def list_blocklist(page: int = 1, limit: int = 100, search: str = ""):
    page = max(1, page)
    limit = min(max(1, limit), 500)
    offset = (page - 1) * limit
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
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
            total = (await db.execute_fetchall(
                "SELECT COUNT(*) FROM blocked_domains"
            ))[0][0]
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, -(-total // limit)),
        "domains": [{"domain": r[0], "added_at": r[1]} for r in rows],
    }


@router.post("/blocklist", status_code=201)
async def add_domain(body: DomainIn):
    domain = _validate(body.domain)
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        existing = await db.execute_fetchall(
            "SELECT 1 FROM blocked_domains WHERE domain = ?", (domain,)
        )
        if existing:
            raise HTTPException(status_code=409, detail="Domain already blocked")
        await db.execute("INSERT INTO blocked_domains (domain) VALUES (?)", (domain,))
        await db.commit()
    return {"domain": domain, "status": "added"}


@router.delete("/blocklist/{domain:path}")
async def remove_domain(domain: str):
    domain = _validate(domain)
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        cur = await db.execute(
            "DELETE FROM blocked_domains WHERE domain = ?", (domain,)
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Domain not found")
    return {"domain": domain, "status": "removed"}


class BatchCheckIn(BaseModel):
    domains: list[str]


@router.post("/blocklist/check")
async def batch_check(body: BatchCheckIn):
    """Return which of the given domains are currently in the blocklist."""
    cleaned = [d.lower().strip().rstrip(".") for d in body.domains if d.strip()]
    if not cleaned:
        return {}
    placeholders = ",".join("?" * len(cleaned))
    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        rows = await db.execute_fetchall(
            f"SELECT domain FROM blocked_domains WHERE domain IN ({placeholders})",
            cleaned,
        )
    blocked_set = {r[0] for r in rows}
    return {d: d in blocked_set for d in cleaned}


@router.post("/blocklist/import")
async def import_blocklist(body: ImportIn):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {exc}")

    # Parse hosts file format (0.0.0.0 domain or 127.0.0.1 domain) and plain lists
    _SKIP = {"localhost", "localhost.localdomain", "broadcasthost", "local", "ip6-localhost"}
    domains: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        candidate = (parts[1] if len(parts) >= 2 else parts[0]).lower().rstrip(".")
        if candidate in _SKIP:
            continue
        if DOMAIN_RE.match(candidate):
            domains.append(candidate)

    if not domains:
        raise HTTPException(status_code=422, detail="No valid domains found in the provided content")

    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        await db.executemany(
            "INSERT OR IGNORE INTO blocked_domains (domain) VALUES (?)",
            [(d,) for d in domains],
        )
        await db.commit()

    return {"imported": len(domains), "status": "ok"}


_YT_RE = re.compile(
    r"^rr?\d+(?:---|\.)sn-[a-z0-9][-a-z0-9]*\.(googlevideo|c\.youtube)\.com$",
    re.IGNORECASE,
)


@router.get("/blocklist/yt-autoblocked")
async def yt_autoblocked():
    """Show YouTube CDN nodes auto-blocked by the sinkhole (googlevideo.com + c.youtube.com)."""
    global _yt_cache, _yt_cache_ts
    if _yt_cache is not None and time.monotonic() - _yt_cache_ts < _YT_TTL:
        return _yt_cache

    async with aiosqlite.connect(BLOCKLIST_DB, timeout=10) as db:
        # YT CDN nodes all start with 'r' — narrow the index range scan before LIKE
        rows = await db.execute_fetchall(
            """SELECT domain, added_at FROM blocked_domains
               WHERE domain >= 'r' AND domain < 's'
                 AND (domain LIKE '%.googlevideo.com' OR domain LIKE '%.c.youtube.com')
               ORDER BY added_at DESC LIMIT 200"""
        )
    domains = [{"domain": r[0], "added_at": r[1]} for r in rows if _YT_RE.match(r[0])]
    result = {"domains": domains, "total": len(domains)}
    _yt_cache = result
    _yt_cache_ts = time.monotonic()
    return result
