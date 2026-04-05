# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.
"""
Device Probe — discovers device hostnames via unicast mDNS and NetBIOS.

Works for devices behind VLANs because both protocols use regular UDP
(not multicast/broadcast). The sinkhole sends a unicast query directly to
the device IP and parses the response.

Coverage:
  - mDNS (port 5353): Apple (iPhone/iPad/Mac/HomePod/Apple TV), Chromecast,
    Google Home, most modern printers, some Android devices, Roku, Smart TVs
  - NetBIOS (port 137): Windows PCs, Samba servers

No external dependencies — uses stdlib socket and struct.
"""

import logging
import random
import re
import socket
import struct
import threading
import time

logger = logging.getLogger("device-probe")

_probe_queue: set[str] = set()
_probe_seen: dict[str, float] = {}   # ip → last probe timestamp
_probe_lock = threading.Lock()

_PROBE_INTERVAL = 86400.0  # re-probe each device at most once per 24h
_PROBE_TIMEOUT = 2.0       # UDP response timeout

# Only accept RFC-valid hostnames from probe responses
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{1,61}[a-zA-Z0-9]$")


def _is_valid_hostname(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 63:
        return False
    return bool(_HOSTNAME_RE.match(name))


# ── mDNS unicast probe ─────────────────────────────────────────────────────

def _build_mdns_query(qname: str) -> bytes:
    """Build a DNS query packet for an mDNS PTR lookup."""
    tid = random.randint(0, 0xFFFF)
    # Header: ID, flags (standard query), 1 question, 0 answers/auth/add
    header = struct.pack(">HHHHHH", tid, 0x0000, 1, 0, 0, 0)
    # Encode qname as sequence of length-prefixed labels
    qname_enc = b""
    for label in qname.split("."):
        if label:
            qname_enc += bytes([len(label)]) + label.encode("ascii")
    qname_enc += b"\x00"
    # Question: QTYPE=PTR (12), QCLASS=IN (1)
    question = qname_enc + struct.pack(">HH", 12, 1)
    return header + question


def _parse_dns_name(data: bytes, offset: int) -> tuple[str, int]:
    """Parse a DNS name from packet data, handling compression pointers."""
    labels = []
    orig_offset = offset
    jumped = False
    for _ in range(20):  # max 20 label depth
        if offset >= len(data):
            break
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:  # compression pointer
            if offset + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                orig_offset = offset + 2
                jumped = True
            offset = ptr
            continue
        offset += 1
        if offset + length > len(data):
            break
        labels.append(data[offset:offset + length].decode("ascii", errors="ignore"))
        offset += length
    final_offset = orig_offset if jumped else offset
    return ".".join(labels), final_offset


# Service types to query — responders advertise their hostname as instance name
_MDNS_SERVICES = [
    "_workstation._tcp.local",   # Debian/Raspberry Pi/Linux
    "_device-info._tcp.local",   # Apple
    "_smb._tcp.local",           # Samba/file sharing
    "_http._tcp.local",          # web services
    "_ssh._tcp.local",           # SSH-enabled hosts
    "_airplay._tcp.local",       # Apple AirPlay
    "_googlecast._tcp.local",    # Chromecast
    "_printer._tcp.local",       # printers
]


def _mdns_query_one(ip: str, qname: str) -> bytes | None:
    """Send one mDNS query with source port 5353 (required by Avahi)."""
    query = _build_mdns_query(qname)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # Avahi ignores queries not from port 5353 — this is REQUIRED
        sock.bind(("", 5353))
    except OSError:
        pass  # port already in use, fall back to ephemeral
    sock.settimeout(_PROBE_TIMEOUT)
    try:
        sock.sendto(query, (ip, 5353))
        data, _ = sock.recvfrom(1500)
        return data
    except (socket.timeout, OSError):
        return None
    finally:
        sock.close()


def _extract_instance_name(data: bytes, qname: str) -> str:
    """Parse mDNS response and extract the instance hostname."""
    if len(data) < 12:
        return ""
    ancount = struct.unpack(">H", data[6:8])[0]
    if ancount == 0:
        return ""
    # Skip question
    offset = 12
    _, offset = _parse_dns_name(data, offset)
    offset += 4  # QTYPE + QCLASS
    # Parse answers
    for _ in range(ancount):
        if offset + 10 > len(data):
            return ""
        _, offset = _parse_dns_name(data, offset)
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        if rtype == 12:  # PTR
            name, _ = _parse_dns_name(data, offset)
            if name:
                # Response format: "instance.service._proto.local"
                # Strip the service suffix to get instance name
                if name.endswith("." + qname):
                    instance = name[:-(len(qname) + 1)]
                else:
                    instance = name
                # Apple/Avahi sometimes format as "hostname [MAC]"
                first = instance.split(" ")[0].split(".")[0]
                # Strip escaped chars
                first = first.replace("\\", "").strip()
                if _is_valid_hostname(first):
                    return first.lower()
        offset += rdlen
    return ""


def probe_mdns(ip: str) -> str:
    """Send unicast mDNS queries to <ip>:5353 for common service types.

    Source port MUST be 5353 (Avahi ignores ephemeral-port queries).
    Returns the first discovered hostname, or empty string.
    """
    try:
        for service in _MDNS_SERVICES:
            data = _mdns_query_one(ip, service)
            if data is None:
                continue
            name = _extract_instance_name(data, service)
            if name:
                return name
        return ""
    except Exception as exc:
        logger.debug("mDNS probe %s failed: %s", ip, exc)
        return ""


# ── NetBIOS name query ─────────────────────────────────────────────────────

def _encode_netbios_wildcard() -> bytes:
    """Encode the NetBIOS wildcard name '*' for NBSTAT query."""
    # Standard wildcard: length 0x20 + "CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + null
    return b"\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00"


def probe_netbios(ip: str) -> str:
    """Send a NetBIOS NBSTAT query to <ip>:137 and return the computer name."""
    try:
        tid = random.randint(0, 0xFFFF)
        # Header: ID, flags=0x0010 (broadcast bit, standard query), 1 Q, 0 A/Aut/Add
        header = struct.pack(">HHHHHH", tid, 0x0010, 1, 0, 0, 0)
        question = _encode_netbios_wildcard() + struct.pack(">HH", 0x21, 0x0001)
        packet = header + question

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(_PROBE_TIMEOUT)
        try:
            sock.sendto(packet, (ip, 137))
            data, _ = sock.recvfrom(1500)
        finally:
            sock.close()

        if len(data) < 56:
            return ""
        # Skip header (12) + question name (34) + qtype/qclass (4) = 50
        # Answer: name (34) + type (2) + class (2) + ttl (4) + rdlen (2) = 44
        # Then RDATA: num_names (1) + names (18 bytes each)
        rdata_offset = 50 + 34 + 2 + 2 + 4 + 2  # = 94
        if rdata_offset >= len(data):
            return ""
        num_names = data[rdata_offset]
        offset = rdata_offset + 1
        for _ in range(num_names):
            if offset + 18 > len(data):
                break
            name_bytes = data[offset:offset + 15]
            name_type = data[offset + 15]
            flags = struct.unpack(">H", data[offset + 16:offset + 18])[0]
            offset += 18
            # Workstation service (type 0x00), unique (flags bit 15 = 0), active (bit 1)
            if name_type == 0x00 and not (flags & 0x8000) and (flags & 0x0400):
                name = name_bytes.decode("ascii", errors="ignore").strip().rstrip("\x00")
                if _is_valid_hostname(name):
                    return name.lower()
        return ""
    except (socket.timeout, OSError):
        return ""
    except Exception as exc:
        logger.debug("NetBIOS probe %s failed: %s", ip, exc)
        return ""


# ── Public API ─────────────────────────────────────────────────────────────

def probe_device(ip: str) -> str:
    """Probe a device via mDNS first, fall back to NetBIOS. Returns hostname or ''."""
    name = probe_mdns(ip)
    if name:
        logger.info("mDNS hostname for %s: %s", ip, name)
        return name
    name = probe_netbios(ip)
    if name:
        logger.info("NetBIOS hostname for %s: %s", ip, name)
        return name
    return ""


def enqueue_probe(ip: str) -> None:
    """Queue an IP for probing (if not already probed recently)."""
    now = time.monotonic()
    with _probe_lock:
        last = _probe_seen.get(ip, 0)
        if now - last < _PROBE_INTERVAL:
            return
        _probe_queue.add(ip)


def probe_worker(hostname_callback) -> None:
    """Background thread: probes queued IPs and calls callback with results.

    hostname_callback(ip: str, hostname: str) is called for each discovery.
    """
    while True:
        time.sleep(5)
        with _probe_lock:
            if not _probe_queue:
                continue
            batch = list(_probe_queue)
            _probe_queue.clear()
            now = time.monotonic()
            for ip in batch:
                _probe_seen[ip] = now
        for ip in batch:
            try:
                name = probe_device(ip)
                if name:
                    hostname_callback(ip, name)
            except Exception as exc:
                logger.debug("Probe %s failed: %s", ip, exc)
            time.sleep(0.1)  # throttle to avoid flooding
