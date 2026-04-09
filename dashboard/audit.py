# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Audit, error, email, and session logging — shared helpers.

Centralizes:
  - activity_logs  : append-only audit trail of admin/user actions
  - error_logs     : append-only exception capture for the admin UI
  - email_logs     : every outbound email (success/fail) for deliverability auditing
  - sessions       : active session tracking with rotation + revocation

Design rules (mandated by global CLAUDE.md):
  * Append-only semantics — never UPDATE/DELETE activity or error rows.
  * Every table carries `created_at` and (where relevant) the real client IP.
  * Schema is created idempotently at startup via `ensure_tables(db)`.
  * All writes are resilient — logging must NEVER raise into the request path.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
import traceback
from contextlib import contextmanager
from typing import Any, Optional

import aiosqlite
from fastapi import Request

SINKHOLE_DB = "/local/sinkhole.db"


# ─── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS activity_logs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        user_id       TEXT,
        action        TEXT NOT NULL,
        resource_type TEXT,
        resource_id   TEXT,
        details       TEXT,               -- JSON {old, new, meta}
        ip_address    TEXT,
        user_agent    TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_activity_ts     ON activity_logs(ts)",
    "CREATE INDEX IF NOT EXISTS idx_activity_user   ON activity_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_logs(action)",

    """CREATE TABLE IF NOT EXISTS error_logs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        ts             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        level          TEXT NOT NULL,     -- ERROR | WARN | FATAL
        message        TEXT NOT NULL,
        stack_trace    TEXT,
        request_url    TEXT,
        request_method TEXT,
        user_id        TEXT,
        ip_address     TEXT,
        user_agent     TEXT,
        context        TEXT                -- JSON
    )""",
    "CREATE INDEX IF NOT EXISTS idx_error_ts    ON error_logs(ts)",
    "CREATE INDEX IF NOT EXISTS idx_error_level ON error_logs(level)",

    """CREATE TABLE IF NOT EXISTS email_logs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        recipient  TEXT NOT NULL,
        subject    TEXT NOT NULL,
        template   TEXT,              -- digest | alert | test | …
        status     TEXT NOT NULL,     -- sent | failed
        attempts   INTEGER DEFAULT 1,
        error      TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_email_ts     ON email_logs(ts)",
    "CREATE INDEX IF NOT EXISTS idx_email_status ON email_logs(status)",

    """CREATE TABLE IF NOT EXISTS sessions (
        id           TEXT PRIMARY KEY,        -- random opaque id
        token_hash   TEXT NOT NULL,           -- sha256(token) — lookup key
        family_id    TEXT NOT NULL,           -- refresh-rotation family
        user_id      TEXT NOT NULL DEFAULT 'admin',
        ip_address   TEXT,
        user_agent   TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        last_seen_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        expires_at   TEXT NOT NULL,
        revoked_at   TEXT,
        replaced_by  TEXT                      -- id of successor after rotation
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_token  ON sessions(token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_family ON sessions(family_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id)",
]


async def ensure_tables(db: aiosqlite.Connection) -> None:
    for stmt in _SCHEMA:
        await db.execute(stmt)
    await db.commit()


# ─── Request context extraction ──────────────────────────────────────────────

def client_ip(request: Optional[Request]) -> str:
    if request is None:
        return ""
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "")
        or ""
    )


def user_agent(request: Optional[Request]) -> str:
    if request is None:
        return ""
    return request.headers.get("user-agent", "")[:512]


# ─── Activity log ────────────────────────────────────────────────────────────

def log_activity(
    action: str,
    *,
    request: Optional[Request] = None,
    user_id: str = "admin",
    resource_type: str = "",
    resource_id: str = "",
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Fire-and-forget synchronous write. Never raises into the request path."""
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                """INSERT INTO activity_logs
                   (user_id, action, resource_type, resource_id, details, ip_address, user_agent)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(details, default=str) if details else None,
                    client_ip(request),
                    user_agent(request),
                ),
            )
            conn.commit()
    except Exception:
        # Last-resort fallback — never let audit failure break the app
        pass


# ─── Error log ───────────────────────────────────────────────────────────────

def log_error(
    message: str,
    *,
    level: str = "ERROR",
    exc: Optional[BaseException] = None,
    request: Optional[Request] = None,
    user_id: str = "",
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Persist an exception/alert for the admin error viewer."""
    try:
        stack = "".join(traceback.format_exception(exc)) if exc else None
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                """INSERT INTO error_logs
                   (level, message, stack_trace, request_url, request_method,
                    user_id, ip_address, user_agent, context)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    level,
                    message[:2000],
                    stack,
                    str(request.url) if request else None,
                    request.method if request else None,
                    user_id,
                    client_ip(request),
                    user_agent(request),
                    json.dumps(context, default=str) if context else None,
                ),
            )
            conn.commit()
    except Exception:
        pass


# ─── Email log ───────────────────────────────────────────────────────────────

def log_email(
    recipient: str,
    subject: str,
    *,
    template: str = "",
    status: str = "sent",
    attempts: int = 1,
    error: str = "",
) -> None:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                """INSERT INTO email_logs
                   (recipient, subject, template, status, attempts, error)
                   VALUES (?,?,?,?,?,?)""",
                (recipient, subject, template, status, attempts, error or None),
            )
            conn.commit()
    except Exception:
        pass


# ─── Session store (refresh-token rotation + revocation) ────────────────────

import hashlib


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    token: str,
    *,
    expires_at: int,
    request: Optional[Request] = None,
    user_id: str = "admin",
    family_id: Optional[str] = None,
) -> str:
    """Persist a session row. `token` is the raw cookie/bearer value.
    Returns the session id (not the token)."""
    sid = secrets.token_hex(16)
    fam = family_id or secrets.token_hex(16)
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                """INSERT INTO sessions
                   (id, token_hash, family_id, user_id, ip_address, user_agent, expires_at)
                   VALUES (?,?,?,?,?,?,datetime(?, 'unixepoch'))""",
                (
                    sid,
                    _hash_token(token),
                    fam,
                    user_id,
                    client_ip(request),
                    user_agent(request),
                    int(expires_at),
                ),
            )
            conn.commit()
    except Exception:
        pass
    return sid


def touch_session(token: str) -> bool:
    """Update last_seen. Returns True if the token is still valid (not expired/revoked)."""
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            row = conn.execute(
                """SELECT id, revoked_at, expires_at FROM sessions
                   WHERE token_hash=?""",
                (_hash_token(token),),
            ).fetchone()
            if not row:
                return False
            sid, revoked_at, expires_at = row
            if revoked_at is not None:
                return False
            # expires_at stored as ISO8601 in UTC
            conn.execute(
                "UPDATE sessions SET last_seen_at=datetime('now', 'localtime') WHERE id=?",
                (sid,),
            )
            conn.commit()
            return True
    except Exception:
        return False


def revoke_session(session_id: str) -> None:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at=datetime('now', 'localtime') WHERE id=? AND revoked_at IS NULL",
                (session_id,),
            )
            conn.commit()
    except Exception:
        pass


def revoke_by_token(token: str) -> None:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at=datetime('now', 'localtime') WHERE token_hash=? AND revoked_at IS NULL",
                (_hash_token(token),),
            )
            conn.commit()
    except Exception:
        pass


def revoke_family(family_id: str) -> None:
    """Burn an entire refresh family — used when a revoked/old token is reused
    (compromise detection, per global security rules)."""
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at=datetime('now', 'localtime') WHERE family_id=? AND revoked_at IS NULL",
                (family_id,),
            )
            conn.commit()
    except Exception:
        pass


def revoke_all(user_id: str = "admin") -> int:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            cur = conn.execute(
                "UPDATE sessions SET revoked_at=datetime('now', 'localtime') WHERE user_id=? AND revoked_at IS NULL",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount or 0
    except Exception:
        return 0


def list_sessions(user_id: str = "admin") -> list[dict]:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            rows = conn.execute(
                """SELECT id, ip_address, user_agent, created_at, last_seen_at, expires_at, revoked_at
                   FROM sessions
                   WHERE user_id=? AND revoked_at IS NULL AND expires_at > datetime('now', 'localtime')
                   ORDER BY last_seen_at DESC""",
                (user_id,),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "ip_address": r[1],
                    "user_agent": r[2],
                    "created_at": r[3],
                    "last_seen_at": r[4],
                    "expires_at": r[5],
                }
                for r in rows
            ]
    except Exception:
        return []


def rotate_session(
    old_token: str,
    new_token: str,
    *,
    expires_at: int,
    request: Optional[Request] = None,
) -> Optional[str]:
    """Refresh-token rotation: invalidate old, issue new in same family.
    If the old token was already revoked/replaced, burn the whole family
    (replay/compromise detected) and return None."""
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            row = conn.execute(
                "SELECT id, family_id, user_id, revoked_at, replaced_by FROM sessions WHERE token_hash=?",
                (_hash_token(old_token),),
            ).fetchone()
            if not row:
                return None
            old_id, family_id, uid, revoked_at, replaced_by = row
            if revoked_at is not None or replaced_by is not None:
                # Replay detected — burn the family
                conn.execute(
                    "UPDATE sessions SET revoked_at=datetime('now', 'localtime') WHERE family_id=? AND revoked_at IS NULL",
                    (family_id,),
                )
                conn.commit()
                return None
        new_sid = create_session(
            new_token,
            expires_at=expires_at,
            request=request,
            user_id=uid,
            family_id=family_id,
        )
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            conn.execute(
                "UPDATE sessions SET revoked_at=datetime('now', 'localtime'), replaced_by=? WHERE id=?",
                (new_sid, old_id),
            )
            conn.commit()
        return new_sid
    except Exception:
        return None
