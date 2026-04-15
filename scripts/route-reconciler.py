#!/usr/bin/env python3
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Reconcile static routes from YAML config into NetworkManager.

Source-of-truth file (default /etc/sinkhole/extra_routes.yml):

    routes:
      - { net: 172.16.20.0/24, via: 172.16.10.1, dev: eth2 }
      - { net: 172.16.40.0/24, via: 172.16.10.1, dev: eth2 }

Behaviour:
  - For each `dev` mentioned in the file, nmcli's ipv4.routes is set to exactly
    the routes listed for that device (anything else previously managed for that
    device is removed).
  - Devices NOT mentioned in the file are left untouched.
  - Routes are persisted in nmcli (survive reboot) and applied live via
    `nmcli device reapply` (no connection bounce).
  - Idempotent: if current state already matches desired, nothing is changed.

Triggered by:
  - systemd oneshot service at boot (After=NetworkManager.service)
  - systemd path unit when the YAML file changes
  - manually:  sudo /usr/local/bin/rs-route-reconciler.py
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed (apt install python3-yaml)", file=sys.stderr)
    sys.exit(2)

DEFAULT_CONFIG = Path("/etc/sinkhole/extra_routes.yml")

log = logging.getLogger("route-reconciler")


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    log.debug("exec: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def load_desired(config_path: Path) -> list[dict]:
    if not config_path.exists():
        log.info("no config at %s — nothing to manage", config_path)
        return []
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        log.error("invalid YAML in %s: %s", config_path, exc)
        sys.exit(2)

    out: list[dict] = []
    for entry in data.get("routes") or []:
        net, via, dev = entry.get("net"), entry.get("via"), entry.get("dev")
        if not (net and via and dev):
            log.warning("skipping incomplete entry: %s", entry)
            continue
        try:
            ipaddress.ip_network(net, strict=False)
            ipaddress.ip_address(via)
        except ValueError as exc:
            log.warning("skipping invalid entry %s: %s", entry, exc)
            continue
        out.append({"net": str(ipaddress.ip_network(net, strict=False)),
                    "via": str(ipaddress.ip_address(via)),
                    "dev": dev})
    return out


def current_routes(dev: str) -> set[tuple[str, str]]:
    """Return {(net, via)} from nmcli for the connection bound to `dev`.

    `nmcli -t -f ipv4.routes connection show <dev>` emits one line:
        ipv4.routes:<net> <via>[ <metric>][ <opts>], <net> <via>, ...
    Empty value is "--" or just "ipv4.routes:".
    """
    proc = _run(["nmcli", "-t", "-f", "ipv4.routes", "connection", "show", dev],
                check=False)
    if proc.returncode != 0:
        return set()
    raw = proc.stdout.strip()
    if ":" not in raw:
        return set()
    body = raw.split(":", 1)[1].strip()
    if not body or body == "--":
        return set()
    routes: set[tuple[str, str]] = set()
    for entry in body.split(","):
        parts = entry.strip().split()
        if len(parts) >= 2:
            routes.add((parts[0], parts[1]))
    return routes


def active_devices() -> set[str]:
    proc = _run(["nmcli", "-t", "-f", "DEVICE", "connection", "show", "--active"])
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def apply_for_device(dev: str, desired: set[tuple[str, str]]) -> bool:
    """Reconcile nmcli routes on `dev`. Returns True if changes were applied."""
    current = current_routes(dev)
    if desired == current:
        log.info("%s: already in sync (%d route(s))", dev, len(desired))
        return False

    add = desired - current
    rem = current - desired
    log.info("%s: applying %d add, %d remove (was %d, will be %d)",
             dev, len(add), len(rem), len(current), len(desired))

    # nmcli has no atomic "set"; clearing then re-adding is the simplest path.
    _run(["nmcli", "connection", "modify", dev, "ipv4.routes", ""])
    for net, via in sorted(desired):
        _run(["nmcli", "connection", "modify", dev,
              "+ipv4.routes", f"{net} {via}"])

    # Live re-apply without bouncing the link.
    _run(["nmcli", "device", "reapply", dev])
    return True


def write_interface_snapshot(snapshot_path: Path) -> None:
    """Write a JSON snapshot of host network interfaces next to the YAML config.

    The dashboard runs in a Docker container and can't see host NICs directly,
    so the reconciler — which already runs on the host — drops a snapshot the
    UI can read to populate the device dropdown.
    """
    import json
    proc = _run(["ip", "-j", "-4", "addr", "show"], check=False)
    if proc.returncode != 0:
        log.warning("ip -j addr failed: %s", proc.stderr.strip())
        return
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        log.warning("could not parse `ip -j addr` output: %s", exc)
        return
    snap: list[dict] = []
    for iface in raw:
        name = iface.get("ifname", "")
        if name in ("lo",) or name.startswith(("docker", "br-", "veth")):
            continue
        ip4 = next(
            (a for a in iface.get("addr_info", [])
             if a.get("family") == "inet" and a.get("scope") == "global"),
            None,
        )
        snap.append({
            "name": name,
            "state": iface.get("operstate", "UNKNOWN"),
            "ip": ip4["local"] if ip4 else None,
            "prefix": ip4["prefixlen"] if ip4 else None,
            "mac": iface.get("address", ""),
        })
    snap.sort(key=lambda x: x["name"])
    payload = {"interfaces": snap, "ts": __import__("time").time()}
    try:
        snapshot_path.write_text(json.dumps(payload, indent=2))
        log.info("wrote %d interface(s) to %s", len(snap), snapshot_path)
    except OSError as exc:
        log.warning("could not write snapshot %s: %s", snapshot_path, exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"YAML config path (default {DEFAULT_CONFIG})")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    desired = load_desired(args.config)

    by_dev: dict[str, set[tuple[str, str]]] = {}
    for r in desired:
        by_dev.setdefault(r["dev"], set()).add((r["net"], r["via"]))

    devs = active_devices()
    changed = 0
    for dev, routes in by_dev.items():
        if dev not in devs:
            log.warning("device %s is not an active NM connection — skipping", dev)
            continue
        if apply_for_device(dev, routes):
            changed += 1

    log.info("reconcile complete: %d device(s) changed", changed)

    # Drop a snapshot of host NICs for the dashboard UI's "dev" dropdown.
    snapshot = args.config.parent / "host_interfaces.json"
    write_interface_snapshot(snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
