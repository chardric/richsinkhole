# Bounded reads of /var/log/rs-lite/dnsmasq.log for the dashboard.
# dnsmasq query lines look like:
#   Apr 20 12:15:01 dnsmasq[1234]: query[A] example.com from 10.0.0.5
#   Apr 20 12:15:01 dnsmasq[1234]: config example.com is 0.0.0.0
#
# We only need: domain, client_ip, blocked? — and we have to do it without
# OOMing on a 512 MB box. So: tail at most QUERYLOG_MAX_BYTES and stop after
# QUERYLOG_MAX_LINES.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

from __future__ import annotations

import os
import re
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

from . import config

_RE_QUERY  = re.compile(r"query\[[A-Z0-9]+\]\s+(\S+)\s+from\s+(\S+)")
_RE_CONFIG = re.compile(r"config\s+(\S+)\s+is\s+0\.0\.0\.0")


@dataclass
class Entry:
    ts:        str
    domain:    str
    client_ip: str
    blocked:   bool


def _tail_bytes(path: Path, max_bytes: int) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    if size <= max_bytes:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    with open(path, "rb") as f:
        f.seek(size - max_bytes, os.SEEK_SET)
        # Drop the (probably partial) first line.
        f.readline()
        return f.read().decode("utf-8", errors="replace")


def parse_recent(max_lines: int | None = None) -> list[Entry]:
    """Return the most-recent entries (oldest first), capped at max_lines."""
    cap = max_lines or config.QUERYLOG_MAX_LINES
    text = _tail_bytes(config.DNSMASQ_LOG, config.QUERYLOG_MAX_BYTES)
    if not text:
        return []

    queries: dict[str, tuple[str, str]] = {}  # domain -> (ts, client_ip)
    blocked: set[str] = set()
    ring: deque[Entry] = deque(maxlen=cap)

    for raw in text.splitlines():
        # Crude TS = first 15 chars of syslog line ("Apr 20 12:15:01")
        ts = raw[:15] if len(raw) >= 15 else ""
        m = _RE_QUERY.search(raw)
        if m:
            domain, client_ip = m.group(1), m.group(2)
            queries[domain] = (ts, client_ip)
            continue
        m = _RE_CONFIG.search(raw)
        if m:
            domain = m.group(1)
            blocked.add(domain)
            ts_q, client_ip = queries.get(domain, (ts, "?"))
            ring.append(Entry(ts_q, domain, client_ip, True))
            continue

    # Allowed entries: emit any query that we never saw a 0.0.0.0 config for.
    for domain, (ts_q, client_ip) in queries.items():
        if domain not in blocked:
            ring.append(Entry(ts_q, domain, client_ip, False))

    return list(ring)


def summarize(entries: list[Entry], top_n: int = 20) -> dict:
    blocked_doms = Counter(e.domain for e in entries if e.blocked)
    clients      = Counter(e.client_ip for e in entries)
    return {
        "total":         len(entries),
        "total_blocked": sum(1 for e in entries if e.blocked),
        "top_blocked":   blocked_doms.most_common(top_n),
        "top_clients":   clients.most_common(top_n),
    }
