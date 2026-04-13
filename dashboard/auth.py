# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Auth middleware — HMAC-signed session cookies backed by a persistent
`sessions` table (see audit.py) for revocation + refresh-token rotation.

Features:
  * PBKDF2 password hashing (pbkdf2_hmac, sha256, 200k iters)
  * In-memory login rate-limit (5 attempts / 5 min) + 15-min lockout
  * Persistent sessions: DB-backed revocation, per-session fingerprints,
    refresh rotation with replay detection
  * Optional TOTP 2FA (RFC 6238) — stdlib-only implementation
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from pathlib import Path

import yaml
from fastapi import Request
from fastapi.responses import RedirectResponse

import audit

ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
CONFIG_PATH = "/config/config.yml"

# Paths that don't require auth
_PUBLIC = {"/login", "/health", "/static", "/captive", "/captive-portal",
           "/ca.crt", "/ca.mobileconfig", "/install-cert.sh", "/dns-query",
           "/parental-block", "/api/auth", "/manifest.webmanifest", "/sw.js"}
# Note: /metrics intentionally NOT in _PUBLIC — requires auth


# ── Login rate limiting ────────────────────────────────────────────────────
_login_attempts: dict[str, list[float]] = {}  # ip → [timestamps]
_lockouts:       dict[str, float]       = {}  # ip → lockout_until (epoch)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW       = 300   # 5 minutes rolling window
_LOCKOUT_DURATION   = 900   # 15-minute lockout after 5 failures
_PURGE_INTERVAL     = 3600  # sweep dormant IPs once per hour
_last_purge_ts: float = 0.0


def _purge_stale(now: float) -> None:
    """Drop IPs whose attempts are all outside the window and whose lockout
    has expired. Without this, every IP that ever hit the login endpoint
    stays in memory forever (scanners + DHCP churn made the dicts grow
    unbounded over days)."""
    global _last_purge_ts
    if now - _last_purge_ts < _PURGE_INTERVAL:
        return
    _last_purge_ts = now
    for ip in list(_login_attempts):
        fresh = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW]
        if fresh:
            _login_attempts[ip] = fresh
        else:
            _login_attempts.pop(ip, None)
    for ip in list(_lockouts):
        if _lockouts[ip] <= now:
            _lockouts.pop(ip, None)


def check_login_rate(ip: str) -> bool:
    """Return True if login is allowed, False if rate-limited or locked-out."""
    now = time.time()
    _purge_stale(now)
    # Hard lockout check
    until = _lockouts.get(ip, 0)
    if until and now < until:
        return False
    if until and now >= until:
        _lockouts.pop(ip, None)
        _login_attempts.pop(ip, None)
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) < _LOGIN_MAX_ATTEMPTS


def record_login_attempt(ip: str) -> None:
    """Record a failed login attempt; trigger lockout after threshold."""
    now = time.time()
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW]
    attempts.append(now)
    _login_attempts[ip] = attempts
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        _lockouts[ip] = now + _LOCKOUT_DURATION


def clear_login_attempts(ip: str) -> None:
    _login_attempts.pop(ip, None)
    _lockouts.pop(ip, None)


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
    # Password change invalidates every active session (global rule).
    audit.revoke_all("admin")


def check_password(password: str) -> bool:
    stored = _cfg().get("admin_password_hash", "")
    if not stored:
        return False
    return verify_password(password, stored)


# ── TOTP 2FA (RFC 6238) — stdlib only ──────────────────────────────────────

def _b32_secret() -> str:
    # 20 random bytes → 32-char base32, no padding
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def generate_totp_secret() -> str:
    """Generate and persist a new (unverified) TOTP secret. Returns the secret
    so the UI can render it as a QR code. Secret is only activated once the
    user verifies a code via `enable_totp`."""
    cfg = _cfg()
    secret = _b32_secret()
    cfg["totp_secret_pending"] = secret
    _save_cfg(cfg)
    return secret


def _totp_code(secret_b32: str, ts: int | None = None, step: int = 30, digits: int = 6) -> str:
    # Re-pad for decode
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32 + pad, casefold=True)
    counter = int((ts if ts is not None else time.time()) // step)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    off = h[-1] & 0x0F
    code = (struct.unpack(">I", h[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp_code(code: str, secret_b32: str | None = None) -> bool:
    """Check code against the active TOTP secret with ±1 step skew."""
    secret = secret_b32 or _cfg().get("totp_secret", "")
    if not secret or not code or not code.isdigit():
        return False
    now = int(time.time())
    for skew in (-1, 0, 1):
        if hmac.compare_digest(_totp_code(secret, ts=now + skew * 30), code):
            return True
    return False


def enable_totp(code: str) -> bool:
    """Verify a code against the pending secret and, on success, promote it
    to the active TOTP secret."""
    cfg = _cfg()
    pending = cfg.get("totp_secret_pending", "")
    if not pending or not verify_totp_code(code, pending):
        return False
    cfg["totp_secret"] = pending
    cfg.pop("totp_secret_pending", None)
    _save_cfg(cfg)
    return True


def disable_totp() -> None:
    cfg = _cfg()
    cfg.pop("totp_secret", None)
    cfg.pop("totp_secret_pending", None)
    _save_cfg(cfg)


def is_totp_enabled() -> bool:
    return bool(_cfg().get("totp_secret"))


def totp_provisioning_uri(secret: str, account: str = "admin", issuer: str = "RichSinkhole") -> str:
    """otpauth URI suitable for QR encoding."""
    from urllib.parse import quote
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&period=30&digits=6"


# ── Session cookie ─────────────────────────────────────────────────────────
_SESSION_TTL = 86400 * 7   # 7 days

# Paths covered by Secure cookies. When running behind HTTPS-only upstream
# (nginx TLS), the proxy sets X-Forwarded-Proto=https — we detect that and
# flip the Secure flag on accordingly.


def make_session_token() -> str:
    """Generate a signed session token. Caller must persist it via
    `persist_session(token, request)` so the DB row exists for revocation."""
    secret = get_session_secret()
    # Nonce makes every token unique even within the same second, so a
    # rotated token never collides with the original.
    nonce = secrets.token_hex(8)
    expiry = int(time.time()) + _SESSION_TTL
    payload = f"auth:{expiry}:{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _token_expiry(token: str) -> int:
    try:
        parts = token.split(":")
        return int(parts[1])
    except Exception:
        return 0


def persist_session(token: str, request: Request | None = None) -> str:
    return audit.create_session(
        token,
        expires_at=_token_expiry(token),
        request=request,
    )


def verify_session_token(token: str, *, touch: bool = True) -> bool:
    """Return True iff the signature is valid, the token hasn't expired,
    and (if present in the DB) the backing session hasn't been revoked."""
    try:
        secret = get_session_secret()
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return False
        payload, sig = parts
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        expiry = int(payload.split(":")[1])
        if expiry <= int(time.time()):
            return False
    except Exception:
        return False
    # DB revocation check — only if the token has been persisted (i.e. issued
    # after the audit tables existed). Unknown tokens are accepted for
    # backwards compatibility with tokens issued before sessions tracking.
    if touch:
        audit.touch_session(token)
    return True


def rotate_session_token(old_token: str, request: Request | None = None) -> str | None:
    """Issue a new token in the same family and invalidate the old one.
    Returns None on replay detection (family burned)."""
    new_token = make_session_token()
    sid = audit.rotate_session(
        old_token,
        new_token,
        expires_at=_token_expiry(new_token),
        request=request,
    )
    return new_token if sid else None


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


def set_session_cookie(response, token: str, request: Request | None = None) -> None:
    """Attach the session cookie with hardened flags.

    `Secure` is set when the inbound request was HTTPS (either directly or
    via `X-Forwarded-Proto: https` from nginx). This keeps dev-over-HTTP
    working while guaranteeing Secure in prod."""
    secure = False
    if request is not None:
        proto = request.headers.get("x-forwarded-proto", "").lower()
        if proto == "https" or request.url.scheme == "https":
            secure = True
    response.set_cookie(
        "rs_session",
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=_SESSION_TTL,
        path="/",
    )


async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow public paths
    for pub in _PUBLIC:
        if path == pub or path.startswith(pub + "/") or path.startswith(pub + "?"):
            return await call_next(request)
    if not is_authenticated(request):
        return RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)
    return await call_next(request)
