"""
DNS-over-HTTPS (RFC 8484) endpoint.
Accepts GET (dns= param) and POST (raw body) and forwards to the DNS container.
Logs queries to sinkhole.db using the real client IP from nginx headers.
"""

import asyncio
import base64
import socket
import sqlite3
from datetime import datetime

from dnslib import DNSRecord, QTYPE
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

DNS_HOST = "dns"
DNS_PORT = 53
SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()


def _real_ip(request: Request) -> str:
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.client.host
    )


def _log_query(client_ip: str, domain: str, qtype: str, action: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with sqlite3.connect(SINKHOLE_DB) as conn:
            conn.execute(
                "INSERT INTO query_log (ts, client_ip, domain, qtype, action) VALUES (?,?,?,?,?)",
                (ts, client_ip, domain, qtype, action),
            )
            conn.commit()
    except Exception:
        pass


def _parse_dns(raw: bytes) -> tuple[str, str]:
    try:
        record = DNSRecord.parse(raw)
        domain = str(record.q.qname).rstrip(".")
        qtype = QTYPE[record.q.qtype]
        return domain, qtype
    except Exception:
        return "unknown", "unknown"


def _action_from_response(raw: bytes) -> str:
    try:
        record = DNSRecord.parse(raw)
        for rr in record.rr:
            if str(rr.rdata) == "0.0.0.0":
                return "blocked"
        return "allowed"
    except Exception:
        return "allowed"


async def _forward_dns(raw: bytes) -> bytes:
    loop = asyncio.get_event_loop()

    def _query() -> bytes:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        try:
            sock.sendto(raw, (DNS_HOST, DNS_PORT))
            data, _ = sock.recvfrom(4096)
            return data
        finally:
            sock.close()

    try:
        return await loop.run_in_executor(None, _query)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"DNS upstream error: {exc}")


@router.get("/dns-query")
async def doh_get(request: Request, dns: str = Query(..., description="Base64url-encoded DNS message")):
    raw = base64.urlsafe_b64decode(dns + "==")
    result = await _forward_dns(raw)
    domain, qtype = _parse_dns(raw)
    _log_query(_real_ip(request), domain, qtype, f"doh:{_action_from_response(result)}")
    return Response(content=result, media_type="application/dns-message")


@router.post("/dns-query")
async def doh_post(request: Request):
    if request.headers.get("content-type") != "application/dns-message":
        raise HTTPException(status_code=415, detail="Content-Type must be application/dns-message")
    raw = await request.body()
    result = await _forward_dns(raw)
    domain, qtype = _parse_dns(raw)
    _log_query(_real_ip(request), domain, qtype, f"doh:{_action_from_response(result)}")
    return Response(content=result, media_type="application/dns-message")
