# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import asyncio
import os

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


@router.get("/settings")
async def get_settings():
    cfg = _read_cfg()
    cfg["server_ip"] = _host_ip()
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
    notify_daily: bool = True
    daily_hour: int = 8


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
        "notify_daily":     ec.get("notify_daily", True),
        "daily_hour":       ec.get("daily_hour", 8),
    }


@router.post("/settings/email")
async def save_email_settings(body: EmailSettingsIn):
    cfg = _read_cfg()
    ec = cfg.get("email_notifications", {})

    # Keep existing password if the placeholder was sent back
    password = body.smtp_password
    if password == "••••••••" or password == "":
        password = ec.get("smtp_password", "")

    cfg["email_notifications"] = {
        "enabled":         body.enabled,
        "smtp_host":       body.smtp_host.strip(),
        "smtp_port":       body.smtp_port,
        "smtp_user":       body.smtp_user.strip(),
        "smtp_password":   password,
        "from_addr":       body.from_addr.strip() or body.smtp_user.strip(),
        "to_addr":         body.to_addr.strip(),
        "tls":             body.tls,
        "notify_security": body.notify_security,
        "notify_update":   body.notify_update,
        "notify_daily":    body.notify_daily,
        "daily_hour":      max(0, min(23, body.daily_hour)),
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
