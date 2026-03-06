import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

DOCKER_SOCK    = "/var/run/docker.sock"
NTP_CONTAINER  = "richsinkhole-ntp-1"

router = APIRouter()


async def _docker(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
        return await client.request(method, path, **kwargs)


@router.get("/ntp/status")
async def ntp_status():
    if not os.path.exists(DOCKER_SOCK):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        r = await _docker("GET", f"/containers/{NTP_CONTAINER}/json")
        if r.status_code == 404:
            return {"running": False}
        r.raise_for_status()
        return {"running": r.json()["State"]["Running"]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Failed to query NTP container state")


class NtpToggle(BaseModel):
    enabled: bool


@router.post("/ntp/enabled")
async def set_ntp_enabled(body: NtpToggle):
    if not os.path.exists(DOCKER_SOCK):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        action = "start" if body.enabled else "stop"
        r = await _docker("POST", f"/containers/{NTP_CONTAINER}/{action}")
        # 204 = success, 304 = already in that state — both are fine
        if r.status_code not in (204, 304):
            raise HTTPException(status_code=502, detail="Failed to change NTP container state")
        return {"running": body.enabled}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Failed to control NTP container")
