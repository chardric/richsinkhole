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


@router.get("/health")
async def health_check():
    checks: dict[str, str] = {}

    # DNS server reachable
    checks["dns"] = "ok" if _tcp_ok("dns", 53) else "offline"

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
    checks["yt_proxy"] = "ok" if _tcp_ok("youtube-proxy", 8000) else "offline"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return JSONResponse({"status": overall, **checks}, status_code=200)
