# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""DNS speed test — latency stats from query_log + live probe."""

import socket
import struct
import time

import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/local/sinkhole.db"

router = APIRouter()

# Well-known domains for live probes
_PROBE_DOMAINS = [
    "google.com", "facebook.com", "cloudflare.com",
    "amazon.com", "microsoft.com",
]


def _dns_probe(domain: str, server: str = "127.0.0.1", port: int = 53, timeout: float = 3.0) -> float | None:
    """Send a raw DNS A query and return response time in ms, or None on failure."""
    # Build a minimal DNS query packet
    txn_id = struct.pack("!H", int(time.monotonic() * 1000) & 0xFFFF)
    flags = b"\x01\x00"        # standard query, recursion desired
    counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"  # 1 question
    qname = b""
    for label in domain.split("."):
        qname += bytes([len(label)]) + label.encode()
    qname += b"\x00"
    qtype = b"\x00\x01"       # A record
    qclass = b"\x00\x01"      # IN
    packet = txn_id + flags + counts + qname + qtype + qclass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            start = time.monotonic()
            s.sendto(packet, (server, port))
            s.recvfrom(512)
            elapsed = (time.monotonic() - start) * 1000
            return round(elapsed, 1)
    except Exception:
        return None


@router.get("/speedtest")
async def dns_speedtest():
    """Return historical DNS latency stats + live probe results."""

    # Historical stats from query_log (last 24h)
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall("""
            SELECT
                COUNT(*) AS total,
                AVG(CASE WHEN response_ms > 0 THEN response_ms END) AS avg_ms,
                MIN(CASE WHEN response_ms > 0 THEN response_ms END) AS min_ms,
                MAX(CASE WHEN response_ms > 0 THEN response_ms END) AS max_ms
            FROM query_log
            WHERE ts >= datetime('now', 'localtime', '-24 hours')
              AND response_ms IS NOT NULL AND response_ms > 0
        """)
        row = rows[0] if rows else (0, None, None, None)
        total = int(row[0] or 0)
        avg_ms = round(float(row[1]), 1) if row[1] else None
        min_ms = round(float(row[2]), 1) if row[2] else None
        max_ms = round(float(row[3]), 1) if row[3] else None

        # p50 / p95 via sorted sample
        percentile_rows = await db.execute_fetchall("""
            SELECT response_ms FROM query_log
            WHERE ts >= datetime('now', 'localtime', '-24 hours')
              AND response_ms IS NOT NULL AND response_ms > 0
            ORDER BY response_ms
        """)
        latencies = [r[0] for r in percentile_rows]
        p50 = round(latencies[len(latencies) // 2], 1) if latencies else None
        p95 = round(latencies[int(len(latencies) * 0.95)], 1) if latencies else None

    # Live probes against local DNS
    probes = []
    for domain in _PROBE_DOMAINS:
        ms = _dns_probe(domain)
        probes.append({"domain": domain, "latency_ms": ms})

    live_avg = None
    live_vals = [p["latency_ms"] for p in probes if p["latency_ms"] is not None]
    if live_vals:
        live_avg = round(sum(live_vals) / len(live_vals), 1)

    return {
        "historical": {
            "total_queries": total,
            "avg_ms": avg_ms,
            "min_ms": min_ms,
            "max_ms": max_ms,
            "p50_ms": p50,
            "p95_ms": p95,
        },
        "live": {
            "probes": probes,
            "avg_ms": live_avg,
        },
    }
