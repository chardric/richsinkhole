# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import re

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SINKHOLE_DB = "/local/sinkhole.db"

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS schedule_rules (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        label       TEXT    NOT NULL DEFAULT '',
        client_ip   TEXT    NOT NULL DEFAULT '*',
        days        TEXT    NOT NULL DEFAULT '0123456',
        start_time  TEXT    NOT NULL,
        end_time    TEXT    NOT NULL,
        enabled     INTEGER NOT NULL DEFAULT 1
    )
"""

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _days_label(days: str) -> str:
    return ", ".join(_DAY_NAMES[int(d)] for d in sorted(set(days)) if d.isdigit())


class RuleIn(BaseModel):
    label: str = ""
    client_ip: str = "*"
    days: str = "0123456"
    start_time: str
    end_time: str
    enabled: bool = True
    grace_minutes: int = 0   # 0 = instant block, >0 = warn before blocking


@router.get("/schedules")
async def list_schedules():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        # Add grace_minutes column if missing (migration)
        cols = {r[1] for r in await db.execute_fetchall("PRAGMA table_info(schedule_rules)")}
        if "grace_minutes" not in cols:
            await db.execute("ALTER TABLE schedule_rules ADD COLUMN grace_minutes INTEGER DEFAULT 0")
            await db.commit()
        rows = await db.execute_fetchall(
            "SELECT id, label, client_ip, days, start_time, end_time, enabled, COALESCE(grace_minutes,0) FROM schedule_rules ORDER BY id"
        )
    return [
        {
            "id":            r[0],
            "label":         r[1],
            "client_ip":     r[2],
            "days":          r[3],
            "days_label":    _days_label(r[3]),
            "start_time":    r[4],
            "end_time":      r[5],
            "enabled":       bool(r[6]),
            "grace_minutes": r[7],
        }
        for r in rows
    ]


@router.post("/schedules")
async def create_schedule(body: RuleIn):
    _validate(body)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        cur = await db.execute(
            "INSERT INTO schedule_rules (label, client_ip, days, start_time, end_time, enabled, grace_minutes) VALUES (?,?,?,?,?,?,?)",
            (body.label.strip()[:64], body.client_ip.strip(), body.days, body.start_time, body.end_time, int(body.enabled), max(0, min(60, body.grace_minutes))),
        )
        await db.commit()
        rule_id = cur.lastrowid
    return {"id": rule_id, **body.dict()}


@router.patch("/schedules/{rule_id}")
async def update_schedule(rule_id: int, body: RuleIn):
    _validate(body)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute(
            "UPDATE schedule_rules SET label=?, client_ip=?, days=?, start_time=?, end_time=?, enabled=?, grace_minutes=? WHERE id=?",
            (body.label.strip()[:64], body.client_ip.strip(), body.days, body.start_time, body.end_time, int(body.enabled), max(0, min(60, body.grace_minutes)), rule_id),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
    return {"id": rule_id, **body.dict()}


@router.delete("/schedules/{rule_id}")
async def delete_schedule(rule_id: int):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute("DELETE FROM schedule_rules WHERE id=?", (rule_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": rule_id}


def _validate(body: RuleIn):
    if not re.match(r"^\d{2}:\d{2}$", body.start_time) or not re.match(r"^\d{2}:\d{2}$", body.end_time):
        raise HTTPException(status_code=422, detail="Times must be HH:MM")
    if not body.days or not all(c in "0123456" for c in body.days):
        raise HTTPException(status_code=422, detail="days must contain digits 0-6")
    if body.start_time == body.end_time:
        raise HTTPException(status_code=422, detail="start_time and end_time must differ")
