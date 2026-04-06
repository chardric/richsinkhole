# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Admin endpoints for the activity / error / email audit trails.

All three tables are append-only — these endpoints are read-only (SELECT +
CSV export). Every table is paginated and filterable to keep the admin UI
responsive even at 12+ months of retention.
"""
from __future__ import annotations

import csv
import io

import aiosqlite
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()


# ─── Activity logs ───────────────────────────────────────────────────────────

@router.get("/activity-logs")
async def list_activity(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_id: str = "",
    action: str = "",
    search: str = "",
):
    where, params = ["1=1"], []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if action:
        where.append("action = ?")
        params.append(action)
    if search:
        where.append("(action LIKE ? OR resource_type LIKE ? OR resource_id LIKE ? OR details LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])
    where_sql = " AND ".join(where)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        db.row_factory = aiosqlite.Row
        total = (await (await db.execute(
            f"SELECT COUNT(*) FROM activity_logs WHERE {where_sql}", params
        )).fetchone())[0]
        rows = await (await db.execute(
            f"""SELECT id, ts, user_id, action, resource_type, resource_id,
                       details, ip_address, user_agent
                FROM activity_logs
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )).fetchall()
    return {
        "total": total,
        "items": [dict(r) for r in rows],
    }


@router.get("/activity-logs.csv")
async def export_activity():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await (await db.execute(
            """SELECT ts, user_id, action, resource_type, resource_id,
                      ip_address, user_agent, details
               FROM activity_logs ORDER BY id DESC LIMIT 100000"""
        )).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts", "user_id", "action", "resource_type", "resource_id",
                "ip_address", "user_agent", "details"])
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="activity_logs.csv"'},
    )


# ─── Error logs ──────────────────────────────────────────────────────────────

@router.get("/error-logs")
async def list_errors(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    level: str = "",
    search: str = "",
):
    where, params = ["1=1"], []
    if level:
        where.append("level = ?")
        params.append(level)
    if search:
        where.append("(message LIKE ? OR stack_trace LIKE ? OR request_url LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    where_sql = " AND ".join(where)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        db.row_factory = aiosqlite.Row
        total = (await (await db.execute(
            f"SELECT COUNT(*) FROM error_logs WHERE {where_sql}", params
        )).fetchone())[0]
        rows = await (await db.execute(
            f"""SELECT id, ts, level, message, request_url, request_method,
                       user_id, ip_address, user_agent, context, stack_trace
                FROM error_logs
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )).fetchall()
    return {"total": total, "items": [dict(r) for r in rows]}


@router.get("/error-logs.csv")
async def export_errors():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await (await db.execute(
            """SELECT ts, level, message, request_url, request_method,
                      user_id, ip_address, user_agent
               FROM error_logs ORDER BY id DESC LIMIT 100000"""
        )).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts", "level", "message", "url", "method", "user_id", "ip", "user_agent"])
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="error_logs.csv"'},
    )


# ─── Email logs ──────────────────────────────────────────────────────────────

@router.get("/email-logs")
async def list_emails(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        db.row_factory = aiosqlite.Row
        total = (await (await db.execute("SELECT COUNT(*) FROM email_logs")).fetchone())[0]
        rows = await (await db.execute(
            """SELECT id, ts, recipient, subject, template, status, attempts, error
               FROM email_logs ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )).fetchall()
    return {"total": total, "items": [dict(r) for r in rows]}
