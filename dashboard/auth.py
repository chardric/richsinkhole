# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Simple auth middleware using HMAC-signed session cookies.
Password stored as pbkdf2 hash in config.yml. Zero new dependencies.
"""
import hashlib
import hmac
import os
import secrets
import time
import yaml

ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
from pathlib import Path
from fastapi import Request
from fastapi.responses import RedirectResponse

CONFIG_PATH = "/config/config.yml"

# Paths that don't require auth
_PUBLIC = {"/login", "/health", "/static", "/captive", "/captive-portal",
           "/ca.crt", "/ca.mobileconfig", "/install-cert.sh", "/dns-query",
           "/parental-block", "/api/auth"}
# Note: /metrics intentionally NOT in _PUBLIC — requires auth


# ── Login rate limiting ────────────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = {}  # ip → [timestamps]
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 300  # 5 minutes


def check_login_rate(ip: str) -> bool:
    """Return True if login is allowed, False if rate-limited."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    # Prune old attempts outside the window
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < _LOGIN_MAX_ATTEMPTS


def record_login_attempt(ip: str) -> None:
    """Record a failed login attempt."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    attempts.append(now)
    _login_attempts[ip] = attempts


def _cfg() -> dict:
    try:
        return yaml.safe_load(Path(CONFIG_PATH).read_text()) or {}
    except Exception:
        return {}


def _save_cfg(data: dict):
    Path(CONFIG_PATH).write_text(yaml.dump(data, default_flow_style=False))


def ensure_session_secret():
    cfg = _cfg()
    if not cfg.get("session_secret"):
        cfg["session_secret"] = secrets.token_hex(32)
        _save_cfg(cfg)


def get_session_secret() -> str:
    secret = _cfg().get("session_secret", "")
    if not secret or secret == "changeme":
        # Force generation if missing — never fall back to a weak default
        ensure_session_secret()
        secret = _cfg().get("session_secret", "")
    return secret


# ── Password management ────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2:{salt}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, dk_hex = stored.split(":")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def is_password_set() -> bool:
    return bool(_cfg().get("admin_password_hash"))


def set_password(password: str):
    cfg = _cfg()
    cfg["admin_password_hash"] = hash_password(password)
    _save_cfg(cfg)


def check_password(password: str) -> bool:
    stored = _cfg().get("admin_password_hash", "")
    if not stored:
        return False
    return verify_password(password, stored)


# ── Session cookie ─────────────────────────────────────────────────────────
_SESSION_TTL = 86400 * 7   # 7 days


def make_session_token() -> str:
    secret = get_session_secret()
    expiry = int(time.time()) + _SESSION_TTL
    payload = f"auth:{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_session_token(token: str) -> bool:
    try:
        secret = get_session_secret()
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return False
        payload, sig = parts
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        _, expiry_str = payload.split(":", 1)
        return int(expiry_str) > int(time.time())
    except Exception:
        return False


def is_authenticated(request: Request) -> bool:
    if not is_password_set():
        return True   # no auth configured — open access
    # Cookie auth (web UI)
    token = request.cookies.get("rs_session", "")
    if token and verify_session_token(token):
        return True
    # Bearer token auth (native mobile/desktop apps)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return verify_session_token(token)
    return False


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow public paths
    for pub in _PUBLIC:
        if path == pub or path.startswith(pub + "/") or path.startswith(pub + "?"):
            return await call_next(request)
    if not is_authenticated(request):
        return RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)
    return await call_next(request)
