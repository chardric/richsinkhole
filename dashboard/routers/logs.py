import asyncio
import json

import aiosqlite
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()


def _row_to_dict(r):
    return {
        "id": r[0], "ts": r[1], "client_ip": r[2], "domain": r[3],
        "qtype": r[4], "action": r[5],
        "upstream": r[6] or "", "response_ms": r[7],
    }


@router.get("/logs")
async def get_logs(limit: int = Query(100, ge=1, le=1000)):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(
            """SELECT id, ts, client_ip, domain, qtype, action,
                      COALESCE(upstream,''), response_ms
               FROM query_log ORDER BY id DESC LIMIT ?""",
            (limit,),
        )
    return [_row_to_dict(r) for r in rows]


@router.get("/logs/stream")
async def stream_logs():
    async def event_generator():
        async with aiosqlite.connect(SINKHOLE_DB) as db:
            row = (await db.execute_fetchall("SELECT COALESCE(MAX(id), 0) FROM query_log"))[0]
            last_id = row[0]
            try:
                while True:
                    rows = await db.execute_fetchall(
                        """SELECT id, ts, client_ip, domain, qtype, action,
                                  COALESCE(upstream,''), response_ms
                           FROM query_log WHERE id > ? ORDER BY id ASC""",
                        (last_id,),
                    )
                    for r in rows:
                        last_id = r[0]
                        yield f"data: {json.dumps(_row_to_dict(r))}\n\n"
                    await asyncio.sleep(0.5)
            except (asyncio.CancelledError, GeneratorExit):
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
