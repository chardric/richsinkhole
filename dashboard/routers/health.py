# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import json
import socket

import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

SINKHOLE_DB = "/local/sinkhole.db"
BLOCKLIST_DB = "/local/blocklist.db"
STATUS_PATH = "/data/updater_status.json"

router = APIRouter()


def _tcp_ok(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False


def _ntp_ok(host: str = "ntp", port: int = 123) -> bool:
    """Send a minimal NTPv3 client packet; return True if a valid response arrives."""
    try:
        # 48-byte NTPv3 client request: LI=0, VN=3, Mode=3
        packet = b"\x1b" + b"\x00" * 47
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2)
            s.sendto(packet, (host, port))
            data, _ = s.recvfrom(1024)
            return len(data) >= 48
    except Exception:
        return False


@router.get("/health/live")
async def health_live():
    """Liveness — process is up. Kubernetes-style: fast, no dependencies."""
    return JSONResponse({"status": "ok"}, status_code=200)


@router.get("/health/ready")
async def health_ready():
    """Readiness — critical deps (DNS + SQLite) are reachable. 503 if not."""
    ok = True
    try:
        async with aiosqlite.connect(SINKHOLE_DB) as db:
            await db.execute("SELECT 1")
        async with aiosqlite.connect(BLOCKLIST_DB) as db:
            await db.execute("SELECT 1")
    except Exception:
        ok = False
    if not _tcp_ok("localhost", 53):
        ok = False
    return JSONResponse({"status": "ok" if ok else "degraded"}, status_code=200 if ok else 503)


@router.get("/health")
async def health_check(request: Request):
    """Public endpoint returns only overall status. Authenticated requests get full details."""
    checks: dict[str, str] = {}

    # DNS server reachable
    checks["dns"] = "ok" if _tcp_ok("localhost", 53) else "offline"

    # SQLite DBs readable
    for label, path in (("dns_db", SINKHOLE_DB), ("blocklist_db", BLOCKLIST_DB)):
        try:
            async with aiosqlite.connect(path) as db:
                await db.execute("SELECT 1")
            checks[label] = "ok"
        except Exception:
            checks[label] = "error"

    # Updater status
    try:
        with open(STATUS_PATH) as f:
            s = json.load(f)
        checks["updater"] = s.get("status", "unknown")
    except FileNotFoundError:
        checks["updater"] = "never_run"
    except Exception:
        checks["updater"] = "error"

    # YouTube proxy
    checks["yt_proxy"] = "ok" if _tcp_ok("localhost", 8000) else "offline"

    # NTP server (non-blocking UDP probe)
    checks["ntp"] = "ok" if _ntp_ok() else "offline"

    # Only core services determine overall health; updater/yt_proxy/ntp are non-critical
    critical = {k: v for k, v in checks.items() if k in ("dns", "dns_db", "blocklist_db")}
    overall = "ok" if all(v == "ok" for v in critical.values()) else "degraded"

    # Public: only overall status (for Docker HEALTHCHECK / uptime monitors)
    # Authenticated: full service breakdown
    from auth import is_authenticated
    if is_authenticated(request):
        return JSONResponse({"status": overall, **checks}, status_code=200)
    return JSONResponse({"status": overall}, status_code=200)
