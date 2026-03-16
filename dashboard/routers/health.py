# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import json
import socket

import aiosqlite
from fastapi import APIRouter
from fastapi.responses import JSONResponse

SINKHOLE_DB = "/data/sinkhole.db"
BLOCKLIST_DB = "/data/blocklist.db"
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


@router.get("/health")
async def health_check():
    checks: dict[str, str] = {}

    # DNS server reachable
    checks["dns"] = "ok" if _tcp_ok("localhost", 53) else "offline"

    # SQLite DBs readable
    for label, path in (("dns_db", SINKHOLE_DB), ("blocklist_db", BLOCKLIST_DB)):
        try:
            async with aiosqlite.connect(path) as db:
                await db.execute("SELECT 1")
            checks[label] = "ok"
        except Exception as e:
            checks[label] = f"error: {e}"

    # Updater status
    try:
        with open(STATUS_PATH) as f:
            s = json.load(f)
        checks["updater"] = s.get("status", "unknown")
    except FileNotFoundError:
        checks["updater"] = "never_run"
    except Exception as e:
        checks["updater"] = f"error: {e}"

    # YouTube proxy
    checks["yt_proxy"] = "ok" if _tcp_ok("localhost", 8000) else "offline"

    # NTP server (non-blocking UDP probe)
    checks["ntp"] = "ok" if _ntp_ok() else "offline"

    # Only core services determine overall health; updater/yt_proxy/ntp are non-critical
    critical = {k: v for k, v in checks.items() if k in ("dns", "dns_db", "blocklist_db")}
    overall = "ok" if all(v == "ok" for v in critical.values()) else "degraded"
    return JSONResponse({"status": overall, **checks}, status_code=200)
