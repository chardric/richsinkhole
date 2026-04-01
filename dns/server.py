#!/usr/bin/env python3
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
RichSinkhole DNS Server
UDP/TCP DNS server with blocklist enforcement and SQLite query logging.
"""

import ipaddress
import logging
import math
import os
import re
import shutil
import socket
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from collections import Counter, OrderedDict

import yaml
from dnslib import RR, QTYPE, A
from dnslib.server import DNSServer, BaseResolver, DNSLogger as DnsLibLogger

import blocker

# Well-known captive portal detection domains for iOS, Android, Windows, macOS, Linux
CAPTIVE_PORTAL_DOMAINS = {
    "captive.apple.com",
    # www.apple.com is intentionally excluded — iOS uses it for HTTPS services
    # (App Store, iCloud, Apple Pay). Redirecting it causes TLS mismatch errors
    # and breaks all Apple services, making the device report "no internet".
    # Firefox: detectportal.firefox.com is intentionally excluded —
    # intercepting it causes a persistent "Open network login page" banner.
    # Let Firefox reach Mozilla directly for its captive check.
    "connectivitycheck.gstatic.com",
    "connectivitycheck.android.com",
    "clients3.google.com",
    # Windows NCSI domains excluded — intercepting them causes a persistent
    # "No Internet" status in Windows taskbar. Let them resolve normally.
    "nmcheck.gnome.org",
    "nmcheck.fedoraproject.org",
}

CONFIG_PATH = "/config/config.yml"
CONFIG_DEFAULT = "/dns/config.yml"
SINKHOLE_DB = "/data/sinkhole.db"
BLOCKLIST_DB = "/data/blocklist.db"
DEFAULT_BLOCKLIST = "/dns/blocklists/default.txt"


# ---------------------------------------------------------------------------
# DNS response cache  (LRU, TTL-respecting, thread-safe)
# ---------------------------------------------------------------------------

_CACHE_MAX = 15000
_CACHE_MIN_TTL = 300   # enforce minimum 5-minute cache for all DNS responses
_dns_cache: OrderedDict = OrderedDict()   # (domain, qtype) → (packed_bytes, expiry, upstream)
_cache_lock = threading.Lock()


def _cache_get(domain: str, qtype: int, request_id: int):
    """Return (reply, upstream_str) from cache, or None on miss/expiry."""
    key = (domain, qtype)
    with _cache_lock:
        entry = _dns_cache.get(key)
        if entry is None:
            return None
        packed, expiry, upstream = entry
        if time.monotonic() > expiry:
            del _dns_cache[key]
            return None
        # Move to end (LRU: recently used stays)
        _dns_cache.move_to_end(key)
    from dnslib import DNSRecord
    reply = DNSRecord.parse(packed)
    reply.header.id = request_id
    return reply, upstream


def _cache_put(domain: str, qtype: int, reply, upstream: str) -> None:
    """Cache a successful reply. Enforces a minimum TTL to reduce upstream queries."""
    if not reply.rr:
        return
    min_ttl = min((rr.ttl for rr in reply.rr), default=0)
    if min_ttl <= 0:
        return
    # Enforce minimum cache TTL — CDNs often return 60s which causes excessive re-queries
    ttl = max(min_ttl, _CACHE_MIN_TTL)
    packed = reply.pack()
    expiry = time.monotonic() + ttl
    with _cache_lock:
        if key := (domain, qtype) in _dns_cache:
            _dns_cache.move_to_end((domain, qtype))
        _dns_cache[(domain, qtype)] = (packed, expiry, upstream)
        if len(_dns_cache) > _CACHE_MAX:
            _dns_cache.popitem(last=False)   # evict oldest


# ---------------------------------------------------------------------------
# Blocked services — cached domain set, reloaded every 30s
# ---------------------------------------------------------------------------
_blocked_svc_domains: set = set()
_blocked_svc_lock = threading.Lock()
_blocked_svc_last: float = 0.0
_BLOCKED_SVC_RELOAD = 30  # seconds


def _load_blocked_services() -> None:
    """Reload blocked service domains from the DB."""
    global _blocked_svc_domains, _blocked_svc_last
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=3) as conn:
            # Import the service definitions
            import sys
            if "/app/dashboard" not in sys.path:
                sys.path.insert(0, "/app/dashboard")
            from services_data import SERVICES_BY_ID
            rows = conn.execute("SELECT service_id FROM blocked_services").fetchall()
            domains = set()
            for (sid,) in rows:
                svc = SERVICES_BY_ID.get(sid)
                if svc:
                    for d in svc["domains"]:
                        domains.add(d.lower())
        with _blocked_svc_lock:
            _blocked_svc_domains = domains
            _blocked_svc_last = time.monotonic()
    except Exception:
        pass  # keep previous set on failure


def _is_service_blocked(domain: str) -> bool:
    """Check if domain (or any parent) belongs to a blocked service."""
    now = time.monotonic()
    if now - _blocked_svc_last > _BLOCKED_SVC_RELOAD:
        _load_blocked_services()
    with _blocked_svc_lock:
        domains = _blocked_svc_domains
    # Check exact match and parent domains (e.g. cdn.facebook.com matches facebook.com)
    if domain in domains:
        return True
    parts = domain.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[i:])
        if parent in domains:
            return True
    return False


def _is_cert_installed(client_ip: str) -> bool:
    """Return True if this client IP has installed the CA cert (captive portal whitelist)."""
    try:
        with sqlite3.connect(SINKHOLE_DB) as conn:
            row = conn.execute(
                "SELECT 1 FROM captive_whitelist WHERE ip = ?", (client_ip,)
            ).fetchone()
            return row is not None
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Hot-reloadable config
# ---------------------------------------------------------------------------

_config: dict = {}
_config_mtime: float = 0.0
_config_lock = threading.Lock()


def get_config() -> dict:
    with _config_lock:
        return _config


def _read_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def reload_config() -> None:
    global _config, _config_mtime
    cfg = _read_config()
    mtime = Path(CONFIG_PATH).stat().st_mtime
    with _config_lock:
        _config = cfg
        _config_mtime = mtime


def config_watcher() -> None:
    log = logging.getLogger("config-watcher")
    while True:
        time.sleep(30)
        try:
            mtime = Path(CONFIG_PATH).stat().st_mtime
            with _config_lock:
                current = _config_mtime
            if mtime != current:
                reload_config()
                log.info("Config hot-reloaded from %s", CONFIG_PATH)
        except Exception as exc:
            log.error("Config watch error: %s", exc)


def bootstrap_config() -> None:
    """Seed /config/config.yml from the baked-in default on first run."""
    dest = Path(CONFIG_PATH)
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_DEFAULT) as f:
            cfg = yaml.safe_load(f) or {}
        with open(dest, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Query log DB
# ---------------------------------------------------------------------------

def init_query_db():
    with sqlite3.connect(SINKHOLE_DB) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                client_ip   TEXT    NOT NULL,
                domain      TEXT    NOT NULL,
                qtype       TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                upstream    TEXT    DEFAULT '',
                response_ms INTEGER DEFAULT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS client_blocks (
                ip          TEXT PRIMARY KEY,
                blocked_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                reason      TEXT DEFAULT 'rate_limit',
                query_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                client_ip   TEXT NOT NULL,
                domain      TEXT DEFAULT '',
                detail      TEXT DEFAULT '',
                resolved_ip TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_ts ON security_events(ts)")
        # Performance indexes on query_log (critical for stats/security/privacy queries)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ql_action    ON query_log(action)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ql_ts        ON query_log(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ql_action_ts ON query_log(action, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ql_client    ON query_log(client_ip)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ql_domain    ON query_log(domain)")
        # Covering index for privacy report (ts range + action filter + group by client_ip,domain)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ql_privacy   ON query_log(ts, action, client_ip, domain)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS device_fingerprints (
                ip          TEXT PRIMARY KEY,
                device_type TEXT NOT NULL,
                confidence  INTEGER DEFAULT 0,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL,
                label       TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dns_records (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT    NOT NULL UNIQUE,
                type     TEXT    NOT NULL DEFAULT 'A',
                value    TEXT    NOT NULL,
                ttl      INTEGER NOT NULL DEFAULT 300,
                enabled  INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule_rules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                label       TEXT    NOT NULL DEFAULT '',
                client_ip   TEXT    NOT NULL DEFAULT '*',
                days        TEXT    NOT NULL DEFAULT '0123456',
                start_time  TEXT    NOT NULL,
                end_time    TEXT    NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS canary_tokens (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                token          TEXT    NOT NULL UNIQUE,
                label          TEXT    NOT NULL DEFAULT '',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                last_triggered TEXT    DEFAULT NULL,
                trigger_count  INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Migrate existing DBs that lack the new columns
        for col, definition in (("upstream", "TEXT DEFAULT ''"), ("response_ms", "INTEGER DEFAULT NULL")):
            try:
                conn.execute(f"ALTER TABLE query_log ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass   # column already exists
        try:
            conn.execute("ALTER TABLE device_fingerprints ADD COLUMN profile TEXT NOT NULL DEFAULT 'normal'")
        except sqlite3.OperationalError:
            pass
        conn.commit()


_log_queue: list = []
_log_queue_lock = threading.Lock()
_LOG_QUEUE_MAX = 500


def log_query(client_ip: str, domain: str, qtype: str, action: str,
              upstream: str = "", response_ms: int | None = None):
    """Enqueue a log entry — never blocks the DNS thread."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = (ts, client_ip, domain, qtype, action, upstream, response_ms)
    with _log_queue_lock:
        if len(_log_queue) < _LOG_QUEUE_MAX:
            _log_queue.append(entry)


def _log_writer() -> None:
    """Background thread: drains the log queue to SQLite in batches."""
    log = logging.getLogger("log-writer")
    while True:
        time.sleep(0.5)
        with _log_queue_lock:
            if not _log_queue:
                continue
            batch = _log_queue[:]
            _log_queue.clear()
        try:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                conn.executemany(
                    "INSERT INTO query_log (ts, client_ip, domain, qtype, action, upstream, response_ms)"
                    " VALUES (?,?,?,?,?,?,?)",
                    batch,
                )
                conn.commit()
        except Exception as exc:
            log.error("Log batch write failed (%d entries): %s", len(batch), exc)


# ---------------------------------------------------------------------------
# Auto-block engine
# ---------------------------------------------------------------------------
# Domains matching these patterns are automatically added to the blocklist
# the first time they are forwarded (allow on first query, block all subsequent).
#
# NOTE: YouTube CDN nodes (googlevideo.com, c.youtube.com) are NOT auto-blocked
# because the same CDN edge serves both video content and ads. DNS-level blocking
# breaks video playback. Ad removal is handled by the YouTube proxy layer instead.
_AUTO_BLOCK_PATTERNS: list[re.Pattern] = [
    # (reserved for future auto-block patterns — YouTube CDN removed)
]

_auto_block_queue: set[str] = set()   # domains pending DB write
_auto_block_seen:  set[str] = set()   # domains already enqueued / written
_auto_block_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Redirect chain detection — catches affiliate hijacking in real time
# Pattern: unknown_domain → attribution_domain → deeplink_domain within 3s
# ---------------------------------------------------------------------------

_ATTRIBUTION_DOMAINS = frozenset({
    "onelink.me", "appsflyer.com", "appsflyersdk.com", "onelink.to",
    "onelinkl.com", "adjust.com", "adjust.io", "adj.st",
    "branch.io", "app.link", "bnc.lt", "go.link",
    "kochava.com", "singular.net", "go.onelink.me",
    "ironsrc.com", "supersonicads.com",
})

_DEEPLINK_DOMAINS = frozenset({
    "shp.ee", "lzd.co", "s.shopee.ph", "s.shopee.com",
    "c.lazada.com.ph", "c.lazada.com", "click.lazada.com.ph",
    "affiliate.shopee.ph", "affiliate.shopee.com",
    "tiktok.com", "vm.tiktok.com", "vt.tiktok.com",
    "lazada.com.ph", "shopee.ph",
})

_CHAIN_WINDOW      = 3.0     # seconds
_CHAIN_MAX_CLIENTS = 2000
_CHAIN_RING_SIZE   = 8
_chain_tracker: dict[str, list] = {}
_chain_lock = threading.Lock()

# Well-known domains that should NOT be treated as "unknown triggers"
_CHAIN_SAFE_PARENTS = frozenset({
    "google.com", "googleapis.com", "gstatic.com", "facebook.com",
    "fbcdn.net", "microsoft.com", "apple.com", "cloudflare.com",
    "akamai.net", "amazonaws.com", "mozilla.com", "mozilla.org",
})


def _classify_chain(domain: str) -> int:
    """0=unknown, 1=attribution, 2=deeplink, 3=safe (skip)."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _ATTRIBUTION_DOMAINS:
            return 1
        if suffix in _DEEPLINK_DOMAINS:
            return 2
        if suffix in _CHAIN_SAFE_PARENTS:
            return 3
    return 0


def _check_redirect_chain(client_ip: str, domain: str) -> tuple[bool, str | None]:
    """Track query and detect affiliate redirect chain pattern.
    Returns (detected, trigger_domain)."""
    now = time.monotonic()
    cat = _classify_chain(domain)
    if cat == 3:
        return False, None  # safe domain, skip tracking

    with _chain_lock:
        ring = _chain_tracker.get(client_ip)
        if ring is None:
            if len(_chain_tracker) >= _CHAIN_MAX_CLIENTS:
                _chain_tracker.pop(next(iter(_chain_tracker)))
            ring = []
            _chain_tracker[client_ip] = ring

        ring.append((now, domain, cat))
        if len(ring) > _CHAIN_RING_SIZE:
            ring.pop(0)

        # Only check pattern when we see a deeplink or attribution domain
        if cat not in (1, 2):
            return False, None

        cutoff = now - _CHAIN_WINDOW
        window = [(ts, d, c) for ts, d, c in ring if ts >= cutoff]

        # Pattern: unknown(0) → attribution(1) within window
        # or: unknown(0) → deeplink(2) within window
        trigger_domain = None
        has_attrib = False
        for _, d, c in window:
            if c == 0 and trigger_domain is None:
                trigger_domain = d
            elif c == 1:
                has_attrib = True

        if trigger_domain and (has_attrib or cat == 2):
            return True, trigger_domain

    return False, None


def _chain_cleanup_task() -> None:
    """Evict stale entries from chain tracker every 60s."""
    while True:
        time.sleep(60)
        now = time.monotonic()
        cutoff = now - _CHAIN_WINDOW * 2
        with _chain_lock:
            stale = [ip for ip, ring in _chain_tracker.items()
                     if ring and ring[-1][0] < cutoff]
            for ip in stale:
                del _chain_tracker[ip]


def _enqueue_auto_block(domain: str) -> None:
    with _auto_block_lock:
        if domain in _auto_block_seen:
            return
        _auto_block_seen.add(domain)
        _auto_block_queue.add(domain)


def _auto_block_writer() -> None:
    """Background thread: flushes auto-block queue to blocklist DB every 5 s."""
    log = logging.getLogger("auto-block")
    while True:
        time.sleep(5)
        with _auto_block_lock:
            if not _auto_block_queue:
                continue
            batch = list(_auto_block_queue)
            _auto_block_queue.clear()
        try:
            with sqlite3.connect(BLOCKLIST_DB, timeout=30) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO blocked_domains (domain) VALUES (?)",
                    [(d,) for d in batch],
                )
                conn.commit()
            log.info("Auto-blocked %d domain(s): %s", len(batch), batch)
        except Exception as exc:
            log.error("Auto-block write failed: %s", exc)
            # Re-queue on failure so they're retried next cycle
            with _auto_block_lock:
                _auto_block_queue.update(batch)


def _check_auto_block(domain: str) -> None:
    """If domain matches an auto-block pattern, enqueue it for blocking."""
    for pattern in _AUTO_BLOCK_PATTERNS:
        if pattern.match(domain):
            _enqueue_auto_block(domain)
            return


# ---------------------------------------------------------------------------
# Security event logging (async queue → SQLite)
# ---------------------------------------------------------------------------

_sec_event_queue: list = []
_sec_event_lock  = threading.Lock()
_SEC_QUEUE_MAX   = 1000


def _log_security_event(client_ip: str, domain: str, event_type: str,
                         detail: str = "", resolved_ip: str = "") -> None:
    """Enqueue a security event — never blocks the DNS thread."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _sec_event_lock:
        if len(_sec_event_queue) < _SEC_QUEUE_MAX:
            _sec_event_queue.append((ts, event_type, client_ip, domain, detail, resolved_ip))


def _sec_event_writer() -> None:
    """Background thread: flush security events to SQLite every 5s."""
    log = logging.getLogger("sec-events")
    while True:
        time.sleep(5)
        with _sec_event_lock:
            if not _sec_event_queue:
                continue
            batch = _sec_event_queue[:]
            _sec_event_queue.clear()
        try:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                conn.executemany(
                    "INSERT INTO security_events (ts, event_type, client_ip, domain, detail, resolved_ip)"
                    " VALUES (?,?,?,?,?,?)",
                    batch,
                )
                conn.commit()
            for row in batch:
                log.warning("SEC-EVENT[%s] client=%s domain=%s detail=%s",
                            row[1], row[2], row[3], row[4])
        except Exception as exc:
            log.error("Security event write failed: %s", exc)
            with _sec_event_lock:
                _sec_event_queue.extend(batch)


# ---------------------------------------------------------------------------
# DNS Rebinding detection
# ---------------------------------------------------------------------------

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
]

_LOCAL_SUFFIXES = (".local", ".internal", ".lan", ".home", ".arpa", ".localhost", ".corp")


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in _PRIVATE_NETS)
    except ValueError:
        return False


def _is_local_domain(domain: str) -> bool:
    return domain == "localhost" or any(domain.endswith(s) for s in _LOCAL_SUFFIXES)


# ---------------------------------------------------------------------------
# DNS Anomaly & DGA detection
# ---------------------------------------------------------------------------

_ANOMALY_WINDOW    = 600   # 10-minute rolling window
_ANOMALY_THRESHOLD = 150   # unique domains per window before flagging
_DGA_MIN_LEN       = 20    # min label length for entropy check
_DGA_ENTROPY       = 4.0   # Shannon entropy threshold (bits/char)

# per-client state: ip → (unique_domain_set, window_start_monotonic)
_anomaly_windows: dict[str, tuple[set, float]] = {}
_anomaly_lock = threading.Lock()


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    total = len(s)
    return -sum((cnt / total) * math.log2(cnt / total) for cnt in Counter(s).values())


def _check_dga(client_ip: str, domain: str) -> None:
    """Flag high-entropy labels as potential DGA beaconing."""
    label = domain.split(".")[0]
    if len(label) >= _DGA_MIN_LEN:
        ent = _shannon_entropy(label)
        if ent >= _DGA_ENTROPY:
            _log_security_event(
                client_ip, domain, "dga_suspect",
                f"label '{label}' entropy={ent:.2f}",
            )


def _check_anomaly(client_ip: str, domain: str) -> None:
    """Detect unusual bursts of unique domain queries per client."""
    now = time.monotonic()
    with _anomaly_lock:
        domains, ws = _anomaly_windows.get(client_ip, (set(), now))
        if now - ws > _ANOMALY_WINDOW:
            # Window elapsed — evaluate before resetting
            if len(domains) > _ANOMALY_THRESHOLD:
                _log_security_event(
                    client_ip, domain, "query_burst",
                    f"{len(domains)} unique domains in {_ANOMALY_WINDOW}s",
                )
            domains, ws = set(), now
        domains.add(domain)
        _anomaly_windows[client_ip] = (domains, ws)


# ---------------------------------------------------------------------------
# Device fingerprinting by DNS query signature
# ---------------------------------------------------------------------------
# (domain_suffix, device_type, weight) — higher weight = more specific signal
_DEVICE_SIGNATURES: list[tuple[str, str, int]] = [
    # Apple devices
    ("mzstatic.com",                            "Apple Device",     5),
    ("icloud.com",                              "Apple Device",     4),
    ("apple.com",                               "Apple Device",     1),
    # Gaming consoles
    ("xboxlive.com",                            "Xbox",             10),
    ("xbox.com",                                "Xbox",             6),
    ("playstation.net",                         "PlayStation",      10),
    ("playstation.com",                         "PlayStation",      5),
    ("nintendo.net",                            "Nintendo Switch",  10),
    ("nintendo.com",                            "Nintendo Switch",  4),
    # Streaming / Smart TV
    ("roku.com",                                "Roku",             10),
    ("samsungcloudsolution.com",                "Samsung TV",       10),
    ("samsungqbe.com",                          "Samsung TV",       10),
    ("tizen.org",                               "Samsung TV",       8),
    ("amazonvideo.com",                         "Amazon Fire TV",   10),
    ("amazon.com",                              "Amazon Device",    2),
    # Android TV — specific to the Android TV / Google TV platform
    ("leanbacklauncher.mutations.google.com",   "Android TV",       15),
    ("androidtv.com",                           "Android TV",       10),
    ("ottx.google.com",                         "Android TV",       12),
    # Xiaomi / MIUI devices (Mi Box, Redmi TV, MIUI phones)
    ("sdkconfig.ad.xiaomi.com",                 "Xiaomi Device",    12),
    ("tracking.miui.com",                       "Xiaomi Device",    10),
    ("data.mistat.xiaomi.com",                  "Xiaomi Device",    10),
    ("resolver.msg.xiaomi.net",                 "Xiaomi Device",    10),
    ("miui.com",                                "Xiaomi Device",    3),
    # Smart speakers / voice
    ("alexa.amazon.com",                        "Amazon Echo",      10),
    ("assistants.google.com",                   "Google Home",      10),
    # IoT / Network gear
    ("synology.com",                            "Synology NAS",     10),
    ("cloud.mikrotik.com",                      "MikroTik",         20),
    ("mikrotik.com",                            "MikroTik",         15),
    ("ubnt.com",                                "Ubiquiti",         10),
    ("ui.com",                                  "Ubiquiti",         8),
    ("tplinkcloud.com",                         "TP-Link",          10),
    ("dlink.com",                               "D-Link",           10),
    ("hikvision.com",                           "Hikvision Camera", 10),
    ("dahuasecurity.com",                       "Dahua Camera",     10),
    ("tuya.com",                                "Tuya IoT",         10),
    ("tuyaeu.com",                              "Tuya IoT",         10),
    # ── Windows-exclusive ────────────────────────────────────────────────
    ("msftconnecttest.com",                     "Windows",          15),
    ("dns.msftncsi.com",                        "Windows",          15),
    ("windowsupdate.com",                       "Windows",          12),
    ("prod.do.dsp.mp.microsoft.com",            "Windows",          12),
    ("v10.events.data.microsoft.com",           "Windows",          12),
    ("settings-win.data.microsoft.com",         "Windows",          12),
    ("client.wns.windows.com",                  "Windows",          12),
    ("activation.sls.microsoft.com",            "Windows",          10),
    ("login.live.com",                          "Windows",          6),
    ("microsoft.com",                           "Windows",          2),
    # ── Android-exclusive (GMS system services, NOT Chrome on desktop) ──
    ("checkin.googleapis.com",                  "Android",          15),
    ("connectivitycheck.android.com",           "Android",          12),
    ("android.googleapis.com",                  "Android",          12),
    ("play.googleapis.com",                     "Android",          10),
    ("ota.googlezip.net",                       "Android",          12),
    ("device-provisioning.googleapis.com",      "Android",          12),
    ("android-context-data.googleapis.com",     "Android",          10),
    ("app-measurement.com",                     "Android",          8),
    # Demoted: Chrome on desktop also queries these via Web Push / Google account
    ("android.clients.google.com",              "Android",          2),
    ("mtalk.google.com",                        "Android",          2),
    ("play.google.com",                         "Android",          1),
    # ── Linux desktop-exclusive ──────────────────────────────────────────
    ("connectivity-check.ubuntu.com",           "Linux",            12),
    ("nmcheck.gnome.org",                       "Linux",            12),
    ("nmcheck.fedoraproject.org",               "Linux",            12),
    ("archive.ubuntu.com",                      "Linux",            10),
    ("security.ubuntu.com",                     "Linux",            10),
    ("ppa.launchpad.net",                       "Linux",            10),
    ("api.snapcraft.io",                        "Linux",            12),
    ("dl.flathub.org",                          "Linux",            10),
    ("livepatch.canonical.com",                 "Linux",            12),
    ("packages.linuxmint.com",                  "Linux",            10),
    ("dl.fedoraproject.org",                    "Linux",            10),
    # ── Apple-exclusive ──────────────────────────────────────────────────
    ("captive.apple.com",                       "Apple Device",     15),
    ("albert.apple.com",                        "Apple Device",     15),
    ("mesu.apple.com",                          "Apple Device",     12),
    ("mask.icloud.com",                         "Apple Device",     12),
    ("mask-h2.icloud.com",                      "Apple Device",     12),
    ("ocsp.apple.com",                          "Apple Device",     8),
    ("gateway.icloud.com",                      "Apple Device",     10),
    # ── ChromeOS-exclusive ───────────────────────────────────────────────
    ("cros-omahaproxy.appspot.com",             "ChromeOS",         20),
    ("chromeos-omahaproxy.appspot.com",         "ChromeOS",         20),
]

_fp_scores:  dict[str, dict[str, int]] = {}   # ip → {device_type: cumulative_weight}
_fp_seen:    dict[str, tuple[str, str]] = {}  # ip → (first_seen, last_seen)
_fp_matched: dict[str, set[str]]        = {}  # ip → {matched_suffix} — dedup: count each suffix once
_fp_dirty:   set[str]                   = set()
_fp_lock     = threading.Lock()


def _check_fingerprint(client_ip: str, domain: str) -> None:
    """Match domain against device signatures; update in-memory scores.

    Each signature suffix is counted at most once per device (per process lifetime)
    to prevent chatty connectivity-check queries from drowning out genuine signals.
    """
    best_type, best_weight, best_suffix = None, 0, None
    for suffix, dtype, weight in _DEVICE_SIGNATURES:
        if (domain == suffix or domain.endswith("." + suffix)) and weight > best_weight:
            best_type, best_weight, best_suffix = dtype, weight, suffix
    if not best_type:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _fp_lock:
        matched = _fp_matched.setdefault(client_ip, set())
        if best_suffix in matched:
            return  # already counted this signal for this device
        matched.add(best_suffix)
        scores = _fp_scores.setdefault(client_ip, {})
        scores[best_type] = scores.get(best_type, 0) + best_weight
        first, _ = _fp_seen.get(client_ip, (now, now))
        _fp_seen[client_ip] = (first, now)
        _fp_dirty.add(client_ip)


# Hostname auto-detection from DNS queries
_hostname_candidates: dict[str, str] = {}  # ip → best hostname candidate
_hostname_lock = threading.Lock()

# Bare hostnames / .local to ignore (common noise, not device names)
_HOSTNAME_IGNORE = frozenset({
    "wpad", "localhost", "lan", "gateway", "_gateway", "config",
    "https", "http", "hthttp", "facebook", "url_to_image",
})


def _check_hostname(client_ip: str, domain: str) -> None:
    """Extract device hostname from bare hostname or .local queries."""
    # Bare hostname (no dots) — e.g. "chadpc", "rpihole"
    if "." not in domain:
        name = domain.lower().strip()
        if name and name not in _HOSTNAME_IGNORE and len(name) >= 3 and name.isascii():
            with _hostname_lock:
                _hostname_candidates[client_ip] = name
            return
    # mDNS .local — e.g. "richards-iphone.local"
    if domain.endswith(".local") and domain.count(".") == 1:
        name = domain[:-6].lower().strip()
        if name and len(name) >= 3:
            with _hostname_lock:
                _hostname_candidates[client_ip] = name


def _get_hostname(ip: str) -> str:
    """Get the best hostname for an IP: query-derived > reverse DNS > empty."""
    with _hostname_lock:
        candidate = _hostname_candidates.get(ip, "")
    if candidate:
        return candidate
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _fp_writer() -> None:
    """Background thread: flush fingerprints to SQLite every 30s."""
    log = logging.getLogger("fingerprint")
    while True:
        time.sleep(30)
        with _fp_lock:
            if not _fp_dirty:
                continue
            snapshot = {}
            for ip in _fp_dirty:
                if ip not in _fp_scores:
                    continue
                best = max(_fp_scores[ip], key=_fp_scores[ip].get)
                snapshot[ip] = (best, _fp_scores[ip][best], _fp_seen.get(ip, ("", "")))
            _fp_dirty.clear()
        if not snapshot:
            continue
        try:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                for ip, (dtype, confidence, (first, last)) in snapshot.items():
                    hostname = _get_hostname(ip)
                    conn.execute(
                        """INSERT INTO device_fingerprints
                               (ip, device_type, confidence, first_seen, last_seen, label)
                           VALUES (?, ?, ?, ?, ?, ?)
                           ON CONFLICT(ip) DO UPDATE SET
                               device_type = excluded.device_type,
                               confidence  = excluded.confidence,
                               last_seen   = excluded.last_seen,
                               label       = CASE WHEN (device_fingerprints.label = '' OR device_fingerprints.label IS NULL) AND excluded.label != ''
                                             THEN excluded.label
                                             ELSE device_fingerprints.label END""",
                        (ip, dtype, confidence, first, last, hostname),
                    )
                # Auto-quarantine new devices if enabled in config
                cfg = get_config()
                if cfg.get("auto_quarantine", False):
                    for ip in snapshot:
                        existing = conn.execute(
                            "SELECT profile FROM device_fingerprints WHERE ip=?", (ip,)
                        ).fetchone()
                        # Only set quarantine if device has no explicit profile yet
                        if existing and existing[0] == "normal":
                            # Check if this is the first time we see it (confidence matches snapshot)
                            _, (_, conf, _) = ip, snapshot[ip]
                            if conf <= 15:  # low confidence = newly seen
                                conn.execute(
                                    "UPDATE device_fingerprints SET profile='quarantine' WHERE ip=? AND profile='normal'",
                                    (ip,),
                                )
                conn.commit()
            log.info("Fingerprints written for %d device(s)", len(snapshot))
        except Exception as exc:
            log.error("Fingerprint write failed: %s", exc)


# ---------------------------------------------------------------------------
# IoT / device burst detection  (1-second sliding window per device IP)
# ---------------------------------------------------------------------------
# IoT devices have very predictable, low-frequency DNS patterns.
# A sudden spike in queries per second is a strong signal of:
#   • Botnet / malware C2 beaconing
#   • Data exfiltration via DNS tunnelling
#   • Compromised firmware making rapid outbound connections
#
# Two thresholds:
#   _BURST_MAX_IOT    — tighter limit for fingerprinted IoT / appliance types
#   _BURST_MAX_NORMAL — looser limit for PCs, phones, servers
# Either way an instant auto-block fires.

_IOT_DEVICE_TYPES = frozenset([
    "Roku", "Samsung TV", "Amazon Fire TV", "Amazon Echo", "Amazon Device",
    "Google Home", "Synology NAS", "MikroTik", "Ubiquiti", "TP-Link", "D-Link",
    "Hikvision Camera", "Dahua Camera", "Tuya IoT",
    "Android TV", "Xiaomi Device",
])

_BURST_WINDOW      = 1.0   # 1-second sliding window
_BURST_MAX_IOT     = 10    # queries/s before auto-block for IoT devices
_BURST_MAX_NORMAL  = 30    # queries/s before auto-block for everything else
_BURST_GRACE       = 60.0  # seconds after startup before burst detection is active
                            # (DNS clients flush buffered queries on server restart — ignore initial burst)

_burst_counters:  dict[str, tuple[int, float]] = {}   # ip → (count, window_start)
_burst_lock       = threading.Lock()
_burst_start_time: float = time.monotonic()            # set at module load; grace window counts from here

_iot_ips:           set[str] = set()
_iot_ips_lock       = threading.Lock()
_iot_ips_last_load: float    = 0.0
_IOT_IPS_RELOAD     = 60     # seconds between DB refreshes

# ---------------------------------------------------------------------------
# Parental control state (reloaded every 30s)
# ---------------------------------------------------------------------------
_parental_devices:      dict[str, dict] = {}  # ip → {social, gaming, social_limit, gaming_limit}
_parental_social:       set[str] = set()
_parental_gaming:       set[str] = set()
_parental_lock          = threading.Lock()
_parental_last_load:    float = 0.0
_PARENTAL_RELOAD        = 30.0

# Screen time usage tracking (write-behind queue)
_usage_today:  dict[tuple, int] = {}   # (ip, category) → today's query count (in-memory)
_usage_queue:  dict[tuple, int] = {}   # pending DB increments
_usage_lock    = threading.Lock()
_usage_date:   str = ""                # YYYY-MM-DD, reset at midnight
_snooze_cache: dict[tuple, float] = {} # (ip, category) → monotonic expiry


def _load_parental() -> None:
    global _parental_devices, _parental_social, _parental_gaming, _parental_last_load
    global _usage_today, _usage_date, _snooze_cache
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            device_rows = conn.execute(
                """SELECT ip, parental_block_social, parental_block_gaming,
                          COALESCE(parental_social_limit, 0),
                          COALESCE(parental_gaming_limit, 0)
                   FROM device_fingerprints
                   WHERE parental_enabled = 1"""
            ).fetchall()
            domain_rows = conn.execute(
                "SELECT domain, category FROM parental_domains"
            ).fetchall()
            try:
                usage_rows = conn.execute(
                    "SELECT ip, category, query_count FROM parental_usage WHERE date = ?",
                    (today,),
                ).fetchall()
            except Exception:
                usage_rows = []
            try:
                now_wall = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                snooze_rows = conn.execute(
                    "SELECT ip, category, expires_at FROM parental_snooze WHERE expires_at > ?",
                    (now_wall,),
                ).fetchall()
            except Exception:
                snooze_rows = []

        devices = {
            r[0]: {
                "social":        bool(r[1]),
                "gaming":        bool(r[2]),
                "social_limit":  int(r[3]),
                "gaming_limit":  int(r[4]),
            }
            for r in device_rows
        }
        social = {r[0] for r in domain_rows if r[1] == "social"}
        gaming = {r[0] for r in domain_rows if r[1] == "gaming"}

        # Build snooze monotonic cache
        now_mono = time.monotonic()
        now_wall_ts = time.time()
        new_snooze: dict = {}
        for ip, cat, expires_str in snooze_rows:
            try:
                expires_wall = datetime.strptime(expires_str, "%Y-%m-%d %H:%M:%S").timestamp()
                expires_mono = now_mono + (expires_wall - now_wall_ts)
                if expires_mono > now_mono:
                    new_snooze[(ip, cat)] = expires_mono
            except Exception:
                pass

        with _parental_lock:
            _parental_devices   = devices
            _parental_social    = social
            _parental_gaming    = gaming
            _parental_last_load = time.monotonic()

        with _usage_lock:
            if _usage_date != today:
                _usage_today.clear()
                _usage_queue.clear()
                _usage_date = today
            # Merge DB values (take max to not lose pending in-memory increments)
            for r in usage_rows:
                key = (r[0], r[1])
                db_count = int(r[2])
                if db_count > _usage_today.get(key, 0):
                    _usage_today[key] = db_count
            _snooze_cache = new_snooze

    except Exception:
        pass


def _track_usage(ip: str, category: str) -> None:
    """Increment in-memory usage counter; background writer flushes to DB every 30s."""
    with _usage_lock:
        key = (ip, category)
        _usage_today[key] = _usage_today.get(key, 0) + 1
        _usage_queue[key] = _usage_queue.get(key, 0) + 1


def _usage_writer() -> None:
    """Background thread: flush screen time increments to SQLite every 30s."""
    log = logging.getLogger("usage")
    while True:
        time.sleep(30)
        with _usage_lock:
            if not _usage_queue:
                continue
            batch = dict(_usage_queue)
            _usage_queue.clear()
        today = datetime.now().strftime("%Y-%m-%d")
        try:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                for (ip, category), delta in batch.items():
                    conn.execute(
                        """INSERT INTO parental_usage (ip, category, date, query_count)
                           VALUES (?, ?, ?, ?)
                           ON CONFLICT(ip, category, date)
                           DO UPDATE SET query_count = query_count + excluded.query_count""",
                        (ip, category, today, delta),
                    )
                conn.commit()
        except Exception as exc:
            log.error("Usage writer failed: %s", exc)
            with _usage_lock:
                for key, delta in batch.items():
                    _usage_queue[key] = _usage_queue.get(key, 0) + delta


def _parental_check(client_ip: str, domain: str) -> str | None:
    """
    Return 'block', 'warn', or None based on parental controls.
    - 'block': hard block (category blocked, or adult content)
    - 'warn':  screen time limit exceeded (soft intercept)
    - None:    allow
    """
    now = time.monotonic()
    if now - _parental_last_load > _PARENTAL_RELOAD:
        _load_parental()
    with _parental_lock:
        device = _parental_devices.get(client_ip)
        if not device:
            return None
        social = _parental_social
        gaming = _parental_gaming

    # Determine category from domain suffixes
    category = None
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in social:
            category = "social"
            break
        if suffix in gaming:
            category = "gaming"
            break

    if category:
        if device[category]:
            # Hard-blocked category
            _track_usage(client_ip, category)
            return "block"
        # Not hard-blocked: check screen time limit
        limit = device[f"{category}_limit"]
        if limit > 0:
            _track_usage(client_ip, category)
            with _usage_lock:
                today_count = _usage_today.get((client_ip, category), 0)
                snoozed     = _snooze_cache.get((client_ip, category), 0) > now
            if today_count >= limit and not snoozed:
                return "warn"
        return None

    # Adult/other: domain is in the main blocklist → parental page
    if blocker.is_blocked(domain):
        return "block"
    return None


def _load_iot_ips() -> None:
    global _iot_ips, _iot_ips_last_load
    try:
        placeholders = ",".join("?" * len(_IOT_DEVICE_TYPES))
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            rows = conn.execute(
                f"SELECT ip FROM device_fingerprints WHERE device_type IN ({placeholders})",
                tuple(_IOT_DEVICE_TYPES),
            ).fetchall()
        ips = {r[0] for r in rows}
        with _iot_ips_lock:
            _iot_ips = ips
            _iot_ips_last_load = time.monotonic()
    except Exception:
        pass


def _burst_check(client_ip: str) -> tuple[bool, str]:
    """
    Update the 1-second query counter for this IP.
    Returns (should_block, detail_str) — does NOT mutate global block state;
    caller is responsible for triggering the actual block.
    """
    now = time.monotonic()
    with _burst_lock:
        count, ws = _burst_counters.get(client_ip, (0, now))
        if now - ws >= _BURST_WINDOW:
            count, ws = 0, now          # new 1-second window
        count += 1
        _burst_counters[client_ip] = (count, ws)
        burst_count = count

    # Refresh IoT IP set if stale
    if now - _iot_ips_last_load > _IOT_IPS_RELOAD:
        _load_iot_ips()
    with _iot_ips_lock:
        is_iot = client_ip in _iot_ips

    # Skip burst enforcement during startup grace window
    if now - _burst_start_time < _BURST_GRACE:
        return False, ""

    rl = _rl_cfg()
    threshold = rl["burst_max_iot"] if is_iot else rl["burst_max_normal"]
    if burst_count > threshold:
        kind = "IoT device" if is_iot else "device"
        detail = f"{kind} DNS burst: {burst_count} queries/s (threshold: {threshold})"
        return True, detail
    return False, ""


def _burst_uncount(client_ip: str) -> None:
    """Decrement burst counter for blocklist-blocked queries."""
    with _burst_lock:
        entry = _burst_counters.get(client_ip)
        if entry and entry[0] > 0:
            _burst_counters[client_ip] = (entry[0] - 1, entry[1])


# ---------------------------------------------------------------------------
# DNS Canary Tokens — hidden tripwire domains; trigger security alert on query
# ---------------------------------------------------------------------------

_canary_tokens: dict[str, dict] = {}   # full token str → {id, label}
_canary_lock   = threading.Lock()
_canary_last_load: float = 0.0
_CANARY_RELOAD = 30

_canary_trigger_queue: list = []
_canary_trigger_lock  = threading.Lock()


_CANARY_SUFFIX = ".rscanary"


def _load_canary_tokens() -> None:
    global _canary_tokens, _canary_last_load
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            rows = conn.execute(
                "SELECT id, token, label FROM canary_tokens"
            ).fetchall()
        # key is the full domain (token + suffix) for direct domain matching
        tokens = {
            (r[1].lower() + _CANARY_SUFFIX): {"id": r[0], "label": r[2]}
            for r in rows
        }
        with _canary_lock:
            _canary_tokens = tokens
            _canary_last_load = time.monotonic()
    except Exception:
        pass


def _check_canary(client_ip: str, domain: str) -> bool:
    """Return True if domain matches a canary token; enqueue trigger update."""
    now = time.monotonic()
    if now - _canary_last_load > _CANARY_RELOAD:
        _load_canary_tokens()
    with _canary_lock:
        info = _canary_tokens.get(domain)
    if info:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _canary_trigger_lock:
            _canary_trigger_queue.append((info["id"], client_ip, domain, ts))
        _log_security_event(
            client_ip, domain, "canary_trigger",
            f"Canary token '{info['label']}' triggered",
        )
        return True
    return False


def _canary_writer() -> None:
    """Background thread: flush canary trigger counts to SQLite every 5s."""
    log = logging.getLogger("canary")
    while True:
        time.sleep(5)
        with _canary_trigger_lock:
            if not _canary_trigger_queue:
                continue
            batch = _canary_trigger_queue[:]
            _canary_trigger_queue.clear()
        try:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                for token_id, client_ip, domain, ts in batch:
                    conn.execute(
                        "UPDATE canary_tokens SET last_triggered=?, trigger_count=trigger_count+1 WHERE id=?",
                        (ts, token_id),
                    )
                conn.commit()
            for token_id, _ip, domain, _ in batch:
                log.warning("CANARY TRIGGERED id=%d domain=%s client=%s", token_id, domain, _ip)
        except Exception as exc:
            log.error("Canary writer failed: %s", exc)
            with _canary_trigger_lock:
                _canary_trigger_queue.extend(batch)


# ---------------------------------------------------------------------------
# Per-device blocking profiles
# ---------------------------------------------------------------------------
# normal     → default behaviour (blocklist enforced)
# strict     → normal + extra keyword-based blocking for tracking/analytics
# passthrough → no blocking at all (trusted servers / admin devices)

_device_profiles: dict[str, str] = {}   # ip → 'normal'|'strict'|'passthrough'
_profiles_lock   = threading.Lock()
_profiles_last_load: float = 0.0
_PROFILES_RELOAD = 30

_STRICT_BLOCK_TERMS = frozenset([
    "analytics", "telemetry", "tracking", "tracker",
    "pagead", "adservice", "pixel.", "beacon.", "metrics.",
    "stats.", "counter.", "collect.", "record.", "hit.",
])


def _load_device_profiles() -> None:
    global _device_profiles, _profiles_last_load
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            rows = conn.execute(
                "SELECT ip, profile FROM device_fingerprints WHERE profile != 'normal'"
            ).fetchall()
        profiles = {r[0]: r[1] for r in rows}
        with _profiles_lock:
            _device_profiles = profiles
            _profiles_last_load = time.monotonic()
    except Exception:
        pass


# Quarantine mode: only these domains are allowed (essential for device onboarding)
_QUARANTINE_ALLOW = frozenset({
    "captive.apple.com", "connectivitycheck.gstatic.com",
    "connectivitycheck.android.com", "clients3.google.com",
    "www.msftconnecttest.com", "dns.msftncsi.com",
    "connectivity-check.ubuntu.com", "nmcheck.gnome.org",
    "time.apple.com", "time.google.com", "pool.ntp.org",
    "ocsp.apple.com", "ocsp.digicert.com", "ocsp.pki.goog",
})


def _get_device_profile(client_ip: str) -> str:
    now = time.monotonic()
    if now - _profiles_last_load > _PROFILES_RELOAD:
        _load_device_profiles()
    with _profiles_lock:
        return _device_profiles.get(client_ip, "normal")


def _is_strict_blocked(domain: str) -> bool:
    return any(term in domain for term in _STRICT_BLOCK_TERMS)


# Dark web / anonymizer detection
_DARKWEB_TLDS = frozenset({".onion", ".i2p"})
_DARKWEB_DOMAINS = frozenset({
    "torproject.org", "tor.eff.org", "bridges.torproject.org",
    "check.torproject.org", "dist.torproject.org",
})


def _check_darkweb(client_ip: str, domain: str) -> bool:
    """Detect .onion/.i2p queries and known Tor infrastructure. Returns True if detected."""
    for tld in _DARKWEB_TLDS:
        if domain.endswith(tld):
            _log_security_event(client_ip, domain, "darkweb_attempt",
                                f"Attempted to resolve {tld} domain")
            return True
    for dd in _DARKWEB_DOMAINS:
        if domain == dd or domain.endswith("." + dd):
            _log_security_event(client_ip, domain, "darkweb_access",
                                f"Accessed Tor infrastructure: {domain}")
            return True
    return False


# ---------------------------------------------------------------------------
# DNS-over-HTTPS / DNS-over-TLS bypass detection
# Detects devices trying to use external encrypted DNS to bypass the sinkhole.
# These are blocked and logged as security events.
# ---------------------------------------------------------------------------

_DOH_DOT_DOMAINS = frozenset({
    # Google DoH/DoT
    "dns.google", "dns.google.com", "dns64.dns.google",
    "8888.google",
    # Cloudflare DoH/DoT
    "cloudflare-dns.com", "one.one.one.one",
    "1dot1dot1dot1.cloudflare-dns.com",
    "dns.cloudflare.com",
    # Quad9 DoH/DoT
    "dns.quad9.net", "dns9.quad9.net", "dns10.quad9.net",
    "dns11.quad9.net",
    # Mozilla/Firefox DoH (Trusted Recursive Resolver)
    "mozilla.cloudflare-dns.com",
    "use-application-dns.net",  # Firefox canary domain — if blocked, Firefox disables DoH
    # NextDNS
    "dns.nextdns.io",
    # AdGuard DoH
    "dns.adguard.com", "dns-family.adguard.com",
    "dns-unfiltered.adguard.com",
    # Mullvad DoH
    "dns.mullvad.net", "adblock.dns.mullvad.net",
    # OpenDNS / Cisco
    "doh.opendns.com", "dns.opendns.com",
    # Comodo / Neustar
    "doh.cleanbrowsing.org", "dns.cleanbrowsing.org",
    # Other common DoH providers
    "doh.applied-privacy.net",
    "doh.dns.sb", "dns.sb",
    "dns.twnic.tw",
    "ordns.he.net",
    "dns.switch.ch",
})

# Config key to control behavior: "block" (default), "log", or "off"
_DOH_MODE_KEY = "doh_bypass_mode"


def _check_doh_bypass(client_ip: str, domain: str, cfg: dict) -> bool:
    """Detect and optionally block DNS-over-HTTPS/DoT bypass attempts.
    Returns True if the query should be blocked."""
    mode = cfg.get(_DOH_MODE_KEY, "block")
    if mode == "off":
        return False

    matched = False
    for dd in _DOH_DOT_DOMAINS:
        if domain == dd or domain.endswith("." + dd):
            matched = True
            break
    if not matched:
        return False

    _log_security_event(client_ip, domain, "doh_bypass",
                        f"DNS bypass attempt via {domain}")

    if mode == "block":
        return True  # caller should block the query
    return False  # log-only mode


# ---------------------------------------------------------------------------
# Custom local DNS records (A / CNAME overrides)
# ---------------------------------------------------------------------------

_dns_records: dict[str, dict] = {}   # hostname → {type, value, ttl}
_dns_records_lock  = threading.Lock()
_dns_records_last_load: float = 0.0
_DNS_RECORDS_RELOAD = 30


def _load_dns_records() -> None:
    global _dns_records, _dns_records_last_load
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            rows = conn.execute(
                "SELECT hostname, type, value, ttl FROM dns_records WHERE enabled=1"
            ).fetchall()
        records = {r[0].lower(): {"type": r[1], "value": r[2], "ttl": r[3]} for r in rows}
        with _dns_records_lock:
            _dns_records = records
            _dns_records_last_load = time.monotonic()
    except Exception:
        pass


def _get_custom_record(hostname: str) -> dict | None:
    now = time.monotonic()
    if now - _dns_records_last_load > _DNS_RECORDS_RELOAD:
        _load_dns_records()
    with _dns_records_lock:
        return _dns_records.get(hostname.lower())


# ---------------------------------------------------------------------------
# Smart scheduling (time-based per-device blocking)
# ---------------------------------------------------------------------------

_schedule_rules: list[dict] = []   # list of rule dicts loaded from DB
_schedule_lock  = threading.Lock()
_schedule_last_load: float = 0.0
_SCHEDULE_RELOAD = 30              # seconds between DB reloads


def _load_schedule_rules() -> None:
    global _schedule_rules, _schedule_last_load
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            # Check if grace_minutes column exists
            cols = {r[1] for r in conn.execute("PRAGMA table_info(schedule_rules)")}
            if "grace_minutes" in cols:
                rows = conn.execute(
                    "SELECT client_ip, days, start_time, end_time, COALESCE(grace_minutes,0) FROM schedule_rules WHERE enabled=1"
                ).fetchall()
                rules = [{"ip": r[0], "days": r[1], "start": r[2], "end": r[3], "grace": r[4]} for r in rows]
            else:
                rows = conn.execute(
                    "SELECT client_ip, days, start_time, end_time FROM schedule_rules WHERE enabled=1"
                ).fetchall()
                rules = [{"ip": r[0], "days": r[1], "start": r[2], "end": r[3], "grace": 0} for r in rows]
        with _schedule_lock:
            _schedule_rules = rules
            _schedule_last_load = time.monotonic()
    except Exception:
        pass


def _is_scheduled_block(client_ip: str) -> str | None:
    """Check if client is in a schedule block window.
    Returns: 'block' if hard-blocked, 'grace' if in grace period, None if not blocked."""
    now = time.monotonic()
    if now - _schedule_last_load > _SCHEDULE_RELOAD:
        _load_schedule_rules()

    from datetime import datetime as _dt
    dt = _dt.now()
    weekday = str(dt.weekday())          # 0=Mon … 6=Sun
    hhmm = dt.strftime("%H:%M")

    with _schedule_lock:
        rules = list(_schedule_rules)

    for rule in rules:
        # IP match: wildcard or exact
        if rule["ip"] != "*" and rule["ip"] != client_ip:
            continue
        # Day match
        if weekday not in rule["days"]:
            continue
        # Time match (handles overnight ranges like 22:00-07:00)
        s, e = rule["start"], rule["end"]
        if s <= e:
            in_window = s <= hhmm < e
        else:                            # crosses midnight
            in_window = hhmm >= s or hhmm < e
        if in_window:
            grace = rule.get("grace", 0)
            if grace > 0:
                # Check if we're still in the grace period (first N minutes of the window)
                sh, sm = int(s[:2]), int(s[3:5])
                start_min = sh * 60 + sm
                now_min = dt.hour * 60 + dt.minute
                # Handle overnight: if now is before start, add 24h
                if s > e and now_min < start_min:
                    elapsed = (now_min + 1440) - start_min
                else:
                    elapsed = now_min - start_min
                if elapsed < grace:
                    return "grace"
            return "block"
    return None


# ---------------------------------------------------------------------------
# Per-client rate limiter & brute-force / flood protection
# ---------------------------------------------------------------------------

_RATE_WINDOW    = 10    # sliding window in seconds
_RATE_MAX       = 100   # max queries per window before rate-limiting (10 QPS avg)
_NXDOMAIN_MAX   = 50    # max NXDOMAINs per window before recon block
_BLOCK_AFTER    = 3     # consecutive over-limit windows before temp block
_BLOCK_DURATION = 300   # block duration in seconds (5 min)


def _rl_cfg() -> dict:
    """Return current rate limit thresholds from live config (hot-reloaded every 30s)."""
    cfg = get_config()
    return {
        "rate_window":      int(cfg.get("rate_window",      _RATE_WINDOW)),
        "rate_max":         int(cfg.get("rate_max",          _RATE_MAX)),
        "block_duration":   int(cfg.get("block_duration",    _BLOCK_DURATION)),
        "burst_max_normal": int(cfg.get("burst_max_normal",  _BURST_MAX_NORMAL)),
        "burst_max_iot":    int(cfg.get("burst_max_iot",     _BURST_MAX_IOT)),
    }

_rate_counters:    dict[str, tuple[int, float]] = {}  # ip → (count, window_start)
_nxdomain_counters: dict[str, tuple[int, float]] = {} # ip → (count, window_start)
_rate_violations:  dict[str, int] = {}                # ip → consecutive violation count
_client_blocks:    dict[str, float] = {}              # ip → expiry (monotonic)
_block_write_queue: dict[str, dict] = {}              # pending DB writes
_rl_lock = threading.Lock()


def _rate_check(client_ip: str) -> tuple[bool, str]:
    """
    Check and update rate counter. Returns (should_refuse, reason).
    Called in the hot path — lock is held only for dict ops.
    """
    now = time.monotonic()
    rl = _rl_cfg()
    with _rl_lock:
        # Already blocked?
        if client_ip in _client_blocks:
            if now < _client_blocks[client_ip]:
                return True, "blocked"
            del _client_blocks[client_ip]

        # Sliding window query counter
        count, ws = _rate_counters.get(client_ip, (0, now))
        if now - ws > rl["rate_window"]:
            count, ws = 0, now
            # Decay violations on a clean new window
            if client_ip in _rate_violations:
                _rate_violations[client_ip] = max(0, _rate_violations[client_ip] - 1)
        count += 1
        _rate_counters[client_ip] = (count, ws)

        if count > rl["rate_max"]:
            v = _rate_violations.get(client_ip, 0) + 1
            _rate_violations[client_ip] = v
            if v >= _BLOCK_AFTER:
                _do_block(client_ip, "rate_limit", count, rl["block_duration"])
                _rate_violations[client_ip] = 0
            return True, "rate_limit"

    return False, ""


def _rate_uncount(client_ip: str) -> None:
    """Decrement rate counter for a query that was blocked by the blocklist.

    Blocked domains (ads/trackers) should not fill up the rate bucket and
    penalise legitimate queries from the same client.
    """
    with _rl_lock:
        entry = _rate_counters.get(client_ip)
        if entry and entry[0] > 0:
            _rate_counters[client_ip] = (entry[0] - 1, entry[1])


def _nxdomain_update(client_ip: str) -> None:
    """Track NXDOMAIN responses; auto-block on flood (DNS recon detection)."""
    now = time.monotonic()
    with _rl_lock:
        if client_ip in _client_blocks:
            return  # already blocked
        nc, nws = _nxdomain_counters.get(client_ip, (0, now))
        if now - nws > _RATE_WINDOW:
            nc, nws = 0, now
        nc += 1
        _nxdomain_counters[client_ip] = (nc, nws)
        if nc > _NXDOMAIN_MAX:
            _do_block(client_ip, "nxdomain_flood", nc)


def _do_block(client_ip: str, reason: str, query_count: int, duration: int = _BLOCK_DURATION) -> None:
    """Add to in-memory block dict and write queue. Must be called under _rl_lock."""
    _client_blocks[client_ip] = time.monotonic() + duration
    _block_write_queue[client_ip] = {"reason": reason, "query_count": query_count}


def _block_writer_task() -> None:
    """Background thread: flush new blocks to SQLite every 5s."""
    log = logging.getLogger("block-writer")
    while True:
        time.sleep(5)
        with _rl_lock:
            if not _block_write_queue:
                continue
            batch = dict(_block_write_queue)
            _block_write_queue.clear()
        try:
            with sqlite3.connect(SINKHOLE_DB, timeout=30) as conn:
                for ip, info in batch.items():
                    conn.execute(
                        """INSERT INTO client_blocks (ip, blocked_at, expires_at, reason, query_count)
                           VALUES (?, datetime('now'), datetime('now', ?), ?, ?)
                           ON CONFLICT(ip) DO UPDATE SET
                             blocked_at  = excluded.blocked_at,
                             expires_at  = excluded.expires_at,
                             reason      = excluded.reason,
                             query_count = excluded.query_count""",
                        (ip, f"+{_BLOCK_DURATION} seconds", info["reason"], info["query_count"]),
                    )
                conn.commit()
            log.warning("Blocked %d client(s): %s", len(batch), list(batch.keys()))
        except Exception as exc:
            log.error("Block write failed: %s", exc)
            with _rl_lock:
                _block_write_queue.update(batch)  # re-queue on failure


def _load_existing_blocks() -> None:
    """On startup: restore non-expired blocks from SQLite into memory."""
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=10) as conn:
            rows = conn.execute(
                "SELECT ip, (julianday(expires_at) - julianday('now')) * 86400 "
                "FROM client_blocks WHERE expires_at > datetime('now')"
            ).fetchall()
        now = time.monotonic()
        with _rl_lock:
            for ip, secs_left in rows:
                _client_blocks[ip] = now + max(0.0, secs_left)
        if rows:
            logging.getLogger("block-writer").info(
                "Restored %d active block(s) from DB", len(rows)
            )
    except Exception as exc:
        logging.getLogger("block-writer").warning("Could not load existing blocks: %s", exc)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class SinkholeResolver(BaseResolver):
    def __init__(self):
        self.logger = logging.getLogger("resolver")

    def resolve(self, request, handler):
        cfg = get_config()
        qname = str(request.q.qname)
        qtype_str = QTYPE[request.q.qtype]
        client_ip = handler.client_address[0]
        domain = qname.lower().rstrip(".")

        # Determine device blocking profile (early — needed by burst/rate checks)
        profile = _get_device_profile(client_ip)
        passthrough = (profile == "passthrough")

        # Quarantine: allow only essential DNS (captive portal check, NTP, OCSP)
        if profile == "quarantine":
            if domain not in _QUARANTINE_ALLOW and not any(domain.endswith("." + a) for a in _QUARANTINE_ALLOW):
                self.logger.info("QUARANTINE %s  (client=%s)", domain, client_ip)
                log_query(client_ip, domain, qtype_str, "blocked")
                return self._redirect_response(request, "0.0.0.0")

        # 0. Rate limit / flood protection (skipped for passthrough)
        if not passthrough:
            refuse, rl_reason = _rate_check(client_ip)
            if refuse:
                self.logger.warning("REFUSED  %s  [%s]  (client=%s)", domain, rl_reason, client_ip)
                log_query(client_ip, domain, qtype_str, "ratelimited")
                reply = request.reply()
                reply.header.rcode = 5  # REFUSED
                return reply

        # 0a. IoT / device burst detection (skipped for passthrough)
        if not passthrough:
            burst, burst_detail = _burst_check(client_ip)
            if burst:
                self.logger.warning("BURST    %s  (client=%s) %s", domain, client_ip, burst_detail)
                with _iot_ips_lock:
                    is_iot_block = client_ip in _iot_ips
                block_reason = "iot_flood" if is_iot_block else "burst_limit"
                with _rl_lock:
                    if client_ip not in _client_blocks:
                        _do_block(client_ip, block_reason, _burst_counters.get(client_ip, (0,))[0],
                                  _rl_cfg()["block_duration"])
                _log_security_event(client_ip, domain, block_reason, burst_detail)
                log_query(client_ip, domain, qtype_str, "ratelimited")
                reply = request.reply()
                reply.header.rcode = 5  # REFUSED
                return reply

        # 0c. Canary token check (always — security tripwire, runs for all profiles)
        if _check_canary(client_ip, domain):
            self.logger.warning("CANARY   %s  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            reply = request.reply()
            reply.header.rcode = 3  # NXDOMAIN
            return reply

        # 0b. Schedule / bedtime block (skipped for passthrough)
        if not passthrough:
            sched_result = _is_scheduled_block(client_ip)
            if sched_result == "block":
                self.logger.info("SCHEDULED %s  (client=%s)", domain, client_ip)
                log_query(client_ip, domain, qtype_str, "scheduled")
                reply = request.reply()
                reply.header.rcode = 3  # NXDOMAIN
                return reply
            elif sched_result == "grace":
                # Grace period: redirect to bedtime warning page instead of blocking
                host_ip = cfg.get("captive_portal_ip") or cfg.get("youtube_redirect_ip", "")
                if host_ip:
                    self.logger.info("BEDTIME-WARN %s -> %s  (client=%s)", domain, host_ip, client_ip)
                    log_query(client_ip, domain, qtype_str, "scheduled")
                    return self._redirect_response(request, host_ip)

        # 1. Captive portal detection domains (skipped for passthrough)
        cp_enabled = cfg.get("captive_portal_enabled", False)
        cp_ip = cfg.get("captive_portal_ip") or cfg.get("youtube_redirect_ip", "")
        if not passthrough and cp_enabled and cp_ip and domain in CAPTIVE_PORTAL_DOMAINS:
            # Skip redirect for whitelisted clients — their OS connectivity checks
            # must reach real servers or the OS will keep showing "no internet".
            if not _is_cert_installed(client_ip):
                self.logger.info("CAPTIVE  %s -> %s  (client=%s)", domain, cp_ip, client_ip)
                log_query(client_ip, domain, qtype_str, "captive")
                return self._redirect_response(request, cp_ip)

        # 2. YouTube redirect — only for clients with cert installed (skipped for passthrough)
        yt_enabled = cfg.get("youtube_redirect_enabled", False)
        yt_ip = cfg.get("youtube_redirect_ip", "")
        yt_domains = {d.lower() for d in cfg.get("youtube_domains", [])}

        if not passthrough and yt_enabled and yt_ip and domain in yt_domains:
            if _is_cert_installed(client_ip):
                self.logger.info("REDIRECTED %s -> %s  (client=%s)", domain, yt_ip, client_ip)
                log_query(client_ip, domain, qtype_str, "youtube")
                return self._redirect_response(request, yt_ip)
            else:
                self.logger.debug("YT-SKIP %s  cert not installed  (client=%s)", domain, client_ip)

        # 2b. Parental controls — redirect to block/warning page on the server
        if not passthrough:
            parental_action = _parental_check(client_ip, domain)
            if parental_action:
                host_ip = cfg.get("captive_portal_ip") or cfg.get("youtube_redirect_ip", "")
                if host_ip:
                    action_str = "parental" if parental_action == "block" else "parental_warn"
                    self.logger.info("PARENTAL[%s] %s -> %s  (client=%s)",
                                     parental_action, domain, host_ip, client_ip)
                    log_query(client_ip, domain, qtype_str, action_str)
                    return self._redirect_response(request, host_ip)

        # 3. Blocked services check (skipped for passthrough)
        if not passthrough and _is_service_blocked(domain):
            self.logger.info("SERVICE  %s -> 0.0.0.0  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            _rate_uncount(client_ip)
            _burst_uncount(client_ip)
            return self._redirect_response(request, "0.0.0.0")

        # 4. Blocklist check (allowlist takes precedence inside is_blocked; skipped for passthrough)
        if not passthrough and blocker.is_blocked(domain):
            self.logger.info("BLOCKED  %s -> 0.0.0.0  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            _rate_uncount(client_ip)
            _burst_uncount(client_ip)
            return self._redirect_response(request, "0.0.0.0")

        # 3a. Strict profile: extra keyword-based blocking for tracking/analytics domains
        if not passthrough and profile in ("strict", "guest") and _is_strict_blocked(domain):
            self.logger.info("STRICT   %s -> 0.0.0.0  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            _rate_uncount(client_ip)
            _burst_uncount(client_ip)
            return self._redirect_response(request, "0.0.0.0")

        # 3c. DNS-over-HTTPS / DNS-over-TLS bypass detection (skipped for passthrough)
        if not passthrough and _check_doh_bypass(client_ip, domain, cfg):
            self.logger.warning("DOH-BYPASS %s -> 0.0.0.0  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            _rate_uncount(client_ip)
            _burst_uncount(client_ip)
            return self._redirect_response(request, "0.0.0.0")

        # 3b. Custom local DNS record
        custom = _get_custom_record(domain)
        if custom:
            if custom["type"] == "A" and request.q.qtype == QTYPE.A:
                self.logger.info("LOCAL-DNS %s -> %s  (client=%s)", domain, custom["value"], client_ip)
                log_query(client_ip, domain, qtype_str, "allowed")
                reply = request.reply()
                reply.header.rcode = 0
                reply.add_answer(RR(
                    rname=request.q.qname,
                    rtype=QTYPE.A,
                    rdata=A(custom["value"]),
                    ttl=custom["ttl"],
                ))
                return reply
            elif custom["type"] == "CNAME":
                from dnslib import CNAME as DnsCNAME
                self.logger.info("LOCAL-DNS %s -> CNAME %s  (client=%s)", domain, custom["value"], client_ip)
                log_query(client_ip, domain, qtype_str, "allowed")
                reply = request.reply()
                reply.header.rcode = 0
                reply.add_answer(RR(
                    rname=request.q.qname,
                    rtype=QTYPE.CNAME,
                    rdata=DnsCNAME(custom["value"]),
                    ttl=custom["ttl"],
                ))
                return reply

        # 4. Cache lookup
        upstream = cfg.get("upstream_dns", "1.1.1.1")
        cached = _cache_get(domain, request.q.qtype, request.header.id)
        if cached is not None:
            reply, cached_upstream = cached
            self.logger.debug("CACHED   %s  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "cached", upstream=cached_upstream, response_ms=0)
            return reply

        # 5. Forward to upstream
        reply, elapsed_ms = self._forward(request, upstream)
        if reply.header.rcode == 0:
            # DNS Rebinding detection: block public domains that resolve to private IPs
            if not _is_local_domain(domain) and request.q.qtype == QTYPE.A:
                for rr in reply.rr:
                    if rr.rtype == QTYPE.A:
                        rip = str(rr.rdata)
                        if _is_private_ip(rip):
                            self.logger.warning(
                                "REBINDING %s -> %s (client=%s)", domain, rip, client_ip
                            )
                            log_query(client_ip, domain, qtype_str, "rebinding",
                                      upstream=upstream, response_ms=elapsed_ms)
                            _log_security_event(
                                client_ip, domain, "rebinding",
                                f"public domain resolved to private IP {rip}", rip,
                            )
                            rb_reply = request.reply()
                            rb_reply.header.rcode = 3  # NXDOMAIN
                            return rb_reply

            # CNAME Cloaking detection: block if CNAME chain leads to a blocked domain
            # Skip if the original domain is explicitly allowlisted
            if not passthrough and not blocker.is_allowed(domain):
                for rr in reply.rr:
                    if rr.rtype == QTYPE.CNAME:
                        cname_target = str(rr.rdata).rstrip(".")
                        if blocker.is_blocked(cname_target):
                            self.logger.warning(
                                "CNAME-CLOAK %s -> %s BLOCKED (client=%s)",
                                domain, cname_target, client_ip,
                            )
                            _log_security_event(
                                client_ip, domain, "cname_cloaking",
                                f"CNAME chain: {domain} → {cname_target}",
                            )
                            log_query(client_ip, domain, qtype_str, "blocked",
                                      upstream=upstream, response_ms=elapsed_ms)
                            return self._redirect_response(request, "0.0.0.0")

            _cache_put(domain, request.q.qtype, reply, upstream)
            _check_auto_block(domain)
            _check_dga(client_ip, domain)
            _check_anomaly(client_ip, domain)
            _check_fingerprint(client_ip, domain)
            _check_hostname(client_ip, domain)
            _check_darkweb(client_ip, domain)

            # Redirect chain detection (affiliate hijacking)
            if not passthrough and cfg.get("redirect_chain_detection", True):
                chain_hit, chain_trigger = _check_redirect_chain(client_ip, domain)
                if chain_hit and chain_trigger:
                    _enqueue_auto_block(chain_trigger)
                    _log_security_event(
                        client_ip, chain_trigger, "affiliate_chain",
                        f"redirect chain: {chain_trigger} -> {domain}",
                    )
                    self.logger.warning(
                        "CHAIN    %s  trigger=%s  (client=%s)",
                        domain, chain_trigger, client_ip,
                    )

            self.logger.info("FORWARDED %s  (client=%s upstream=%s %dms)", domain, client_ip, upstream, elapsed_ms)
            log_query(client_ip, domain, qtype_str, "forwarded", upstream=upstream, response_ms=elapsed_ms)
        elif reply.header.rcode == 3:  # NXDOMAIN
            _nxdomain_update(client_ip)
            _check_hostname(client_ip, domain)
            self.logger.info("NXDOMAIN %s  (client=%s upstream=%s %dms)", domain, client_ip, upstream, elapsed_ms)
            log_query(client_ip, domain, qtype_str, "nxdomain", upstream=upstream, response_ms=elapsed_ms)
        else:
            self.logger.warning("FAILED   %s  rcode=%d  (client=%s upstream=%s %dms)", domain, reply.header.rcode, client_ip, upstream, elapsed_ms)
            log_query(client_ip, domain, qtype_str, "failed", upstream=upstream, response_ms=elapsed_ms)
        return reply

    def _redirect_response(self, request, ip: str):
        reply = request.reply()
        reply.header.rcode = 0
        if request.q.qtype == QTYPE.A:
            reply.add_answer(RR(
                rname=request.q.qname,
                rtype=QTYPE.A,
                ttl=60,
                rdata=A(ip),
            ))
        return reply

    def _forward(self, request, upstream: str) -> tuple:
        """Forward query to upstream. Returns (reply, elapsed_ms)."""
        t0 = time.monotonic()
        try:
            raw = request.pack()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(raw, (upstream, 53))
            data, _ = sock.recvfrom(4096)
            sock.close()
            from dnslib import DNSRecord
            reply = DNSRecord.parse(data)
        except Exception as exc:
            self.logger.error("Upstream DNS error for %s: %s", request.q.qname, exc)
            reply = request.reply()
            reply.header.rcode = 2  # SERVFAIL
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return reply, elapsed_ms


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap():
    """Initialise DBs; seed blocklist if first run."""
    Path("/data").mkdir(parents=True, exist_ok=True)

    init_query_db()

    blocklist_exists = Path(BLOCKLIST_DB).exists()
    blocker.init_blocklist_db()

    if not blocklist_exists:
        logging.getLogger("bootstrap").info(
            "Blocklist DB not found — seeding from %s", DEFAULT_BLOCKLIST
        )
        blocker.seed_from_file(DEFAULT_BLOCKLIST)
    else:
        logging.getLogger("bootstrap").info("Blocklist DB already exists, skipping seed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def setup_logging(level_str: str):
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=level,
    )


def start_dns():
    """Initialise config, spawn daemon threads, start UDP+TCP servers.

    Returns immediately — all work runs in daemon threads.
    Called by the unified sinkhole entrypoint or standalone mode.
    """
    bootstrap_config()
    reload_config()

    cfg = get_config()
    setup_logging(cfg.get("log_level", "info"))

    log = logging.getLogger("main")
    log.info("RichSinkhole DNS starting up...")

    bootstrap()

    # Start config hot-reload watcher
    watcher = threading.Thread(target=config_watcher, daemon=True, name="config-watcher")
    watcher.start()
    log.info("Config watcher started (polling every 30s)")

    # Start async log writer (keeps DNS thread non-blocking)
    writer = threading.Thread(target=_log_writer, daemon=True, name="log-writer")
    writer.start()
    log.info("Log writer started (batch flush every 500ms)")

    # Start auto-block writer
    ab_writer = threading.Thread(target=_auto_block_writer, daemon=True, name="auto-block")
    ab_writer.start()
    log.info("Auto-block writer started (flush every 5s)")

    # Start security event writer
    sec_writer = threading.Thread(target=_sec_event_writer, daemon=True, name="sec-events")
    sec_writer.start()
    log.info("Security event writer started")

    # Start device fingerprint writer
    fp_writer = threading.Thread(target=_fp_writer, daemon=True, name="fingerprint")
    fp_writer.start()
    log.info("Device fingerprint writer started")

    # Start canary token writer
    ct_writer = threading.Thread(target=_canary_writer, daemon=True, name="canary")
    ct_writer.start()
    log.info("Canary token writer started")

    # Start client block writer + restore previous session blocks
    bw = threading.Thread(target=_block_writer_task, daemon=True, name="block-writer")
    bw.start()
    _load_existing_blocks()
    log.info("Block writer started; existing blocks restored")

    # Start screen time usage writer
    uw = threading.Thread(target=_usage_writer, daemon=True, name="usage-writer")
    uw.start()
    log.info("Usage writer started (flush every 30s)")

    # Start redirect chain cleanup thread
    cc = threading.Thread(target=_chain_cleanup_task, daemon=True, name="chain-cleanup")
    cc.start()

    dns_logger = DnsLibLogger(prefix=False)
    resolver = SinkholeResolver()

    udp_server = DNSServer(resolver, port=53, address="0.0.0.0", logger=dns_logger)
    tcp_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=True, logger=dns_logger)

    udp_server.start_thread()
    tcp_server.start_thread()

    log.info("Listening on 0.0.0.0:53 (UDP+TCP). Upstream: %s", cfg.get("upstream_dns"))
    log.info("Config: %s | Blocklist DB: %s | Query log DB: %s",
             CONFIG_PATH, BLOCKLIST_DB, SINKHOLE_DB)


def main():
    start_dns()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        logging.getLogger("main").info("Shutting down.")


if __name__ == "__main__":
    main()
