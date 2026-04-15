# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Static routes manager — UI for the YAML config consumed by the host-side
rs-route-reconciler.service.

The container can read/write the YAML at /data/config/extra_routes.yml (the
host bind-mounts data/config/ into /data/config/), but cannot directly inspect
host network interfaces. The reconciler script writes host_interfaces.json
next to the YAML on each run; this router serves that snapshot.
"""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

CONFIG_PATH = Path("/data/config/extra_routes.yml")
SNAPSHOT_PATH = Path("/data/config/host_interfaces.json")

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────────


def _read_routes() -> list[dict]:
    if not CONFIG_PATH.exists():
        return []
    try:
        data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=500, detail=f"config YAML invalid: {exc}")
    out: list[dict] = []
    for r in data.get("routes") or []:
        if isinstance(r, dict) and r.get("net") and r.get("via") and r.get("dev"):
            out.append({"net": str(r["net"]), "via": str(r["via"]), "dev": str(r["dev"])})
    return out


def _write_routes(routes: list[dict]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# RichSinkhole — extra static routes\n"
        "# Managed by the dashboard. Hand-edits are preserved on reload but\n"
        "# comments inside this file are NOT — keep notes elsewhere.\n"
        "#\n"
        "# After save, the host-side rs-route-reconciler service applies the\n"
        "# changes within a few seconds via NetworkManager (persistent across\n"
        "# reboots, no connection bounce).\n\n"
    )
    body = yaml.safe_dump({"routes": routes}, default_flow_style=False, sort_keys=False)
    # Atomic write via tempfile + rename so the path watcher never sees a half-written file.
    tmp = CONFIG_PATH.with_suffix(".yml.tmp")
    tmp.write_text(header + body)
    os.replace(tmp, CONFIG_PATH)


def _validate(net: str, via: str, dev: str) -> tuple[str, str, str]:
    try:
        n = ipaddress.ip_network(net, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid net {net!r}: {exc}")
    try:
        v = ipaddress.ip_address(via)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid via {via!r}: {exc}")
    dev = (dev or "").strip()
    if not dev or not dev.replace(".", "").replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"invalid dev {dev!r}")
    return str(n), str(v), dev


# ── endpoints ────────────────────────────────────────────────────────────────


@router.get("/routes")
async def list_routes():
    return {"routes": _read_routes(), "config_path": str(CONFIG_PATH)}


@router.get("/routes/interfaces")
async def list_interfaces():
    if not SNAPSHOT_PATH.exists():
        return {"interfaces": [], "ts": None,
                "note": "snapshot not yet written — run `sudo systemctl start rs-route-reconciler.service` on the host"}
    try:
        data = json.loads(SNAPSHOT_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"snapshot read failed: {exc}")
    return data


@router.post("/routes/refresh", status_code=202)
async def refresh_snapshot():
    """Touch the YAML so the host's path watcher re-runs the reconciler,
    which refreshes host_interfaces.json. Used by the UI's 'Re-scan' button."""
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config file not present")
    # `os.utime(None)` updates mtime to now and triggers inotify on the host.
    os.utime(CONFIG_PATH, None)
    return {"status": "queued"}


class RouteIn(BaseModel):
    net: str
    via: str
    dev: str


@router.post("/routes", status_code=201)
async def add_route(body: RouteIn):
    net, via, dev = _validate(body.net, body.via, body.dev)
    routes = _read_routes()
    if any(r["net"] == net and r["dev"] == dev for r in routes):
        raise HTTPException(status_code=409, detail=f"route for {net} on {dev} already exists")
    routes.append({"net": net, "via": via, "dev": dev})
    routes.sort(key=lambda r: (r["dev"], ipaddress.ip_network(r["net"])))
    _write_routes(routes)
    return {"net": net, "via": via, "dev": dev, "status": "added"}


@router.delete("/routes")
async def remove_route(net: str, dev: str):
    """Delete by (net, dev) pair — net alone isn't unique because the same
    subnet could (in principle) be reachable via two different interfaces."""
    routes = _read_routes()
    new = [r for r in routes if not (r["net"] == net and r["dev"] == dev)]
    if len(new) == len(routes):
        raise HTTPException(status_code=404, detail=f"no route {net} on {dev}")
    _write_routes(new)
    return {"net": net, "dev": dev, "status": "removed"}
