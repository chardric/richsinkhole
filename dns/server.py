#!/usr/bin/env python3
"""
RichSinkhole DNS Server
UDP/TCP DNS server with blocklist enforcement and SQLite query logging.
"""

import logging
import os
import shutil
import socket
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml
from dnslib import RR, QTYPE, A
from dnslib.server import DNSServer, BaseResolver, DNSLogger as DnsLibLogger

import blocker

# Well-known captive portal detection domains for iOS, Android, Windows, macOS, Linux
CAPTIVE_PORTAL_DOMAINS = {
    "captive.apple.com",
    "www.apple.com",
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
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                client_ip TEXT    NOT NULL,
                domain    TEXT    NOT NULL,
                qtype     TEXT    NOT NULL,
                action    TEXT    NOT NULL  -- 'blocked', 'allowed', or 'redirected'
            )
        """)
        conn.commit()


def log_query(client_ip: str, domain: str, qtype: str, action: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(SINKHOLE_DB) as conn:
            conn.execute(
                "INSERT INTO query_log (ts, client_ip, domain, qtype, action) VALUES (?,?,?,?,?)",
                (ts, client_ip, domain, qtype, action),
            )
            conn.commit()
    except Exception as exc:
        logging.getLogger(__name__).error("Failed to log query: %s", exc)


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

        # 1. Captive portal detection domains (highest priority)
        cp_enabled = cfg.get("captive_portal_enabled", False)
        cp_ip = cfg.get("captive_portal_ip") or cfg.get("youtube_redirect_ip", "")
        if cp_enabled and cp_ip and domain in CAPTIVE_PORTAL_DOMAINS:
            self.logger.info("CAPTIVE  %s -> %s  (client=%s)", domain, cp_ip, client_ip)
            log_query(client_ip, domain, qtype_str, "redirected")
            return self._redirect_response(request, cp_ip)

        # 2. YouTube redirect — only for clients with cert installed
        yt_enabled = cfg.get("youtube_redirect_enabled", False)
        yt_ip = cfg.get("youtube_redirect_ip", "")
        yt_domains = {d.lower() for d in cfg.get("youtube_domains", [])}

        if yt_enabled and yt_ip and domain in yt_domains:
            if _is_cert_installed(client_ip):
                self.logger.info("REDIRECTED %s -> %s  (client=%s)", domain, yt_ip, client_ip)
                log_query(client_ip, domain, qtype_str, "redirected")
                return self._redirect_response(request, yt_ip)
            else:
                self.logger.debug("YT-SKIP %s  cert not installed  (client=%s)", domain, client_ip)

        # 3. Blocklist check
        if blocker.is_blocked(domain):
            self.logger.info("BLOCKED  %s -> 0.0.0.0  (client=%s)", domain, client_ip)
            log_query(client_ip, domain, qtype_str, "blocked")
            return self._redirect_response(request, "0.0.0.0")

        # 4. Forward to upstream
        upstream = cfg.get("upstream_dns", "1.1.1.1")
        reply = self._forward(request, upstream)
        if reply.header.rcode == 0:
            self.logger.info("FORWARDED %s  (client=%s upstream=%s)", domain, client_ip, upstream)
            log_query(client_ip, domain, qtype_str, "forwarded")
        else:
            self.logger.warning("FAILED   %s  rcode=%d  (client=%s upstream=%s)", domain, reply.header.rcode, client_ip, upstream)
            log_query(client_ip, domain, qtype_str, "failed")
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

    def _forward(self, request, upstream: str):
        try:
            raw = request.pack()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(raw, (upstream, 53))
            data, _ = sock.recvfrom(4096)
            sock.close()
            from dnslib import DNSRecord
            return DNSRecord.parse(data)
        except Exception as exc:
            self.logger.error("Upstream DNS error for %s: %s", request.q.qname, exc)
            reply = request.reply()
            reply.header.rcode = 2  # SERVFAIL
            return reply


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
