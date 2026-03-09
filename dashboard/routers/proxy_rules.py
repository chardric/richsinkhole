# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Reverse Proxy rule manager.
Writes per-hostname nginx server blocks to /nginx/conf.d/ and reloads nginx
via the Docker HTTP API over the Unix socket. Also auto-creates a local DNS
A record so the hostname resolves to this server on the network.
"""
import os
import re

import aiosqlite
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SINKHOLE_DB    = "/data/sinkhole.db"
NGINX_CONF_DIR = "/nginx/conf.d"
NGINX_CONTAINER = os.getenv("NGINX_CONTAINER", "richsinkhole-nginx-1")
DOCKER_SOCK    = "/var/run/docker.sock"
HOST_IP        = os.getenv("HOST_IP", "")

router = APIRouter()

_ENSURE_TABLE = """
    CREATE TABLE IF NOT EXISTS proxy_rules (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname   TEXT NOT NULL UNIQUE,
        target     TEXT NOT NULL,
        enabled    INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
"""

_ENSURE_DNS_TABLE = """
    CREATE TABLE IF NOT EXISTS dns_records (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT    NOT NULL UNIQUE,
        type     TEXT    NOT NULL DEFAULT 'A',
        value    TEXT    NOT NULL,
        ttl      INTEGER NOT NULL DEFAULT 300,
        enabled  INTEGER NOT NULL DEFAULT 1
    )
"""

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$")
_TARGET_RE   = re.compile(r"^https?://[^\s/$.?#].\S*$")


class ProxyRuleIn(BaseModel):
    hostname: str
    target:   str
    enabled:  bool = True


def _conf_path(rule_id: int) -> str:
    return f"{NGINX_CONF_DIR}/proxy_{rule_id}.conf"


HTTP_PORT = os.getenv("HTTP_PORT", "80")


def _is_self_target(target: str) -> bool:
    """Detect if the proxy target points back to this server (would loop)."""
    if not HOST_IP:
        return False
    from urllib.parse import urlparse
    parsed = urlparse(target)
    host = parsed.hostname or ""
    port = str(parsed.port) if parsed.port else "80"
    return host == HOST_IP and port == HTTP_PORT


def _write_conf(rule_id: int, hostname: str, target: str) -> None:
    os.makedirs(NGINX_CONF_DIR, exist_ok=True)
    # Strip trailing slash from target to avoid double-slash in proxy_pass
    target = target.rstrip("/")

    # If target points back to this server's nginx, generate a dashboard
    # proxy with proper path rewriting to avoid redirect loops
    if _is_self_target(target):
        root_path = os.getenv("ROOT_PATH", "/richsinkhole")
        conf = (
            f"# RichSinkhole proxy: {hostname} -> {target} (self → dashboard)\n"
            f"server {{\n"
            f"    listen 80;\n"
            f"    server_name {hostname};\n\n"
            f"    # Root redirect to dashboard\n"
            f"    location = / {{\n"
            f"        return 301 {root_path}/;\n"
            f"    }}\n\n"
            f"    # Dashboard with prefix strip\n"
            f"    location {root_path}/ {{\n"
            f"        rewrite ^{root_path}/(.*) /$1 break;\n"
            f"        proxy_pass              http://dashboard:8080;\n"
            f"        proxy_http_version      1.1;\n"
            f"        proxy_set_header        Host              $host;\n"
            f"        proxy_set_header        X-Real-IP         $remote_addr;\n"
            f"        proxy_set_header        X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
            f"        proxy_set_header        X-Forwarded-Proto $scheme;\n"
            f"        proxy_set_header        Upgrade           $http_upgrade;\n"
            f"        proxy_set_header        Connection        \"upgrade\";\n"
            f"        proxy_buffering         off;\n"
            f"        proxy_cache             off;\n"
            f"        proxy_read_timeout      86400s;\n"
            f"        chunked_transfer_encoding on;\n"
            f"    }}\n\n"
            f"    # Catch-all for other paths\n"
            f"    location / {{\n"
            f"        proxy_pass              http://dashboard:8080;\n"
            f"        proxy_http_version      1.1;\n"
            f"        proxy_set_header        Host              $host;\n"
            f"        proxy_set_header        X-Real-IP         $remote_addr;\n"
            f"        proxy_set_header        X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
            f"        proxy_set_header        X-Forwarded-Proto $scheme;\n"
            f"    }}\n"
            f"}}\n"
        )
    else:
        conf = (
            f"# RichSinkhole proxy: {hostname} -> {target}\n"
            f"server {{\n"
            f"    listen 80;\n"
            f"    server_name {hostname};\n\n"
            f"    location / {{\n"
            f"        proxy_pass         {target};\n"
            f"        proxy_http_version 1.1;\n"
            f"        proxy_set_header   Host              $host;\n"
            f"        proxy_set_header   X-Real-IP         $remote_addr;\n"
            f"        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
            f"        proxy_set_header   X-Forwarded-Proto $scheme;\n"
            f"        proxy_set_header   Upgrade           $http_upgrade;\n"
            f"        proxy_set_header   Connection        \"upgrade\";\n"
            f"        proxy_read_timeout    60s;\n"
            f"        proxy_connect_timeout 10s;\n"
            f"    }}\n"
            f"}}\n"
        )
    with open(_conf_path(rule_id), "w") as f:
        f.write(conf)


def _delete_conf(rule_id: int) -> None:
    try:
        os.unlink(_conf_path(rule_id))
    except FileNotFoundError:
        pass


async def _nginx_reload() -> bool:
    """Reload nginx via Docker HTTP API over the Unix socket."""
    if not os.path.exists(DOCKER_SOCK):
        return False
    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=10,
        ) as client:
            # 1. Create exec instance
            r = await client.post(
                f"/containers/{NGINX_CONTAINER}/exec",
                json={
                    "Cmd": ["nginx", "-s", "reload"],
                    "AttachStdout": True,
                    "AttachStderr": True,
                },
            )
            if r.status_code != 201:
                return False
            exec_id = r.json()["Id"]
            # 2. Start the exec
            await client.post(
                f"/exec/{exec_id}/start",
                json={"Detach": True},
            )
        return True
    except Exception:
        return False


async def _auto_dns(db, hostname: str) -> None:
    """Insert an A record for this hostname if one doesn't already exist."""
    if not HOST_IP:
        return
    await db.execute(_ENSURE_DNS_TABLE)
    await db.execute(
        "INSERT OR IGNORE INTO dns_records (hostname, type, value, ttl, enabled)"
        " VALUES (?, 'A', ?, 300, 1)",
        (hostname.lower(), HOST_IP),
    )


def _validate(body: ProxyRuleIn) -> None:
    h = body.hostname.strip().lower()
    if not h or not _HOSTNAME_RE.match(h):
        raise HTTPException(status_code=400, detail="Invalid hostname")
    t = body.target.strip()
    if not t or not _TARGET_RE.match(t):
        raise HTTPException(
            status_code=400,
            detail="Target must be a full URL: http://IP:PORT or https://IP:PORT",
        )


@router.get("/proxy-rules")
async def list_proxy_rules():
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        rows = await db.execute_fetchall(
            "SELECT id, hostname, target, enabled, created_at"
            " FROM proxy_rules ORDER BY id"
        )
    return [
        {
            "id":         r[0],
            "hostname":   r[1],
            "target":     r[2],
            "enabled":    bool(r[3]),
            "created_at": r[4],
        }
        for r in rows
    ]


@router.post("/proxy-rules", status_code=201)
async def create_proxy_rule(body: ProxyRuleIn):
    _validate(body)
    hostname = body.hostname.strip().lower()
    target   = body.target.strip()
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        try:
            cur = await db.execute(
                "INSERT INTO proxy_rules (hostname, target, enabled) VALUES (?, ?, ?)",
                (hostname, target, int(body.enabled)),
            )
            rule_id = cur.lastrowid
        except Exception:
            raise HTTPException(status_code=409, detail="Hostname already has a proxy rule")
        await _auto_dns(db, hostname)
        await db.commit()

    if body.enabled:
        _write_conf(rule_id, hostname, target)
        if not await _nginx_reload():
            raise HTTPException(status_code=502, detail="Rule saved but nginx reload failed — check nginx config")

    return {"id": rule_id, "hostname": hostname, "target": target, "enabled": body.enabled}


@router.patch("/proxy-rules/{rule_id}")
async def update_proxy_rule(rule_id: int, body: ProxyRuleIn):
    _validate(body)
    hostname = body.hostname.strip().lower()
    target   = body.target.strip()
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute(_ENSURE_TABLE)
        old_rows = await db.execute_fetchall(
            "SELECT hostname FROM proxy_rules WHERE id=?", (rule_id,)
        )
        if not old_rows:
            raise HTTPException(status_code=404, detail="Rule not found")
        old_hostname = old_rows[0][0]
        await db.execute(
            "UPDATE proxy_rules SET hostname=?, target=?, enabled=? WHERE id=?",
            (hostname, target, int(body.enabled), rule_id),
        )
        if old_hostname != hostname:
            # Remove the old auto-created DNS record for the previous hostname
            await db.execute(
                "DELETE FROM dns_records WHERE hostname=?", (old_hostname,)
            )
        await _auto_dns(db, hostname)
        await db.commit()

    _delete_conf(rule_id)
    if body.enabled:
        _write_conf(rule_id, hostname, target)
    if not await _nginx_reload():
        raise HTTPException(status_code=502, detail="Rule saved but nginx reload failed — check nginx config")

    return {"id": rule_id, "hostname": hostname, "target": target, "enabled": body.enabled}


@router.delete("/proxy-rules/{rule_id}")
async def delete_proxy_rule(rule_id: int):
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        cur = await db.execute("DELETE FROM proxy_rules WHERE id=?", (rule_id,))
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule not found")

    _delete_conf(rule_id)
    await _nginx_reload()
    return {"deleted": rule_id}
