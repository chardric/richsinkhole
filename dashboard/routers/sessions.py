# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Session management + 2FA endpoints.

Lets the admin:
  * List active sessions (device, IP, last-seen)
  * Revoke a specific session (remote logout)
  * Revoke all other sessions at once
  * Enrol / verify / disable TOTP 2FA
"""
from fastapi import APIRouter, Body, HTTPException, Request

import audit
import auth

router = APIRouter()


@router.get("/sessions")
async def list_sessions(request: Request):
    current_token = request.cookies.get("rs_session", "")
    import hashlib
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    items = audit.list_sessions()
    # Mark the one matching the caller's cookie so the UI can show "this device"
    for s in items:
        try:
            import sqlite3
            with sqlite3.connect(audit.SINKHOLE_DB, timeout=5) as conn:
                row = conn.execute(
                    "SELECT token_hash FROM sessions WHERE id=?", (s["id"],),
                ).fetchone()
                s["is_current"] = bool(row and row[0] == current_hash)
        except Exception:
            s["is_current"] = False
    return {"items": items}


@router.delete("/sessions/{session_id}")
async def revoke(session_id: str, request: Request):
    audit.log_activity(
        "session.revoke",
        request=request,
        resource_type="session",
        resource_id=session_id,
    )
    audit.revoke_session(session_id)
    return {"status": "ok"}


@router.post("/sessions/revoke-others")
async def revoke_others(request: Request):
    current_token = request.cookies.get("rs_session", "")
    import hashlib, sqlite3
    current_hash = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    try:
        with sqlite3.connect(audit.SINKHOLE_DB, timeout=5) as conn:
            cur = conn.execute(
                """UPDATE sessions SET revoked_at=datetime('now', 'localtime')
                   WHERE user_id='admin' AND revoked_at IS NULL AND token_hash != ?""",
                (current_hash,),
            )
            conn.commit()
            count = cur.rowcount or 0
    except Exception:
        count = 0
    audit.log_activity("session.revoke_others", request=request, details={"count": count})
    return {"status": "ok", "revoked": count}


# ─── TOTP 2FA ────────────────────────────────────────────────────────────────

@router.get("/2fa/status")
async def totp_status():
    return {"enabled": auth.is_totp_enabled()}


@router.post("/2fa/setup")
async def totp_setup(request: Request):
    """Start enrolment — returns a fresh pending secret + provisioning URI."""
    secret = auth.generate_totp_secret()
    audit.log_activity("2fa.setup_start", request=request)
    return {
        "secret": secret,
        "uri": auth.totp_provisioning_uri(secret),
    }


@router.post("/2fa/enable")
async def totp_enable(request: Request, payload: dict = Body(...)):
    code = str(payload.get("code", ""))
    if not auth.enable_totp(code):
        raise HTTPException(400, "Invalid verification code")
    audit.log_activity("2fa.enable", request=request)
    return {"status": "ok"}


@router.post("/2fa/disable")
async def totp_disable(request: Request, payload: dict = Body(...)):
    password = str(payload.get("password", ""))
    if not auth.check_password(password):
        raise HTTPException(401, "Password incorrect")
    auth.disable_totp()
    audit.log_activity("2fa.disable", request=request)
    return {"status": "ok"}
