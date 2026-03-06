import fnmatch
import re
import sqlite3
import logging
import time
from pathlib import Path

DB_PATH = "/data/blocklist.db"

logger = logging.getLogger(__name__)

# In-memory pattern cache — refreshed every 60 seconds
_pattern_cache: list[re.Pattern] = []
_pattern_cache_time: float = 0.0
_PATTERN_CACHE_TTL = 60


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_blocklist_db():
    """Create blocklist DB schema if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL UNIQUE,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migration: add enabled column if upgrading from older schema
        try:
            conn.execute("ALTER TABLE blocked_patterns ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def _get_pattern_cache() -> list[re.Pattern]:
    global _pattern_cache, _pattern_cache_time
    now = time.monotonic()
    if now - _pattern_cache_time > _PATTERN_CACHE_TTL:
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT pattern FROM blocked_patterns WHERE enabled = 1").fetchall()
            _pattern_cache = [
                re.compile(fnmatch.translate(r[0]), re.IGNORECASE) for r in rows
            ]
            _pattern_cache_time = now
        except Exception as exc:
            logger.warning("Failed to load blocked patterns: %s", exc)
    return _pattern_cache


def seed_from_file(filepath: str):
    """Import domains from a plain text file into blocklist DB."""
    path = Path(filepath)
    if not path.exists():
        logger.warning("Blocklist seed file not found: %s", filepath)
        return

    domains = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                domains.append((line.lower(),))

    with get_connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO blocked_domains (domain) VALUES (?)",
            domains,
        )
        conn.commit()

    logger.info("Seeded %d domains from %s", len(domains), filepath)


def is_blocked(domain: str) -> bool:
    """
    Check if a domain is blocked by:
    1. Exact match or parent-domain match in blocked_domains
    2. Wildcard pattern match in blocked_patterns
    """
    domain = domain.lower().rstrip(".")
    parts = domain.split(".")

    with get_connection() as conn:
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            row = conn.execute(
                "SELECT 1 FROM blocked_domains WHERE domain = ? LIMIT 1",
                (candidate,),
            ).fetchone()
            if row:
                return True

    for regex in _get_pattern_cache():
        if regex.match(domain):
            return True

    return False
