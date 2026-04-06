# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

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


@router.get("/ntp/clients")
async def ntp_clients():
    """List devices syncing with the NTP server via chronyc clients."""
    if not os.path.exists(DOCKER_SOCK):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    try:
        # Create exec instance
        r = await _docker("POST", f"/containers/{NTP_CONTAINER}/exec", json={
            "AttachStdout": True, "AttachStderr": True,
            "Cmd": ["chronyc", "-c", "clients"],
        })
        if r.status_code != 201:
            return {"clients": []}
        exec_id = r.json()["Id"]

        # Start exec and read output
        r2 = await _docker("POST", f"/exec/{exec_id}/start", json={"Detach": False})
        output = r2.text.strip()

        import ipaddress
        import re
        _DOCKER_NETS = (
            ipaddress.ip_network("172.17.0.0/16"),
            ipaddress.ip_network("172.18.0.0/16"),
            ipaddress.ip_network("172.19.0.0/16"),
        )

        clients = []
        for line in output.splitlines():
            # CSV format: hostname,ntp_packets,ntp_drop,ntp_interval,ntp_intl,ntp_last,...
            parts = line.split(",")
            if len(parts) < 6:
                continue
            # Extract IP — strip any Docker exec stream header bytes
            raw_host = parts[0].strip()
            ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", raw_host)
            if not ip_match:
                continue
            hostname = ip_match.group(1)
            # Skip Docker internal IPs
            try:
                addr = ipaddress.ip_address(hostname)
                if any(addr in net for net in _DOCKER_NETS) or addr.is_loopback:
                    continue
            except ValueError:
                continue
            ntp_packets = int(parts[1]) if parts[1].strip().isdigit() else 0
            if ntp_packets == 0:
                continue  # never synced via NTP
            last_ago = parts[5].strip()  # seconds since last NTP request
            try:
                last_secs = int(last_ago)
            except (ValueError, TypeError):
                last_secs = -1
            clients.append({
                "ip": hostname,
                "ntp_packets": ntp_packets,
                "last_sync_ago": last_secs,
            })

        # Enrich with device labels from sinkhole DB
        try:
            import aiosqlite
            async with aiosqlite.connect("/local/sinkhole.db") as db:
                for c in clients:
                    row = await db.execute_fetchall(
                        "SELECT label, device_type FROM device_fingerprints WHERE ip=?", (c["ip"],)
                    )
                    if row:
                        c["label"] = row[0][0] or ""
                        c["device_type"] = row[0][1] or ""
                    else:
                        c["label"] = ""
                        c["device_type"] = ""
        except Exception:
            pass

        clients.sort(key=lambda x: -x["ntp_packets"])
        return {"clients": clients}
    except HTTPException:
        raise
    except Exception:
        return {"clients": []}


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
