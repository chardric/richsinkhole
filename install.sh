#!/usr/bin/env bash
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

set -euo pipefail

# RichSinkhole installer
# Handles systemd-resolved stub listener conflict and starts the DNS sinkhole.

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

check_prereqs() {
    for cmd in docker curl; do
        command -v "$cmd" &>/dev/null || error "$cmd is required but not installed."
    done

    if ! docker compose version &>/dev/null; then
        error "Docker Compose v2 is required. Install Docker Desktop or the compose plugin."
    fi

    if [ "$EUID" -ne 0 ]; then
        warn "Not running as root. Some steps (systemd-resolved config) may require sudo."
    fi
}

# ---------------------------------------------------------------------------
# Free port 53 from systemd-resolved stub listener
# ---------------------------------------------------------------------------

free_port_53() {
    local resolved_conf="/etc/systemd/resolved.conf"
    local override_dir="/etc/systemd/resolved.conf.d"
    local override_file="${override_dir}/nostub.conf"

    # Check if port 53 is already free
    if ! ss -tlunp | grep -q ':53 '; then
        info "Port 53 is free — no changes needed."
        return 0
    fi

    # Check if systemd-resolved is the culprit
    if ! ss -tlunp | grep -q '127.0.0.53'; then
        warn "Port 53 is in use by something other than systemd-resolved. Manual intervention required."
        return 1
    fi

    info "systemd-resolved stub listener detected on port 53. Disabling it..."

    mkdir -p "$override_dir"
    cat > "$override_file" <<EOF
# Written by RichSinkhole installer
[Resolve]
DNSStubListener=no
EOF

    systemctl restart systemd-resolved

    # Verify port is now free
    if ss -tlunp | grep -q ':53 '; then
        error "Port 53 is still in use after disabling systemd-resolved stub. Aborting."
    fi

    info "Port 53 is now free."

    # Point /etc/resolv.conf to a working DNS while sinkhole starts
    if [ -L /etc/resolv.conf ]; then
        # It's a symlink (typical Ubuntu) — update it
        ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
        info "Updated /etc/resolv.conf symlink to use systemd-resolved upstream path."
    fi
}

# ---------------------------------------------------------------------------
# Build & start
# ---------------------------------------------------------------------------

start_services() {
    info "Building and starting RichSinkhole..."
    docker compose build --quiet
    docker compose up -d

    info "Waiting for DNS server to be ready..."
    local retries=10
    while [ $retries -gt 0 ]; do
        if docker compose ps | grep -q "Up"; then
            break
        fi
        sleep 1
        retries=$((retries - 1))
    done

    if ! docker compose ps | grep -q "Up"; then
        error "Container failed to start. Run: docker compose logs"
    fi
}

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

smoke_test() {
    info "Running smoke tests..."
    sleep 2  # give server a moment to fully initialize

    if ! command -v dig &>/dev/null; then
        warn "dig not found — skipping smoke tests. Install dnsutils to test."
        return 0
    fi

    local result_allowed result_blocked

    result_allowed=$(dig @127.0.0.1 youtube.com A +short +time=3 2>/dev/null | head -1)
    if [ -n "$result_allowed" ] && [ "$result_allowed" != "0.0.0.0" ]; then
        info "PASS: youtube.com resolved to ${result_allowed} (allowed)"
    else
        warn "FAIL: youtube.com did not resolve as expected (got: '${result_allowed}')"
    fi

    result_blocked=$(dig @127.0.0.1 doubleclick.net A +short +time=3 2>/dev/null | head -1)
    if [ "$result_blocked" = "0.0.0.0" ]; then
        info "PASS: doubleclick.net returned 0.0.0.0 (blocked)"
    else
        warn "FAIL: doubleclick.net was not blocked (got: '${result_blocked}')"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo ""
    echo "  RichSinkhole — DNS Sinkhole Installer"
    echo "  ======================================"
    echo ""

    check_prereqs
    free_port_53
    start_services
    smoke_test

    echo ""
    info "RichSinkhole is running!"
    echo ""
    echo "  Test commands:"
    echo "    dig @127.0.0.1 youtube.com      # should resolve normally"
    echo "    dig @127.0.0.1 doubleclick.net  # should return 0.0.0.0"
    echo ""
    echo "  Logs:     docker compose logs -f"
    echo "  Status:   docker compose ps"
    echo "  Stop:     docker compose down"
    echo ""
}

main "$@"
