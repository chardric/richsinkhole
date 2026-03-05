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
