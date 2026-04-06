#!/usr/bin/env python3
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
RichSinkhole Blocklist Updater
Fetches remote blocklists on a schedule and upserts into blocklist.db.
"""

import json
import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
import schedule
import yaml

SOURCES_PATH           = "/updater/sources.yml"
BLOCKLIST_DB           = "/local/blocklist.db"
SINKHOLE_DB            = "/local/sinkhole.db"
STATUS_PATH            = "/data/updater_status.json"
THREAT_INTEL_STATUS    = "/data/threat_intel_status.json"
FORCE_UPDATE_PATH      = "/data/force_update"
KNOWN_CLIENTS_PATH     = "/data/known_clients.json"
LAST_SUMMARY_PATH      = "/data/last_summary_date.txt"

# Threat intel feeds: (url, format)
# format: "hosts" = standard hosts-file, "threatfox_csv" = ThreatFox CSV export
_source_failures: dict[str, int] = {}  # url → consecutive failure count

THREAT_INTEL_FEEDS = [
    ("https://urlhaus.abuse.ch/downloads/hostfile/",        "hosts"),
    ("https://threatfox.abuse.ch/export/csv/recent/",       "threatfox_csv"),
]

DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)
_SKIP_HOSTS = {
    "localhost", "localhost.localdomain", "broadcasthost",
    "local", "ip6-localhost", "ip6-loopback",
}

# Parent domains that must NEVER be in the blocklist.
# Any subdomain of these is stripped during blocklist fetch.
# YouTube CDN uses googlevideo.com / c.youtube.com for video delivery —
# blocking them breaks playback. Ad removal is done at the proxy layer.
_ALWAYS_ALLOW_PARENTS = (
    "googlevideo.com",
    "c.youtube.com",
    "youtube-ui.l.google.com",
    "ytimg.com",
    "ggpht.com",
    "gstatic.com",
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("updater")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_sources() -> dict:
    with open(SOURCES_PATH) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Webhook notifications
# ---------------------------------------------------------------------------

def _get_notifications(cfg: dict) -> tuple[str, list]:
    n = cfg.get("notifications", {}) or {}
    return n.get("webhook_url", ""), n.get("events", [])


def _send_webhook(url: str, payload: dict) -> None:
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
        log.info("Webhook delivered: %s", payload.get("event"))
    except Exception as exc:
        log.warning("Webhook failed: %s", exc)


def notify_blocklist_updated(cfg: dict, added: int, total: int) -> None:
    url, events = _get_notifications(cfg)
    if not url or "blocklist_updated" not in events:
        return
    _send_webhook(url, {
        "event": "blocklist_updated",
        "domains_added": added,
        "total_domains": total,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


def notify_daily_summary(cfg: dict) -> None:
    url, events = _get_notifications(cfg)
    if not url or "daily_summary" not in events:
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last = ""
    try:
        last = Path(LAST_SUMMARY_PATH).read_text().strip()
    except FileNotFoundError:
        pass
    if last == today:
        return
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=3) as conn:
            (total,) = conn.execute("SELECT COUNT(*) FROM query_log").fetchone()
            (blocked,) = conn.execute(
                "SELECT COUNT(*) FROM query_log WHERE action='blocked'"
            ).fetchone()
            (clients,) = conn.execute(
                "SELECT COUNT(DISTINCT client_ip) FROM query_log"
            ).fetchone()
    except Exception as exc:
        log.warning("daily_summary DB read failed: %s", exc)
        return
    _send_webhook(url, {
        "event": "daily_summary",
        "date": today,
        "total_queries": total,
        "blocked_queries": blocked,
        "unique_clients": clients,
    })
    Path(LAST_SUMMARY_PATH).write_text(today)


def check_new_clients(cfg: dict) -> None:
    url, events = _get_notifications(cfg)
    if not url or "new_client" not in events:
        return
    try:
        known: set = set(json.loads(Path(KNOWN_CLIENTS_PATH).read_text())) \
            if Path(KNOWN_CLIENTS_PATH).exists() else set()
    except Exception:
        known = set()
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=3) as conn:
            rows = conn.execute("SELECT DISTINCT client_ip FROM query_log").fetchall()
    except Exception as exc:
        log.warning("new_client check failed: %s", exc)
        return
    current = {row[0] for row in rows}
    new_clients = current - known
    for ip in new_clients:
        _send_webhook(url, {"event": "new_client", "client_ip": ip})
    if new_clients or not known:
        Path(KNOWN_CLIENTS_PATH).write_text(json.dumps(list(current)))


# ---------------------------------------------------------------------------
# Fetch & parse
# ---------------------------------------------------------------------------

def fetch_domains(url: str, whiteset: set[str]) -> list[str]:
    """Fetch a hosts file or plain domain list. Returns valid non-whitelisted domains."""
    log.info("Fetching %s", url)
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        log.error("Failed to fetch %s: %s", url, exc)
        return []

    domains: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # AdBlock format: "||domain.com^"
        if line.startswith("||") and line.endswith("^"):
            candidate = line[2:-1].lower().strip()
        else:
            parts = line.split()
            # Hosts format: "0.0.0.0 domain.com" or "127.0.0.1 domain.com"
            # Plain format: "domain.com"
            candidate = (parts[1] if len(parts) >= 2 else parts[0]).lower().rstrip(".")
        if candidate in _SKIP_HOSTS or candidate in whiteset:
            continue
        # Never block subdomains of protected parent domains (e.g. YouTube CDN)
        if any(candidate == p or candidate.endswith("." + p) for p in _ALWAYS_ALLOW_PARENTS):
            continue
        if DOMAIN_RE.match(candidate):
            domains.append(candidate)

    log.info("  -> %d valid domains from %s", len(domains), url)
    return domains


# ---------------------------------------------------------------------------
# DB update
# ---------------------------------------------------------------------------

def run_update() -> None:
    log.info("=== Blocklist update starting ===")
    t_start = time.monotonic()
    try:
        cfg = load_sources()
    except Exception as exc:
        log.error("Failed to read sources.yml: %s", exc)
        _write_status(0, 0, "config_error")
        return

    from default_sources import DEFAULT_SOURCES
    user_urls: list[str] = cfg.get("sources", [])
    # Merge default + user sources, dedup, defaults first
    seen = set()
    urls = []
    for u in DEFAULT_SOURCES + user_urls:
        key = u.strip().lower()
        if key not in seen:
            seen.add(key)
            urls.append(u)
    whiteset: set[str] = {d.lower() for d in cfg.get("whitelist", [])}

    _write_progress("preparing", f"{len(urls)} sources", 0)

    # Skip sources that have failed 3+ consecutive times
    urls = [u for u in urls if _source_failures.get(u, 0) < 3]

    # Skip sources disabled in DB (stale 90+ days or manually disabled)
    try:
        with sqlite3.connect(BLOCKLIST_DB, timeout=5) as conn:
            disabled = {r[0] for r in conn.execute(
                "SELECT url FROM blocklist_feeds WHERE enabled=0"
            ).fetchall()}
        if disabled:
            before = len(urls)
            urls = [u for u in urls if u not in disabled]
            if len(urls) < before:
                log.info("Skipped %d disabled source(s)", before - len(urls))
    except Exception:
        pass

    if not urls:
        log.warning("No source URLs configured")
        _write_status(0, 0, "no_sources")
        return

    # ── Phase 1: Parallel fetch ──────────────────────────────────────────
    per_url: dict[str, list[str]] = {}
    all_domains: set[str] = set()

    def _fetch_one(url: str) -> tuple[str, list[str]]:
        return url, fetch_domains(url, whiteset)

    fetched_count = 0
    total_sources = len(urls)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_one, u): u for u in urls}
        for future in as_completed(futures):
            fetched_count += 1
            pct = int(fetched_count / total_sources * 50)  # fetch = 0-50%
            try:
                url, domains = future.result()
                per_url[url] = domains
                all_domains.update(domains)
                _source_failures.pop(url, None)  # reset on success
                _write_progress("fetching", f"{fetched_count}/{total_sources} sources ({len(all_domains):,} domains)", pct)
            except Exception as exc:
                log.error("Fetch failed for %s: %s", futures[future], exc)
                _source_failures[url] = _source_failures.get(url, 0) + 1
                if _source_failures[url] >= 3:
                    log.warning("Source disabled after 3 failures: %s", url)
                _write_progress("fetching", f"{fetched_count}/{total_sources} sources", pct)

    t_fetch = time.monotonic()
    log.info("Fetched %d unique domains from %d sources in %.1fs",
             len(all_domains), len(urls), t_fetch - t_start)

    if not all_domains:
        log.warning("No domains fetched from any source — skipping DB update")
        _write_status(0, 0, "no_domains")
        return

    _write_progress("building", f"Writing {len(all_domains):,} domains to DB", 55)

    # ── Phase 2: Table-swap (Pi-hole gravity style) ──────────────────────
    # Build new table without index → bulk insert → add index → swap.
    # This avoids 2.2M INSERT OR IGNORE against an indexed table.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        with sqlite3.connect(BLOCKLIST_DB, timeout=120) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

            # Ensure schema for feeds table
            conn.execute("""
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

            (count_before,) = conn.execute(
                "SELECT COUNT(*) FROM blocked_domains"
            ).fetchone()

            # Preserve custom/feed/threat_intel domains (user-added, not from sources.yml)
            custom_rows = conn.execute(
                "SELECT domain, source, added_at FROM blocked_domains WHERE source IS NOT NULL AND source != 'blocklist'"
            ).fetchall()

            log.info("DB swap: creating new table, inserting %d domains...", len(all_domains))
            t_db = time.monotonic()

            # Build new table with NO indexes/constraints — pure sequential writes
            conn.execute("DROP TABLE IF EXISTS blocked_domains_new")
            conn.execute("""
                CREATE TABLE blocked_domains_new (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain   TEXT NOT NULL,
                    source   TEXT,
                    added_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # Bulk insert in chunks to avoid massive WAL growth
            # all_domains is already a set — no duplicates
            domain_list = list(all_domains)
            CHUNK = 50_000
            for i in range(0, len(domain_list), CHUNK):
                chunk = [(d,) for d in domain_list[i:i + CHUNK]]
                conn.executemany(
                    "INSERT INTO blocked_domains_new (domain, source) VALUES (?, 'blocklist')",
                    chunk,
                )
                if (i + CHUNK) % 200_000 == 0 or i + CHUNK >= len(domain_list):
                    log.info("DB swap: inserted %d / %d domains (%.1fs)",
                             min(i + CHUNK, len(domain_list)), len(domain_list),
                             time.monotonic() - t_db)

            _write_progress("indexing", "Building indexes", 80)
            log.info("DB swap: building indexes...")
            # Add unique index on fully populated table (single sort pass)
            conn.execute("DROP INDEX IF EXISTS idx_bdn_domain")
            conn.execute("CREATE UNIQUE INDEX idx_bdn_domain ON blocked_domains_new(domain)")

            # Re-insert preserved custom/feed/threat_intel domains (few rows, index exists)
            if custom_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO blocked_domains_new (domain, source, added_at) VALUES (?, ?, ?)",
                    custom_rows,
                )

            conn.execute("DROP INDEX IF EXISTS idx_bdn_source")
            conn.execute("CREATE INDEX idx_bdn_source ON blocked_domains_new(source)")

            _write_progress("swapping", "Swapping tables", 90)
            log.info("DB swap: renaming tables...")
            # Atomic swap
            conn.execute("DROP TABLE IF EXISTS blocked_domains_old")
            conn.execute("ALTER TABLE blocked_domains RENAME TO blocked_domains_old")
            conn.execute("ALTER TABLE blocked_domains_new RENAME TO blocked_domains")
            conn.execute("DROP TABLE IF EXISTS blocked_domains_old")
            conn.commit()
            # Restore normal sync after bulk work is committed
            conn.execute("PRAGMA synchronous=NORMAL")

            (count_after,) = conn.execute(
                "SELECT COUNT(*) FROM blocked_domains"
            ).fetchone()

            # Update blocklist_feeds metadata for each source URL
            # Add last_changed column if missing (tracks when domain_count changed)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(blocklist_feeds)")}
            if "last_changed" not in cols:
                conn.execute("ALTER TABLE blocklist_feeds ADD COLUMN last_changed TEXT")

            for url, domains in per_url.items():
                count = len(domains)
                existing = conn.execute(
                    "SELECT domain_count FROM blocklist_feeds WHERE url=?", (url,)
                ).fetchone()
                changed = (existing is None or existing[0] != count)
                conn.execute("""
                    INSERT INTO blocklist_feeds (url, domain_count, last_synced, enabled, is_builtin, last_changed)
                    VALUES (?, ?, ?, 1, 1, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        domain_count = excluded.domain_count,
                        last_synced  = excluded.last_synced,
                        is_builtin   = 1,
                        last_changed = CASE WHEN excluded.last_changed IS NOT NULL
                                            THEN excluded.last_changed
                                            ELSE blocklist_feeds.last_changed END
                """, (url, count, now, now if changed else None))

            # Auto-disable sources stale for N+ days (content unchanged)
            stale_days = int(cfg.get("source_stale_days", 90))
            stale = conn.execute("""
                SELECT url FROM blocklist_feeds
                WHERE last_changed IS NOT NULL
                  AND last_changed < datetime('now', ? || ' days')
                  AND enabled = 1
            """, (f"-{stale_days}",)).fetchall()
            for (stale_url,) in stale:
                conn.execute("UPDATE blocklist_feeds SET enabled=0 WHERE url=?", (stale_url,))
                log.warning("Auto-disabled stale source (unchanged 90+ days): %s", stale_url)

            conn.commit()

    except Exception as exc:
        log.error("DB error during update: %s", exc)
        # Clean up any half-built swap table/indexes so next run starts fresh
        try:
            with sqlite3.connect(BLOCKLIST_DB) as conn:
                conn.execute("DROP INDEX IF EXISTS idx_bdn_domain")
                conn.execute("DROP INDEX IF EXISTS idx_bdn_source")
                conn.execute("DROP TABLE IF EXISTS blocked_domains_new")
                conn.commit()
        except Exception:
            pass
        _write_status(0, 0, "db_error")
        return

    t_db = time.monotonic()
    added = count_after - count_before
    log.info("=== Update complete: %d total (fetch %.1fs, DB swap %.1fs, total %.1fs) ===",
             count_after, t_fetch - t_start, t_db - t_fetch, t_db - t_start)
    _write_status(added, count_after, "ok")
    notify_blocklist_updated(cfg, added, count_after)
    notify_daily_summary(cfg)


PROGRESS_PATH = "/data/updater_progress.json"


def _write_status(added: int, total: int, status: str) -> None:
    data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "domains_added": added,
        "total_domains": total,
        "status": status,
    }
    try:
        with open(STATUS_PATH, "w") as f:
            json.dump(data, f)
        # Clear progress when done
        with open(PROGRESS_PATH, "w") as f:
            json.dump({"running": False}, f)
    except Exception as exc:
        log.error("Failed to write status file: %s", exc)


def _write_progress(stage: str, detail: str = "", pct: int = 0) -> None:
    try:
        with open(PROGRESS_PATH, "w") as f:
            json.dump({"running": True, "stage": stage, "detail": detail, "pct": pct}, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def fetch_threatfox_domains(url: str) -> list[str]:
    """Parse ThreatFox CSV export — extract domain-type IOCs only."""
    log.info("Fetching (ThreatFox CSV) %s", url)
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError as exc:
        log.error("Failed to fetch ThreatFox: %s", exc)
        return []

    import csv, io
    domains: list[str] = []
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].startswith("#"):
            continue
        # CSV columns: date, id, ioc, ioc_type, ...
        if len(row) < 4:
            continue
        ioc      = row[2].strip().strip('"')
        ioc_type = row[3].strip().strip('"')
        if ioc_type != "domain":
            continue
        candidate = ioc.lower().rstrip(".")
        if candidate not in _SKIP_HOSTS and DOMAIN_RE.match(candidate):
            domains.append(candidate)

    log.info("  -> %d valid domains from ThreatFox", len(domains))
    return domains


def _migrate_blocklist_source_col() -> None:
    """Add source column to blocked_domains if upgrading from older schema."""
    try:
        with sqlite3.connect(BLOCKLIST_DB, timeout=120) as conn:
            conn.execute("ALTER TABLE blocked_domains ADD COLUMN source TEXT DEFAULT 'blocklist'")
            conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def run_threat_intel() -> None:
    """Fetch threat intel feeds and insert into blocklist.db with source='threat_intel'."""
    log.info("=== Threat intel update starting ===")
    _migrate_blocklist_source_col()

    all_domains: set[str] = set()
    for url, fmt in THREAT_INTEL_FEEDS:
        if fmt == "threatfox_csv":
            domains = fetch_threatfox_domains(url)
        else:
            domains = fetch_domains(url, set())
        all_domains.update(domains)
        log.info("Threat intel: %d domains from %s", len(domains), url)

    if not all_domains:
        log.warning("Threat intel: no domains fetched — skipping")
        _write_threat_intel_status(0, 0, "no_domains")
        return

    try:
        with sqlite3.connect(BLOCKLIST_DB, timeout=120) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            (before,) = conn.execute(
                "SELECT COUNT(*) FROM blocked_domains WHERE source='threat_intel'"
            ).fetchone()
            conn.executemany(
                """INSERT INTO blocked_domains (domain, source)
                   VALUES (?, 'threat_intel')
                   ON CONFLICT(domain) DO UPDATE SET source='threat_intel'""",
                [(d,) for d in all_domains],
            )
            conn.commit()
            (after,) = conn.execute(
                "SELECT COUNT(*) FROM blocked_domains WHERE source='threat_intel'"
            ).fetchone()
    except Exception as exc:
        log.error("Threat intel DB error: %s", exc)
        _write_threat_intel_status(0, 0, "db_error")
        return

    added = after - before
    log.info("=== Threat intel done: +%d new, %d total threat domains ===", added, after)
    _write_threat_intel_status(added, after, "ok")


def _write_threat_intel_status(added: int, total: int, status: str) -> None:
    data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "domains_added": added,
        "total_domains": total,
        "status": status,
        "feeds": [url for url, _ in THREAT_INTEL_FEEDS],
    }
    try:
        with open(THREAT_INTEL_STATUS, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        log.error("Failed to write threat intel status: %s", exc)



def prune_query_log(retain_days: int = 30) -> None:
    """Delete query log entries older than retain_days and reclaim disk space."""
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=10) as conn:
            result = conn.execute(
                "DELETE FROM query_log WHERE ts < datetime('now', ?)",
                (f"-{retain_days} days",),
            )
            deleted = result.rowcount
            conn.commit()
        if deleted:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                conn.execute("VACUUM")
            log.info("Query log pruned: %d rows deleted (retain %d days)", deleted, retain_days)
        else:
            log.info("Query log prune: nothing to delete (retain %d days)", retain_days)
    except Exception as exc:
        log.error("Query log prune failed: %s", exc)


_CONFIG_PATH = "/config/config.yml"

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Snapshot of active schedule settings — used to detect changes
_ScheduleKey = tuple  # (hour, minute, frequency, day_of_week, day_of_month)


def _read_update_schedule() -> _ScheduleKey:
    """Return schedule tuple from config.yml, falling back to defaults."""
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        h   = max(0, min(23, int(cfg.get("update_hour",         3))))
        m   = max(0, min(59, int(cfg.get("update_minute",       0))))
        frq = cfg.get("update_frequency", "daily")
        if frq not in ("daily", "weekly", "monthly"):
            frq = "daily"
        dow = max(0, min(6,  int(cfg.get("update_day_of_week",  0))))
        dom = max(1, min(28, int(cfg.get("update_day_of_month", 1))))
        return h, m, frq, dow, dom
    except Exception:
        return 3, 0, "daily", 0, 1


def _set_update_schedule(key: _ScheduleKey) -> None:
    """Clear and re-register blocklist + prune jobs for the given schedule."""
    hour, minute, frequency, day_of_week, day_of_month = key
    schedule.clear("blocklist")
    schedule.clear("prune")

    time_str = f"{hour:02d}:{minute:02d}"

    if frequency == "weekly":
        getattr(schedule.every(), _DAYS[day_of_week]).at(time_str).do(run_update).tag("blocklist")
        log.info("Schedule: blocklist every %s at %s", _DAYS[day_of_week], time_str)

    elif frequency == "monthly":
        # schedule lib has no native monthly support — check day-of-month inside a daily job
        def _monthly_check(dom=day_of_month):
            from datetime import date as _date
            if _date.today().day == dom:
                run_update()
        schedule.every().day.at(time_str).do(_monthly_check).tag("blocklist")
        log.info("Schedule: blocklist monthly on day %d at %s", day_of_month, time_str)

    else:  # daily
        schedule.every().day.at(time_str).do(run_update).tag("blocklist")
        log.info("Schedule: blocklist daily at %s", time_str)

    # Prune always runs daily, 5 min after the configured time
    prune_minute = (minute + 5) % 60
    prune_hour   = hour if minute + 5 < 60 else (hour + 1) % 24
    prune_str    = f"{prune_hour:02d}:{prune_minute:02d}"
    schedule.every().day.at(prune_str).do(prune_query_log).tag("prune")
    log.info("Schedule: prune daily at %s", prune_str)


def _blocklist_stale(max_age_hours: int = 23) -> bool:
    """Return True if blocklist hasn't been updated within max_age_hours."""
    try:
        with open(STATUS_PATH) as f:
            status = json.load(f)
        last = status.get("last_updated", "")
        if not last or status.get("status") != "ok":
            return True
        from datetime import datetime as _dt
        updated = _dt.strptime(last, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
        log.info("Blocklist age: %.1fh (stale threshold: %dh)", age_h, max_age_hours)
        return age_h >= max_age_hours
    except Exception:
        return True


def start_updater_sync() -> None:
    """Blocking loop that runs the updater forever.

    Designed to be called via ``asyncio.to_thread(start_updater_sync)``
    from the unified sinkhole entrypoint, or directly in standalone mode.
    """
    log.info("RichSinkhole Updater starting up...")

    # Only run on startup if blocklist is stale (>23h old)
    # Avoids 2-3 min DB lock on every container restart
    if _blocklist_stale():
        run_update()
        run_threat_intel()
    else:
        log.info("Blocklist is fresh — skipping startup update")
    prune_query_log()

    # Load initial schedule from config
    cur_key = _read_update_schedule()
    _set_update_schedule(cur_key)

    # Threat intel refreshes every 6 hours (fixed — not user-configurable)
    schedule.every(6).hours.do(run_threat_intel)

    while True:
        schedule.run_pending()

        # Re-read config each cycle to pick up sources.yml and schedule changes
        try:
            cfg = load_sources()
        except Exception:
            cfg = {}

        check_new_clients(cfg)

        # Detect and apply schedule changes without restarting
        new_key = _read_update_schedule()
        if new_key != cur_key:
            log.info("Update schedule changed — rescheduling")
            cur_key = new_key
            _set_update_schedule(cur_key)

        force_path = Path(FORCE_UPDATE_PATH)
        if force_path.exists():
            log.info("Force update triggered via /data/force_update")
            force_path.unlink(missing_ok=True)
            run_update()
            _set_update_schedule(cur_key)

        time.sleep(60)


def main() -> None:
    start_updater_sync()


if __name__ == "__main__":
    main()
