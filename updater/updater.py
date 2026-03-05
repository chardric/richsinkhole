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

SOURCES_PATH = "/updater/sources.yml"
BLOCKLIST_DB = "/data/blocklist.db"
SINKHOLE_DB = "/data/sinkhole.db"
STATUS_PATH = "/data/updater_status.json"
FORCE_UPDATE_PATH = "/data/force_update"
KNOWN_CLIENTS_PATH = "/data/known_clients.json"
LAST_SUMMARY_PATH = "/data/last_summary_date.txt"

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

def main() -> None:
    log.info("RichSinkhole Updater starting up...")

    # Run immediately on startup
    run_update()

    # Schedule daily at 03:00 Asia/Manila (UTC+8)
    schedule.every().day.at("03:00").do(run_update)
    log.info("Scheduled: daily blocklist update at 03:00 Asia/Manila")

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
