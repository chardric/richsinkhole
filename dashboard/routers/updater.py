import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

STATUS_PATH = "/data/updater_status.json"
FORCE_UPDATE_PATH = "/data/force_update"
SOURCES_PATH = "/updater/sources.yml"

router = APIRouter()

_DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)
_SKIP_HOSTS = {
    "localhost", "localhost.localdomain", "broadcasthost",
    "local", "ip6-localhost", "ip6-loopback",
}


@router.get("/updater/status")
async def get_updater_status():
    path = Path(STATUS_PATH)
    if not path.exists():
        return {
            "status": "never_run",
            "last_updated": None,
            "domains_added": 0,
            "total_domains": 0,
        }
    with open(path) as f:
        return json.load(f)


@router.get("/updater/sources")
async def get_sources():
    try:
        with open(SOURCES_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="sources.yml not available")


class SourcesIn(BaseModel):
    sources: list[str]
    whitelist: list[str] = []
    update_interval_hours: int = 24


class ValidateIn(BaseModel):
    url: str


def _normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def _load_sources_safe() -> dict:
    try:
        with open(SOURCES_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _count_domains(text: str) -> int:
    count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        candidate = (parts[1] if len(parts) >= 2 else parts[0]).lower().rstrip(".")
        if candidate in _SKIP_HOSTS:
            continue
        if _DOMAIN_RE.match(candidate):
            count += 1
    return count


@router.post("/updater/sources/validate")
async def validate_source(body: ValidateIn):
    url = body.url.strip()

    # 1. URL format: must parse to a valid http(s) URL with a real hostname
    try:
        parsed = urlparse(url)
    except Exception:
        return {"valid": False, "error": "Invalid URL format"}

    if parsed.scheme not in ("http", "https"):
        return {"valid": False, "error": "URL must start with http:// or https://"}

    host = parsed.hostname or ""
    if not host or "." not in host:
        return {"valid": False, "error": "URL must contain a valid hostname (e.g. example.com)"}

    # 2. Duplicate check (normalized: lowercase + strip trailing slash)
    existing = _load_sources_safe()
    norm = _normalize_url(url)
    for s in existing.get("sources", []):
        if _normalize_url(s) == norm:
            return {"valid": False, "error": "This source is already in the list"}

    # 3. Reachability — fetch the URL
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "RichSinkhole/1.0"})
    except httpx.TimeoutException:
        return {"valid": False, "error": "Connection timed out (>20s)"}
    except httpx.ConnectError as exc:
        return {"valid": False, "error": f"Could not connect: {exc}"}
    except Exception as exc:
        return {"valid": False, "error": f"Request failed: {exc}"}

    if resp.status_code >= 400:
        return {"valid": False, "error": f"Server returned HTTP {resp.status_code}"}

    # 4. Content-type check — must be some kind of text
    ctype = resp.headers.get("content-type", "")
    if ctype and not any(t in ctype for t in ("text/", "application/octet-stream", "application/x-")):
        short = ctype.split(";")[0].strip()
        return {"valid": False, "error": f"Unexpected content type: {short} — expected a plain-text blocklist"}

    # 5. Size bounds
    content = resp.text
    if len(content) < 50:
        return {"valid": False, "error": "Response too small to be a valid blocklist (< 50 bytes)"}
    if len(content) > 52_428_800:  # 50 MB
        return {"valid": False, "error": "File too large (> 50 MB) — refusing to add"}

    # 6. Domain count — must look like an actual blocklist
    count = _count_domains(content)
    if count < 10:
        return {"valid": False, "error": f"Only {count} valid domain(s) found — does not look like a blocklist"}

    return {"valid": True, "domains_found": count}


@router.post("/updater/sources")
async def save_sources(body: SourcesIn):
    for url in body.sources:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail=f"Invalid URL: {url!r}")

    # Deduplicate while preserving order (normalized comparison)
    seen: set[str] = set()
    deduped: list[str] = []
    for url in body.sources:
        key = _normalize_url(url)
        if key not in seen:
            seen.add(key)
            deduped.append(url)

    data = {
        "sources": deduped,
        "whitelist": body.whitelist,
        "update_interval_hours": body.update_interval_hours,
    }
    with open(SOURCES_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    return {"status": "saved"}


@router.post("/updater/run")
async def trigger_update():
    Path(FORCE_UPDATE_PATH).touch()
    return {"status": "triggered"}
