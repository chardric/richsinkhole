#!/usr/bin/env python3
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.
"""
Host-level mDNS multicast scan + NetBIOS probe for RichSinkhole.

Runs on the RPi host (not in Docker container) because:
  1. Docker NAT rewrites UDP source ports, breaking Avahi's port 5353 requirement
  2. The RPi has direct L2 access to multiple subnets via its physical interfaces

Strategy:
  1. Multicast mDNS scan on each local interface — discovers all responders on
     directly-connected subnets in a single query per interface
  2. Unicast mDNS + NetBIOS probe for IPs on other subnets (fallback)
  3. Hostname pattern inference — classifies device type from hostname

Run via cron hourly:
    0 * * * * /usr/local/bin/rs-host-probe >> /var/log/rs-host-probe.log 2>&1

Dependencies: Python 3 stdlib only.
"""

import fcntl
import logging
import random
import re
import socket
import sqlite3
import struct
import sys
import time

DB_PATH = "/mnt/nas/richsinkhole-data/sinkhole.db"
PROBE_TIMEOUT = 3.0
MULTICAST_LISTEN = 3.0
ACTIVE_WINDOW_HOURS = 24

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("rs-probe")

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{1,61}[a-zA-Z0-9]$")

_HOSTNAME_PATTERNS = [
    (re.compile(r"^raspberrypi$|^rpi-|^rpi\d|^pi-hole|^pihole|^octopi|^retropie|^homeassistant|^raspi-|^raspberry-|^jellyfin$"), "Raspberry Pi"),
    (re.compile(r"^eap\d+|^omada"),              "TP-Link"),
    (re.compile(r"^mikrotik|^routerboard|^hap-|^hex-"), "MikroTik"),
    (re.compile(r"^ubnt|^unifi"),                "Ubiquiti"),
    (re.compile(r"^iphone|^ipad|^imac|^macbook|^apple-tv|^homepod"), "Apple Device"),
    (re.compile(r"^android-|^pixel-|^galaxy-"),  "Android"),
    (re.compile(r"^mi-|^xiaomi|^redmi|^poco"),   "Xiaomi Device"),
    (re.compile(r"^desktop-[a-z0-9]{7}$|^laptop-[a-z0-9]{7}$|^surface-"), "Windows"),
    (re.compile(r"^echo-|^alexa-"),              "Amazon Echo"),
    (re.compile(r"^googlehome|^nest-|^chromecast"), "Google Home"),
    (re.compile(r"^roku-"),                      "Roku"),
    (re.compile(r"^plex|^emby|^kodi|^openmediavault|^nextcloud"), "Media Server"),
    (re.compile(r"^synology|^diskstation|^ds\d+"), "Synology NAS"),
]

_MDNS_SERVICES = [
    "_workstation._tcp.local",
    "_device-info._tcp.local",
    "_smb._tcp.local",
    "_http._tcp.local",
    "_ssh._tcp.local",
    "_airplay._tcp.local",
    "_googlecast._tcp.local",
    "_printer._tcp.local",
    "_ipp._tcp.local",
    "_raop._tcp.local",
]


def infer_type(hostname: str) -> str:
    for pattern, dtype in _HOSTNAME_PATTERNS:
        if pattern.search(hostname):
            return dtype
    return ""


def is_valid_hostname(name: str) -> bool:
    if not name or len(name) < 2 or len(name) > 63:
        return False
    return bool(_HOSTNAME_RE.match(name))


# ── DNS packet helpers ──────────────────────────────────────────────────────

def _build_query(qname: str) -> bytes:
    tid = random.randint(0, 0xFFFF)
    header = struct.pack(">HHHHHH", tid, 0x0000, 1, 0, 0, 0)
    qname_enc = b""
    for label in qname.split("."):
        if label:
            qname_enc += bytes([len(label)]) + label.encode("ascii")
    qname_enc += b"\x00"
    return header + qname_enc + struct.pack(">HH", 12, 1)


def _parse_name(data: bytes, offset: int) -> tuple[str, int]:
    labels = []
    orig_offset = offset
    jumped = False
    for _ in range(20):
        if offset >= len(data):
            break
        length = data[offset]
        if length == 0:
            offset += 1
            break
        if (length & 0xC0) == 0xC0:
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
    return ".".join(labels), (orig_offset if jumped else offset)


def _extract_instance_names(data: bytes) -> list[str]:
    """Extract all instance hostnames from an mDNS PTR response."""
    names = []
    if len(data) < 12:
        return names
    qdcount = struct.unpack(">H", data[4:6])[0]
    ancount = struct.unpack(">H", data[6:8])[0]
    if ancount == 0:
        return names
    offset = 12
    # mDNS responses may omit the question section (qdcount=0)
    for _ in range(qdcount):
        _, offset = _parse_name(data, offset)
        offset += 4  # QTYPE + QCLASS
    for _ in range(ancount):
        if offset + 10 > len(data):
            break
        _, offset = _parse_name(data, offset)
        rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        if rtype == 12:  # PTR
            name, _ = _parse_name(data, offset)
            if name:
                first = name.split(" ")[0].split(".")[0].replace("\\", "").strip()
                if is_valid_hostname(first):
                    names.append(first.lower())
        offset += rdlen
    return names


# ── Multicast mDNS scan ─────────────────────────────────────────────────────

def _get_local_interfaces() -> list[tuple[str, str]]:
    """Return list of (interface_name, ip) for local IPv4 interfaces."""
    results = []
    try:
        import subprocess
        output = subprocess.check_output(
            ["ip", "-4", "-br", "addr", "show"],
            text=True, timeout=5,
        )
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "UP":
                ifname = parts[0]
                if ifname in ("lo", "docker0") or ifname.startswith("br-") or ifname.startswith("veth"):
                    continue
                ip = parts[2].split("/")[0]
                if ip and not ip.startswith("169.254."):
                    results.append((ifname, ip))
    except Exception as exc:
        log.error("Failed to enumerate interfaces: %s", exc)
    return results


def multicast_scan(iface_ip: str) -> dict[str, str]:
    """Multicast mDNS scan on a specific interface. Returns {ip: hostname}."""
    results: dict[str, str] = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
        sock.bind(("", 5353))
        mreq = socket.inet_aton("224.0.0.251") + socket.inet_aton(iface_ip)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # Send queries for all service types
        for service in _MDNS_SERVICES:
            query = _build_query(service)
            sock.sendto(query, ("224.0.0.251", 5353))

        # Collect responses for MULTICAST_LISTEN seconds
        sock.settimeout(MULTICAST_LISTEN)
        start = time.monotonic()
        while time.monotonic() - start < MULTICAST_LISTEN:
            try:
                data, (src_ip, _port) = sock.recvfrom(1500)
                if src_ip == iface_ip:
                    continue  # ignore self
                names = _extract_instance_names(data)
                for name in names:
                    if src_ip not in results:
                        results[src_ip] = name
                        log.info("mDNS %s (%s) → %s", src_ip, iface_ip, name)
            except socket.timeout:
                break
            except Exception:
                continue
        sock.close()
    except Exception as exc:
        log.error("Multicast scan on %s failed: %s", iface_ip, exc)
    return results


# ── Unicast NetBIOS fallback ────────────────────────────────────────────────

def probe_netbios(ip: str) -> str:
    try:
        tid = random.randint(0, 0xFFFF)
        header = struct.pack(">HHHHHH", tid, 0x0010, 1, 0, 0, 0)
        question = b"\x20CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\x00" + struct.pack(">HH", 0x21, 0x0001)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(PROBE_TIMEOUT)
        try:
            sock.sendto(header + question, (ip, 137))
            data, _ = sock.recvfrom(1500)
        finally:
            sock.close()
        if len(data) < 56:
            return ""
        rdata_offset = 50 + 34 + 2 + 2 + 4 + 2
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
            if name_type == 0x00 and not (flags & 0x8000) and (flags & 0x0400):
                name = name_bytes.decode("ascii", errors="ignore").strip().rstrip("\x00")
                if is_valid_hostname(name):
                    return name.lower()
        return ""
    except (socket.timeout, OSError):
        return ""
    except Exception as exc:
        log.debug("NetBIOS %s: %s", ip, exc)
        return ""


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    # Single-instance lock to prevent concurrent runs
    lock_fd = open("/var/lock/rs-host-probe.lock", "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        log.info("Another probe is already running, exiting")
        sys.exit(0)

    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
    except sqlite3.OperationalError as exc:
        log.error("Cannot open %s: %s", DB_PATH, exc)
        sys.exit(1)

    # Phase 1: multicast scan on each local interface
    interfaces = _get_local_interfaces()
    log.info("Scanning %d local interfaces: %s", len(interfaces), [i[0] for i in interfaces])

    discovered: dict[str, str] = {}
    for ifname, ifip in interfaces:
        results = multicast_scan(ifip)
        discovered.update(results)
    log.info("Multicast scan found %d hostnames", len(discovered))

    # Phase 2: NetBIOS fallback for active IPs without a mDNS response
    active_rows = conn.execute(
        "SELECT DISTINCT client_ip FROM query_log "
        "WHERE ts >= datetime('now', ?) ORDER BY client_ip",
        (f"-{ACTIVE_WINDOW_HOURS} hours",),
    ).fetchall()
    active_ips = [r[0] for r in active_rows if r[0] and not r[0].startswith("127.")]

    nb_count = 0
    for ip in active_ips:
        if ip in discovered:
            continue
        name = probe_netbios(ip)
        if name:
            discovered[ip] = name
            log.info("NetBIOS %s → %s", ip, name)
            nb_count += 1
        time.sleep(0.05)
    log.info("NetBIOS probe found %d additional hostnames", nb_count)

    # Phase 3: write results to DB
    updated = 0
    for ip, name in discovered.items():
        dtype = infer_type(name)
        # Insert if missing
        conn.execute(
            """INSERT OR IGNORE INTO device_fingerprints
                 (ip, device_type, confidence, first_seen, last_seen, label)
               VALUES (?, ?, ?, datetime('now'), datetime('now'), ?)""",
            (ip, dtype or "Unknown", 10, name),
        )
        # Update label only if empty (preserve manual labels)
        if dtype:
            cur = conn.execute(
                """UPDATE device_fingerprints
                   SET label = ?,
                       device_type = CASE WHEN device_type IN ('Unknown','') OR device_type IS NULL
                                          THEN ? ELSE device_type END,
                       last_seen = datetime('now')
                   WHERE ip = ? AND (label IS NULL OR label = '')""",
                (name, dtype, ip),
            )
        else:
            cur = conn.execute(
                """UPDATE device_fingerprints
                   SET label = ?, last_seen = datetime('now')
                   WHERE ip = ? AND (label IS NULL OR label = '')""",
                (name, ip),
            )
        if cur.rowcount > 0:
            updated += 1

    conn.commit()
    conn.close()
    log.info("Updated %d devices with new labels", updated)


if __name__ == "__main__":
    main()
