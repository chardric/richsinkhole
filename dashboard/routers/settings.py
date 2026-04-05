# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import asyncio
import os
import sqlite3
import time
import threading

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

CONFIG_PATH = "/config/config.yml"

router = APIRouter()


def _read_cfg() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Config file not available")


def _host_ip() -> str:
    return os.environ.get("HOST_IP", "")


_SENSITIVE_KEYS = {
    "session_secret", "admin_password_hash",
}

@router.get("/settings")
async def get_settings():
    cfg = _read_cfg()
    cfg["server_ip"] = _host_ip()
    # Strip sensitive fields
    for k in _SENSITIVE_KEYS:
        cfg.pop(k, None)
    # Mask SMTP password
    email = cfg.get("email_notifications")
    if isinstance(email, dict) and email.get("smtp_password"):
        email["smtp_password"] = "••••••••"
    return cfg


class SettingsIn(BaseModel):
    youtube_redirect_enabled: bool
    captive_portal_enabled: bool


@router.post("/settings")
async def save_settings(body: SettingsIn):
    ip = _host_ip()
    if not ip:
        raise HTTPException(status_code=400, detail="HOST_IP is not set on the server")

    cfg = _read_cfg()
    cfg["youtube_redirect_enabled"] = body.youtube_redirect_enabled
    cfg["youtube_redirect_ip"] = ip
    cfg["captive_portal_enabled"] = body.captive_portal_enabled
    cfg["captive_portal_ip"] = ip

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    return {"status": "saved"}


# ── Email notification settings ───────────────────────────────────────────────

class EmailSettingsIn(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""   # empty string = keep existing password
    from_addr: str = ""
    to_addr: str = ""
    tls: bool = True
    notify_security: bool = True
    notify_update: bool = True
    notify_digest: bool = False
    digest_frequency: str = "weekly"      # weekly | monthly | yearly
    digest_hour: int = 8                  # 0-23
    digest_day_of_week: int = 0           # 0=Mon … 6=Sun (for weekly)
    digest_day_of_month: int = 1          # 1-28 (for monthly/yearly)


@router.get("/settings/email")
async def get_email_settings():
    cfg = _read_cfg()
    ec = cfg.get("email_notifications", {})
    return {
        "enabled":          ec.get("enabled", False),
        "smtp_host":        ec.get("smtp_host", ""),
        "smtp_port":        ec.get("smtp_port", 587),
        "smtp_user":        ec.get("smtp_user", ""),
        "smtp_password":    "••••••••" if ec.get("smtp_password") else "",
        "from_addr":        ec.get("from_addr", ""),
        "to_addr":          ec.get("to_addr", ""),
        "tls":              ec.get("tls", True),
        "notify_security":  ec.get("notify_security", True),
        "notify_update":    ec.get("notify_update", True),
        "notify_digest":      ec.get("notify_digest", False),
        "digest_frequency":   ec.get("digest_frequency", "weekly"),
        "digest_hour":        ec.get("digest_hour", ec.get("daily_hour", 8)),
        "digest_day_of_week": ec.get("digest_day_of_week", 0),
        "digest_day_of_month":ec.get("digest_day_of_month", 1),
    }


@router.post("/settings/email")
async def save_email_settings(body: EmailSettingsIn):
    cfg = _read_cfg()
    ec = cfg.get("email_notifications", {})

    # Keep existing password if the placeholder was sent back
    password = body.smtp_password
    if password == "••••••••" or password == "":
        password = ec.get("smtp_password", "")

    freq = body.digest_frequency
    if freq not in ("weekly", "monthly", "yearly"):
        raise HTTPException(status_code=400, detail="digest_frequency must be weekly, monthly, or yearly")

    cfg["email_notifications"] = {
        "enabled":           body.enabled,
        "smtp_host":         body.smtp_host.strip(),
        "smtp_port":         body.smtp_port,
        "smtp_user":         body.smtp_user.strip(),
        "smtp_password":     password,
        "from_addr":         body.from_addr.strip() or body.smtp_user.strip(),
        "to_addr":           body.to_addr.strip(),
        "tls":               body.tls,
        "notify_security":   body.notify_security,
        "notify_update":     body.notify_update,
        "notify_digest":     body.notify_digest,
        "digest_frequency":  freq,
        "digest_hour":       max(0, min(23, body.digest_hour)),
        "digest_day_of_week":  max(0, min(6, body.digest_day_of_week)),
        "digest_day_of_month": max(1, min(28, body.digest_day_of_month)),
    }

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    return {"status": "saved"}


@router.post("/settings/email/test")
async def test_email():
    from notifier import send_async, _test_html
    plain = (
        "Test — RichSinkhole notifications are working\n\n"
        "If you received this, your email settings are configured correctly.\n\n"
        "— RichSinkhole"
    )
    try:
        await send_async("Test — Notifications are working", plain, _test_html(), force=True)
    except Exception as exc:
        # Sanitize: include the exception type but not internal details that may contain credentials
        raise HTTPException(status_code=400, detail=f"Email delivery failed: {type(exc).__name__}")
    return {"status": "sent"}


@router.post("/settings/email/clear-password")
async def clear_email_password():
    """Wipe the stored SMTP password so a new one can be saved."""
    cfg = _read_cfg()
    ec  = cfg.get("email_notifications", {})
    ec["smtp_password"] = ""
    cfg["email_notifications"] = ec
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    return {"status": "cleared"}


# ── Rate limit settings ───────────────────────────────────────────────────────

_RL_DEFAULTS = {
    "rate_window":      10,
    "rate_max":         100,
    "burst_max_normal": 30,
    "burst_max_iot":    10,
    "block_duration":   300,
}


@router.get("/settings/rate-limits")
async def get_rate_limits():
    cfg = _read_cfg()
    result = {k: int(cfg.get(k, v)) for k, v in _RL_DEFAULTS.items()}
    result["rate_limit_exempt_ips"] = cfg.get("rate_limit_exempt_ips", [])
    return result


class RateLimitsIn(BaseModel):
    rate_window:      int = 10
    rate_max:         int = 100
    burst_max_normal: int = 30
    burst_max_iot:    int = 10
    block_duration:   int = 300
    rate_limit_exempt_ips: list[str] = []


@router.post("/settings/rate-limits")
async def save_rate_limits(body: RateLimitsIn):
    # Validate ranges
    if not (1 <= body.rate_window <= 60):
        raise HTTPException(status_code=400, detail="rate_window must be 1–60 seconds")
    if not (10 <= body.rate_max <= 1000):
        raise HTTPException(status_code=400, detail="rate_max must be 10–1000")
    if not (5 <= body.burst_max_normal <= 500):
        raise HTTPException(status_code=400, detail="burst_max_normal must be 5–500")
    if not (2 <= body.burst_max_iot <= 100):
        raise HTTPException(status_code=400, detail="burst_max_iot must be 2–100")
    if not (30 <= body.block_duration <= 86400):
        raise HTTPException(status_code=400, detail="block_duration must be 30–86400 seconds")

    cfg = _read_cfg()
    cfg.update({
        "rate_window":      body.rate_window,
        "rate_max":         body.rate_max,
        "burst_max_normal": body.burst_max_normal,
        "burst_max_iot":    body.burst_max_iot,
        "block_duration":   body.block_duration,
        "rate_limit_exempt_ips": [ip.strip() for ip in body.rate_limit_exempt_ips if ip.strip()],
    })
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    return {"status": "saved"}


# ── Blocklist update schedule ─────────────────────────────────────────────────

_VALID_MINUTES    = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
_VALID_FREQS      = {"daily", "weekly", "monthly"}


@router.get("/settings/update-schedule")
async def get_update_schedule():
    cfg = _read_cfg()
    return {
        "update_hour":            int(cfg.get("update_hour",            3)),
        "update_minute":          int(cfg.get("update_minute",          0)),
        "update_frequency":       str(cfg.get("update_frequency",       "daily")),
        "update_day_of_week":     int(cfg.get("update_day_of_week",     0)),   # 0=Mon … 6=Sun
        "update_day_of_month":    int(cfg.get("update_day_of_month",    1)),   # 1-28
        "source_stale_days":      int(cfg.get("source_stale_days",      90)),  # auto-disable after N days
    }


class UpdateScheduleIn(BaseModel):
    update_hour:         int = 3
    update_minute:       int = 0
    update_frequency:    str = "daily"
    update_day_of_week:  int = 0
    update_day_of_month: int = 1
    source_stale_days:   int = 90


@router.post("/settings/update-schedule")
async def save_update_schedule(body: UpdateScheduleIn):
    if not (0 <= body.update_hour <= 23):
        raise HTTPException(status_code=400, detail="update_hour must be 0–23")
    if body.update_minute not in _VALID_MINUTES:
        raise HTTPException(status_code=400, detail="update_minute must be a multiple of 5 (0–55)")
    if body.update_frequency not in _VALID_FREQS:
        raise HTTPException(status_code=400, detail="update_frequency must be daily, weekly, or monthly")
    if not (0 <= body.update_day_of_week <= 6):
        raise HTTPException(status_code=400, detail="update_day_of_week must be 0–6")
    if not (1 <= body.update_day_of_month <= 28):
        raise HTTPException(status_code=400, detail="update_day_of_month must be 1–28")
    if not (30 <= body.source_stale_days <= 365):
        raise HTTPException(status_code=400, detail="source_stale_days must be 30–365")

    cfg = _read_cfg()
    cfg["update_hour"]         = body.update_hour
    cfg["update_minute"]       = body.update_minute
    cfg["update_frequency"]    = body.update_frequency
    cfg["update_day_of_week"]  = body.update_day_of_week
    cfg["update_day_of_month"] = body.update_day_of_month
    cfg["source_stale_days"]   = body.source_stale_days
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    return {"status": "saved"}


# ── Tuya Pairing Mode ───────────────────────────────────────────────────────

BLOCKLIST_DB = "/local/blocklist.db"

_TUYA_DOMAINS = [
    "iotbing.com", "tuya.com", "tuyacn.com", "tuyaeu.com",
    "tuyaus.com", "smartlife.com", "smart-life.com", "voltsmart.com",
]

_pairing_timer: threading.Timer | None = None
_pairing_active = False


def _end_pairing() -> None:
    """Re-block Tuya domains after timeout."""
    global _pairing_active
    try:
        with sqlite3.connect(BLOCKLIST_DB, timeout=30) as conn:
            for d in _TUYA_DOMAINS:
                conn.execute(
                    "INSERT OR IGNORE INTO blocked_domains (domain, source) VALUES (?, 'custom')",
                    (d,),
                )
            conn.commit()
    except Exception:
        pass
    _pairing_active = False


@router.get("/settings/pairing-mode")
async def get_pairing_mode():
    return {"active": _pairing_active}


class PairingModeIn(BaseModel):
    enabled: bool
    duration_minutes: int = 30


@router.post("/settings/pairing-mode")
async def set_pairing_mode(body: PairingModeIn):
    global _pairing_timer, _pairing_active

    if body.enabled:
        if not (5 <= body.duration_minutes <= 120):
            raise HTTPException(400, "Duration must be 5-120 minutes")

        # Unblock Tuya domains
        try:
            with sqlite3.connect(BLOCKLIST_DB, timeout=30) as conn:
                for d in _TUYA_DOMAINS:
                    conn.execute("DELETE FROM blocked_domains WHERE domain=?", (d,))
                conn.commit()
        except Exception as exc:
            raise HTTPException(500, "Failed to unblock Tuya domains")

        # Cancel existing timer
        if _pairing_timer:
            _pairing_timer.cancel()

        # Set auto-reblock timer
        _pairing_timer = threading.Timer(body.duration_minutes * 60, _end_pairing)
        _pairing_timer.daemon = True
        _pairing_timer.start()
        _pairing_active = True

        return {"status": "enabled", "expires_in_minutes": body.duration_minutes}

    else:
        # Manually disable — re-block immediately
        if _pairing_timer:
            _pairing_timer.cancel()
            _pairing_timer = None
        _end_pairing()
        return {"status": "disabled"}
