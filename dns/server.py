#!/usr/bin/env python3
"""
RichSinkhole DNS Server
UDP/TCP DNS server with blocklist enforcement and SQLite query logging.
"""

import logging
import os
import re
import shutil
import socket
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

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
    "www.msftconnecttest.com",
    "www.msftncsi.com",
    "ipv6.msftconnecttest.com",
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

_CACHE_MAX = 5000
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
    """Cache a successful reply using the minimum TTL from its answer records."""
    if not reply.rr:
        return
    min_ttl = min((rr.ttl for rr in reply.rr), default=0)
    if min_ttl <= 0:
        return
    packed = reply.pack()
    expiry = time.monotonic() + min_ttl
    with _cache_lock:
        if key := (domain, qtype) in _dns_cache:
            _dns_cache.move_to_end((domain, qtype))
        _dns_cache[(domain, qtype)] = (packed, expiry, upstream)
        if len(_dns_cache) > _CACHE_MAX:
            _dns_cache.popitem(last=False)   # evict oldest


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
        # Migrate existing DBs that lack the new columns
        for col, definition in (("upstream", "TEXT DEFAULT ''"), ("response_ms", "INTEGER DEFAULT NULL")):
            try:
                conn.execute(f"ALTER TABLE query_log ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass   # column already exists
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
# YouTube CDN node naming format:
#   r[N]---sn-[id].googlevideo.com   (triple-dash, single-r prefix)
#   r[N].sn-[id].googlevideo.com     (dot-separator, single-r prefix)
#   rr[N]---sn-[id].googlevideo.com  (triple-dash, double-r prefix)
#   rr[N].sn-[id].googlevideo.com    (dot-separator, double-r prefix)
# Also via c.youtube.com (ISP/peering cache, same node naming convention).
_AUTO_BLOCK_PATTERNS: list[re.Pattern] = [
    # Primary YouTube CDN delivery nodes — googlevideo.com
    re.compile(r"^rr?\d+(?:---|\.)sn-[a-z0-9][-a-z0-9]*\.googlevideo\.com$", re.IGNORECASE),
    # ISP/peering cache format — c.youtube.com (same node naming, different TLD)
    re.compile(r"^rr?\d+(?:---|\.)sn-[a-z0-9][-a-z0-9]*\.c\.youtube\.com$", re.IGNORECASE),
]

_auto_block_queue: set[str] = set()   # domains pending DB write
_auto_block_seen:  set[str] = set()   # domains already enqueued / written
_auto_block_lock = threading.Lock()


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
# Per-client rate limiter & brute-force / flood protection
# ---------------------------------------------------------------------------

_RATE_WINDOW    = 10    # sliding window in seconds
_RATE_MAX       = 100   # max queries per window before rate-limiting (10 QPS avg)
_NXDOMAIN_MAX   = 50    # max NXDOMAINs per window before recon block
_BLOCK_AFTER    = 3     # consecutive over-limit windows before temp block
_BLOCK_DURATION = 300   # block duration in seconds (5 min)

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
    with _rl_lock:
        # Already blocked?
        if client_ip in _client_blocks:
            if now < _client_blocks[client_ip]:
                return True, "blocked"
            del _client_blocks[client_ip]

        # Sliding window query counter
        count, ws = _rate_counters.get(client_ip, (0, now))
        if now - ws > _RATE_WINDOW:
            count, ws = 0, now
            # Decay violations on a clean new window
            if client_ip in _rate_violations:
                _rate_violations[client_ip] = max(0, _rate_violations[client_ip] - 1)
        count += 1
        _rate_counters[client_ip] = (count, ws)

        if count > _RATE_MAX:
            v = _rate_violations.get(client_ip, 0) + 1
            _rate_violations[client_ip] = v
            if v >= _BLOCK_AFTER:
                _do_block(client_ip, "rate_limit", count)
                _rate_violations[client_ip] = 0
            return True, "rate_limit"

    return False, ""


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


def _do_block(client_ip: str, reason: str, query_count: int) -> None:
    """Add to in-memory block dict and write queue. Must be called under _rl_lock."""
    _client_blocks[client_ip] = time.monotonic() + _BLOCK_DURATION
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

        # 0. Rate limit / flood protection
        refuse, rl_reason = _rate_check(client_ip)
        if refuse:
            self.logger.warning("REFUSED  %s  [%s]  (client=%s)", domain, rl_reason, client_ip)
            log_query(client_ip, domain, qtype_str, "ratelimited")
            reply = request.reply()
            reply.header.rcode = 5  # REFUSED
            return reply

        # 1. Captive portal detection domains (highest priority)
        cp_enabled = cfg.get("captive_portal_enabled", False)
        cp_ip = cfg.get("captive_portal_ip") or cfg.get("youtube_redirect_ip", "")
        if cp_enabled and cp_ip and domain in CAPTIVE_PORTAL_DOMAINS:
            # Skip redirect for whitelisted clients — their OS connectivity checks
            # must reach real servers or the OS will keep showing "no internet".
            if not _is_cert_installed(client_ip):
                self.logger.info("CAPTIVE  %s -> %s  (client=%s)", domain, cp_ip, client_ip)
                log_query(client_ip, domain, qtype_str, "captive")
                return self._redirect_response(request, cp_ip)

        # 2. YouTube redirect — only for clients with cert installed
        yt_enabled = cfg.get("youtube_redirect_enabled", False)
        yt_ip = cfg.get("youtube_redirect_ip", "")
        yt_domains = {d.lower() for d in cfg.get("youtube_domains", [])}

        if yt_enabled and yt_ip and domain in yt_domains:
            if _is_cert_installed(client_ip):
                self.logger.info("REDIRECTED %s -> %s  (client=%s)", domain, yt_ip, client_ip)
                log_query(client_ip, domain, qtype_str, "youtube")
                return self._redirect_response(request, yt_ip)
            else:
                self.logger.debug("YT-SKIP %s  cert not installed  (client=%s)", domain, client_ip)

        # 3. Blocklist check
        if blocker.is_blocked(domain):
            self.logger.info("BLOCKED  %s -> 0.0.0.0  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            return self._redirect_response(request, "0.0.0.0")

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
            _cache_put(domain, request.q.qtype, reply, upstream)
            _check_auto_block(domain)
            self.logger.info("FORWARDED %s  (client=%s upstream=%s %dms)", domain, client_ip, upstream, elapsed_ms)
            log_query(client_ip, domain, qtype_str, "forwarded", upstream=upstream, response_ms=elapsed_ms)
        elif reply.header.rcode == 3:  # NXDOMAIN
            _nxdomain_update(client_ip)
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


def main():
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

    # Start client block writer + restore previous session blocks
    bw = threading.Thread(target=_block_writer_task, daemon=True, name="block-writer")
    bw.start()
    _load_existing_blocks()
    log.info("Block writer started; existing blocks restored")

    dns_logger = DnsLibLogger(prefix=False)
    resolver = SinkholeResolver()

    udp_server = DNSServer(resolver, port=53, address="0.0.0.0", logger=dns_logger)
    tcp_server = DNSServer(resolver, port=53, address="0.0.0.0", tcp=True, logger=dns_logger)

    udp_server.start_thread()
    tcp_server.start_thread()

    log.info("Listening on 0.0.0.0:53 (UDP+TCP). Upstream: %s", cfg.get("upstream_dns"))
    log.info("Config: %s | Blocklist DB: %s | Query log DB: %s",
             CONFIG_PATH, BLOCKLIST_DB, SINKHOLE_DB)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        udp_server.stop()
        tcp_server.stop()


if __name__ == "__main__":
    main()
