# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Service Controls — restart core containers (Sinkhole, Unbound, Nginx)
via Docker HTTP API over the Unix socket.
"""
import os

import httpx
from fastapi import APIRouter, HTTPException

DOCKER_SOCK = "/var/run/docker.sock"

_CONTAINERS = {
    "sinkhole": "richsinkhole-sinkhole-1",
    "unbound":  "richsinkhole-unbound-1",
    "nginx":    "richsinkhole-nginx-1",
    "ntp":      "richsinkhole-ntp-1",
}

router = APIRouter()


async def _docker(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=30,
    ) as client:
        return await client.request(method, path, **kwargs)


@router.get("/services/status")
async def services_status():
    if not os.path.exists(DOCKER_SOCK):
        raise HTTPException(503, "Docker socket not available")
    out = {}
    for key, name in _CONTAINERS.items():
        try:
            r = await _docker("GET", f"/containers/{name}/json")
            if r.status_code == 404:
                out[key] = {"running": False, "status": "not found", "uptime": ""}
                continue
            info = r.json()
            state = info["State"]
            out[key] = {
                "running": state["Running"],
                "status": state.get("Status", "unknown"),
                "started_at": state.get("StartedAt", ""),
            }
        except Exception:
            out[key] = {"running": False, "status": "error", "uptime": ""}
    return out


@router.post("/services/restart/{service}")
async def restart_service(service: str):
    if service not in _CONTAINERS:
        raise HTTPException(400, f"Unknown service: {service}")
    if not os.path.exists(DOCKER_SOCK):
        raise HTTPException(503, "Docker socket not available")
    container = _CONTAINERS[service]
    try:
        r = await _docker("POST", f"/containers/{container}/restart", params={"t": 5})
        if r.status_code == 204:
            return {"service": service, "restarted": True}
        if r.status_code == 404:
            raise HTTPException(404, f"Container {service} not found")
        raise HTTPException(502, f"Restart failed (HTTP {r.status_code})")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"Failed to restart {service}: {e}")
