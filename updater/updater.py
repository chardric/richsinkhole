#!/usr/bin/env python3
"""
RichSinkhole Blocklist Updater
Fetches remote blocklists on a schedule and upserts into blocklist.db.
"""

import json
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import schedule
import yaml

SOURCES_PATH           = "/updater/sources.yml"
BLOCKLIST_DB           = "/data/blocklist.db"
SINKHOLE_DB            = "/data/sinkhole.db"
STATUS_PATH            = "/data/updater_status.json"
THREAT_INTEL_STATUS    = "/data/threat_intel_status.json"
FORCE_UPDATE_PATH      = "/data/force_update"
KNOWN_CLIENTS_PATH     = "/data/known_clients.json"
LAST_SUMMARY_PATH      = "/data/last_summary_date.txt"

# Threat intel feeds: (url, format)
# format: "hosts" = standard hosts-file, "threatfox_csv" = ThreatFox CSV export
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
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # Hosts format: "0.0.0.0 domain.com" or "127.0.0.1 domain.com"
        # Plain format: "domain.com"
        candidate = (parts[1] if len(parts) >= 2 else parts[0]).lower().rstrip(".")
        if candidate in _SKIP_HOSTS or candidate in whiteset:
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
    try:
        cfg = load_sources()
    except Exception as exc:
        log.error("Failed to read sources.yml: %s", exc)
        _write_status(0, 0, "config_error")
        return

    urls: list[str] = cfg.get("sources", [])
    whiteset: set[str] = {d.lower() for d in cfg.get("whitelist", [])}

    if not urls:
        log.warning("No source URLs configured")
        _write_status(0, 0, "no_sources")
        return

    all_domains: set[str] = set()
    for url in urls:
        all_domains.update(fetch_domains(url, whiteset))

    if not all_domains:
        log.warning("No domains fetched from any source — skipping DB update")
        _write_status(0, 0, "no_domains")
        return

    try:
        with sqlite3.connect(BLOCKLIST_DB) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bd_domain ON blocked_domains(domain)")
            (count_before,) = conn.execute(
                "SELECT COUNT(*) FROM blocked_domains"
            ).fetchone()

            conn.executemany(
                "INSERT OR IGNORE INTO blocked_domains (domain) VALUES (?)",
                [(d,) for d in all_domains],
            )
            conn.commit()

            (count_after,) = conn.execute(
                "SELECT COUNT(*) FROM blocked_domains"
            ).fetchone()
    except Exception as exc:
        log.error("DB error during update: %s", exc)
        _write_status(0, 0, "db_error")
        return

    added = count_after - count_before
    log.info("=== Update complete: +%d new domains, %d total ===", added, count_after)
    _write_status(added, count_after, "ok")
    notify_blocklist_updated(cfg, added, count_after)
    notify_daily_summary(cfg)


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
    except Exception as exc:
        log.error("Failed to write status file: %s", exc)


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
        with sqlite3.connect(BLOCKLIST_DB) as conn:
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
        with sqlite3.connect(BLOCKLIST_DB) as conn:
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


def main() -> None:
    log.info("RichSinkhole Updater starting up...")

    # Run immediately on startup
    run_update()
    run_threat_intel()
    prune_query_log()

    # Schedule daily at 03:00 Asia/Manila (UTC+8)
    schedule.every().day.at("03:00").do(run_update)
    schedule.every().day.at("03:05").do(prune_query_log)
    # Threat intel refreshes every 6 hours
    schedule.every(6).hours.do(run_threat_intel)
    log.info("Scheduled: blocklist at 03:00, prune at 03:05, threat intel every 6h")

    while True:
        schedule.run_pending()

        # Re-read config each cycle to pick up sources.yml changes
        try:
            cfg = load_sources()
        except Exception:
            cfg = {}

        check_new_clients(cfg)

        force_path = Path(FORCE_UPDATE_PATH)
        if force_path.exists():
            log.info("Force update triggered via /data/force_update")
            force_path.unlink(missing_ok=True)
            schedule.clear()
            run_update()
            schedule.every().day.at("03:00").do(run_update)

        time.sleep(60)


if __name__ == "__main__":
    main()
