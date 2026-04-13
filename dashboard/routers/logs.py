# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import asyncio
import json
import time

import aiosqlite
import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

SINKHOLE_DB = "/local/sinkhole.db"
CONFIG_PATH = "/config/config.yml"

# Cap concurrent SSE connections and per-connection lifetime. Prior code
# ran `while True` and held an aiosqlite connection open until the client
# disconnected — a stale browser tab kept the task (and DB handle) alive
# indefinitely.
_STREAM_MAX_CLIENTS = 10
_STREAM_MAX_SECONDS = 3600  # force reconnect after 1h; EventSource auto-retries
_active_streams = 0

router = APIRouter()


def _hidden_ips() -> set:
    """IPs to hide from query logs (routers/infrastructure)."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        return set(cfg.get("rate_limit_exempt_ips", []))
    except Exception:
        return set()


def _row_to_dict(r):
    return {
        "id": r[0], "ts": r[1], "client_ip": r[2], "domain": r[3],
        "qtype": r[4], "action": r[5],
        "upstream": r[6] or "", "response_ms": r[7],
    }


@router.get("/logs")
async def get_logs(limit: int = Query(100, ge=1, le=1000)):
    hidden = _hidden_ips()
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        # Fetch extra rows to compensate for filtered IPs
        fetch_limit = limit * 3 if hidden else limit
        rows = await db.execute_fetchall(
            """SELECT id, ts, client_ip, domain, qtype, action,
                      COALESCE(upstream,''), response_ms
               FROM query_log ORDER BY id DESC LIMIT ?""",
            (fetch_limit,),
        )
    result = []
    for r in rows:
        if r[2] in hidden:
            continue
        result.append(_row_to_dict(r))
        if len(result) >= limit:
            break
    return result


@router.get("/logs/stream")
async def stream_logs():
    global _active_streams
    if _active_streams >= _STREAM_MAX_CLIENTS:
        raise HTTPException(status_code=503, detail="too many active log streams")
    _active_streams += 1

    async def event_generator():
        global _active_streams
        hidden = _hidden_ips()
        started = time.monotonic()
        try:
            async with aiosqlite.connect(SINKHOLE_DB) as db:
                row = (await db.execute_fetchall("SELECT COALESCE(MAX(id), 0) FROM query_log"))[0]
                last_id = row[0]
                while time.monotonic() - started < _STREAM_MAX_SECONDS:
                    rows = await db.execute_fetchall(
                        """SELECT id, ts, client_ip, domain, qtype, action,
                                  COALESCE(upstream,''), response_ms
                           FROM query_log WHERE id > ? ORDER BY id ASC""",
                        (last_id,),
                    )
                    for r in rows:
                        last_id = r[0]
                        if r[2] in hidden:
                            continue
                        yield f"data: {json.dumps(_row_to_dict(r))}\n\n"
                    await asyncio.sleep(0.5)
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            _active_streams = max(0, _active_streams - 1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
