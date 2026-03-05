import sqlite3
import logging
from pathlib import Path

DB_PATH = "/data/blocklist.db"

logger = logging.getLogger(__name__)


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
        conn.commit()


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
    Check if a domain or any of its parent domains is blocked.
    e.g. 'sub.doubleclick.net' matches block on 'doubleclick.net'
    """
    domain = domain.lower().rstrip(".")
    parts = domain.split(".")

    with get_connection() as conn:
        # Check exact match and all parent domains
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            row = conn.execute(
                "SELECT 1 FROM blocked_domains WHERE domain = ? LIMIT 1",
                (candidate,),
            ).fetchone()
            if row:
                return True

    return False
