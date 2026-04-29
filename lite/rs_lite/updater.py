# One-shot blocklist refresh for the Lite variant.
# Reads sources.yml, fetches each feed, parses (hosts/threatfox CSV),
# applies user allowlist + service-bundle blocks, writes a dnsmasq
# 0.0.0.0 hosts file, and reloads dnsmasq.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

from __future__ import annotations

import csv
import io
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from . import config, db
from . import services_data

log = logging.getLogger("rs_lite.updater")


# ---------------------------------------------------------------------------
# Constants borrowed from updater/updater.py to keep parsing identical.
# ---------------------------------------------------------------------------

DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)

_SKIP_HOSTS = {
    "localhost", "localhost.localdomain", "broadcasthost",
    "local", "ip6-localhost", "ip6-loopback",
}

_ALWAYS_ALLOW_PARENTS = (
    "googlevideo.com",
    "c.youtube.com",
    "youtube-ui.l.google.com",
    "ytimg.com",
    "ggpht.com",
    "gstatic.com",
)

# Default sources used when sources.yml does not list any.
DEFAULT_SOURCES: list[tuple[str, str]] = [
    ("https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts", "hosts"),
    ("https://adaway.org/hosts.txt",                                       "hosts"),
    ("https://raw.githubusercontent.com/anudeepND/blacklist/master/adservers.txt", "hosts"),
    ("https://curbengh.github.io/phishing-filter/phishing-filter-hosts.txt", "hosts"),
    ("https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/fake.txt", "hosts"),
    ("https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/popupads.txt", "hosts"),
]


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------

def _http_get(url: str) -> str:
    resp = requests.get(url, timeout=config.HTTP_TIMEOUT_SECS, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_hosts(url: str, allow: set[str]) -> list[str]:
    """Hosts-file or plain-domain list. Returns valid non-allowed domains."""
    log.info("Fetching %s", url)
    try:
        text = _http_get(url)
    except requests.RequestException as exc:
        log.error("Failed to fetch %s: %s", url, exc)
        return []

    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if line.startswith("||") and line.endswith("^"):
            candidate = line[2:-1].lower().strip()
        else:
            parts = line.split()
            candidate = (parts[1] if len(parts) >= 2 else parts[0]).lower().rstrip(".")
        if candidate in _SKIP_HOSTS or candidate in allow:
            continue
        if any(candidate == p or candidate.endswith("." + p) for p in _ALWAYS_ALLOW_PARENTS):
            continue
        if DOMAIN_RE.match(candidate):
            out.append(candidate)
            if len(out) >= config.MAX_DOMAINS_PER_FEED:
                log.warning("Truncating %s at %d domains", url, len(out))
                break

    log.info("  -> %d domains from %s", len(out), url)
    return out


def fetch_threatfox(url: str, allow: set[str]) -> list[str]:
    log.info("Fetching ThreatFox CSV %s", url)
    try:
        text = _http_get(url)
    except requests.RequestException as exc:
        log.error("Failed to fetch ThreatFox: %s", exc)
        return []

    out: list[str] = []
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].startswith("#") or len(row) < 4:
            continue
        ioc      = row[2].strip().strip('"').lower().rstrip(".")
        ioc_type = row[3].strip().strip('"')
        if ioc_type != "domain":
            continue
        if ioc in allow or ioc in _SKIP_HOSTS:
            continue
        if any(ioc == p or ioc.endswith("." + p) for p in _ALWAYS_ALLOW_PARENTS):
            continue
        if DOMAIN_RE.match(ioc):
            out.append(ioc)
    log.info("  -> %d domains from ThreatFox", len(out))
    return out


# ---------------------------------------------------------------------------
# Service-bundle blocks
# ---------------------------------------------------------------------------

def service_bundle_domains(allow: set[str]) -> list[str]:
    """Domains from services the user has flipped on for blocking."""
    blocked_ids = db.blocked_service_ids()
    if not blocked_ids:
        return []
    by_id = {s["id"]: s for s in services_data.SERVICES}
    out: list[str] = []
    for sid in blocked_ids:
        svc = by_id.get(sid)
        if not svc:
            continue
        for d in svc.get("domains", []):
            d = d.lower().strip().rstrip(".")
            if d and d not in allow and DOMAIN_RE.match(d):
                out.append(d)
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_hosts_file(domains: set[str]) -> int:
    """Atomic write of /var/lib/rs-lite/blocked.hosts.

    File is left mode 0644 so dnsmasq (running as user `dnsmasq`) can read it.
    """
    target = config.BLOCKED_HOSTS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".blocked.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write("# rs-lite blocked.hosts — generated %s\n" %
                    datetime.now(timezone.utc).isoformat(timespec="seconds"))
            f.write("# %d domains\n" % len(domains))
            for d in sorted(domains):
                f.write(f"0.0.0.0 {d}\n")
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return len(domains)


def reload_dnsmasq() -> bool:
    try:
        subprocess.run(
            config.DNSMASQ_RELOAD_CMD,
            check=True, capture_output=True, timeout=20,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("dnsmasq reload failed (continuing): %s", exc)
        return False


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def load_sources_yml() -> dict:
    p = config.SOURCES_YML
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        log.error("sources.yml parse error: %s", exc)
        return {}


def resolve_sources(cfg: dict) -> list[tuple[str, str]]:
    """Merge default + user sources into [(url, format), ...]."""
    user_raw = cfg.get("sources") or []
    user: list[tuple[str, str]] = []
    for item in user_raw:
        if isinstance(item, str):
            user.append((item, "hosts"))
        elif isinstance(item, dict) and "url" in item:
            user.append((item["url"], item.get("format", "hosts")))
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for url, fmt in DEFAULT_SOURCES + user:
        key = url.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append((url, fmt))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_once() -> dict:
    t0 = time.monotonic()
    cfg = load_sources_yml()
    allow_user = {a["domain"] for a in db.list_allowlist()}
    allow_yml  = {d.lower() for d in cfg.get("whitelist", []) or []}
    allow = allow_user | allow_yml

    sources = resolve_sources(cfg)
    log.info("Refreshing from %d sources (allow-list: %d)", len(sources), len(allow))

    aggregate: set[str] = set()
    feeds_ok = 0
    for url, fmt in sources:
        if fmt == "threatfox_csv":
            domains = fetch_threatfox(url, allow)
        else:
            domains = fetch_hosts(url, allow)
        if domains:
            feeds_ok += 1
            aggregate.update(domains)

    bundle = service_bundle_domains(allow)
    if bundle:
        log.info("Service-bundle adds %d domains", len(bundle))
        aggregate.update(bundle)

    # Final allow-pass — defensively strip in case allow added items late.
    aggregate.difference_update(allow)
    written = write_hosts_file(aggregate)
    reload_ok = reload_dnsmasq()

    elapsed = round(time.monotonic() - t0, 1)
    db.set_setting("last_refresh_at",   datetime.now(timezone.utc).isoformat(timespec="seconds"))
    db.set_setting("last_refresh_count", str(written))
    db.set_setting("last_refresh_feeds", f"{feeds_ok}/{len(sources)}")
    db.set_setting("last_refresh_secs",  str(elapsed))
    log.info("Done: %d domains, %d/%d feeds ok, %.1fs, dnsmasq reload=%s",
             written, feeds_ok, len(sources), elapsed, reload_ok)
    return {
        "domains":   written,
        "feeds_ok":  feeds_ok,
        "feeds_all": len(sources),
        "elapsed_s": elapsed,
        "reload_ok": reload_ok,
    }


def _main() -> int:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
    )
    db.init_db()
    try:
        run_once()
        return 0
    except Exception:
        log.exception("Refresh failed")
        return 1


if __name__ == "__main__":
    sys.exit(_main())
