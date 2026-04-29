# SQLite state DB helper for the Lite variant.
# Single tiny DB: settings, allowlist, services_off.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS allowlist (
    domain     TEXT PRIMARY KEY,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS services_blocked (
    service_id TEXT PRIMARY KEY,
    blocked_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db(path: Path | None = None) -> None:
    p = Path(path) if path else config.STATE_DB
    p.parent.mkdir(parents=True, exist_ok=True)
    with connect(p) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def connect(path: Path | None = None):
    p = Path(path) if path else config.STATE_DB
    conn = sqlite3.connect(p, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=datetime('now')",
            (key, value),
        )


def list_allowlist() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT domain, note, created_at FROM allowlist ORDER BY domain"
        ).fetchall()]


def add_allow(domain: str, note: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO allowlist(domain, note) VALUES(?, ?)",
            (domain.strip().lower(), note),
        )


def remove_allow(domain: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM allowlist WHERE domain = ?",
            (domain.strip().lower(),),
        )


def blocked_service_ids() -> set[str]:
    with connect() as conn:
        return {r["service_id"] for r in conn.execute(
            "SELECT service_id FROM services_blocked"
        ).fetchall()}


def block_service(service_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO services_blocked(service_id) VALUES(?)",
            (service_id,),
        )


def unblock_service(service_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "DELETE FROM services_blocked WHERE service_id = ?",
            (service_id,),
        )
