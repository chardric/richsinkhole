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
# Host tuning — sysctls for DNS workload + memory cgroup on Raspberry Pi
# ---------------------------------------------------------------------------

tune_sysctls() {
    local conf="/etc/sysctl.d/99-sinkhole.conf"

    if [ "$EUID" -ne 0 ]; then
        warn "Skipping sysctl tuning — not running as root. Re-run with sudo to apply."
        return 0
    fi

    local desired
    desired=$(cat <<'EOF'
# Written by RichSinkhole installer — DNS workload tuning.
# Safe defaults for a dedicated sinkhole host; tune further if needed.
vm.swappiness = 10
net.core.rmem_max = 4194304
net.core.rmem_default = 1048576
net.core.wmem_max = 1048576
net.core.netdev_max_backlog = 5000
net.ipv4.udp_rmem_min = 16384
EOF
)

    if [ -f "$conf" ] && [ "$(cat "$conf")" = "$desired" ]; then
        info "Sysctl tuning already in place at $conf."
        return 0
    fi

    # Backup any pre-existing file before overwriting
    [ -f "$conf" ] && cp -a "$conf" "${conf}.bak"

    printf '%s\n' "$desired" > "$conf"
    chmod 644 "$conf"

    if sysctl --system >/dev/null 2>&1; then
        info "Installed sysctl tuning at $conf and applied."
    else
        warn "Wrote $conf but 'sysctl --system' reported errors. Review with: sysctl --system"
    fi
}

enable_pi_cgroup_memory() {
    local model_file="/proc/device-tree/model"
    local cmdline="/boot/firmware/cmdline.txt"

    # Pi-only: bail silently on non-Pi hosts.
    [ -r "$model_file" ] || return 0
    grep -qi "Raspberry Pi" "$model_file" || return 0

    # Fall back to legacy path on older Raspbian where /boot/firmware/ doesn't exist.
    [ -f "$cmdline" ] || cmdline="/boot/cmdline.txt"
    [ -f "$cmdline" ] || { warn "Raspberry Pi detected but no cmdline.txt found — skipping cgroup fix."; return 0; }

    if [ "$EUID" -ne 0 ]; then
        warn "Raspberry Pi detected. Memory cgroup may need enabling — re-run installer with sudo."
        return 0
    fi

    # Already enabled at runtime (covers cgroup v1 and v2) → nothing to do.
    # This is the authoritative check: params in /proc/cmdline can both be
    # present (firmware injects cgroup_disable=memory, we override with enable);
    # only the resolved controller list tells us whether it actually worked.
    if grep -qw memory /sys/fs/cgroup/cgroup.controllers 2>/dev/null \
       || awk '$1=="memory" && $4=="1" {f=1} END{exit !f}' /proc/cgroups 2>/dev/null; then
        info "Memory cgroup already enabled at runtime."
        return 0
    fi

    # Already present in cmdline.txt → waiting for reboot.
    if grep -q "cgroup_enable=memory" "$cmdline"; then
        warn "Memory cgroup flags already in $cmdline — reboot required to activate."
        return 0
    fi

    # Edit cmdline.txt — appending; "last value wins" overrides firmware-injected
    # cgroup_disable=memory on Raspberry Pi OS.
    cp -a "$cmdline" "${cmdline}.bak"
    local current new
    current=$(tr -d '\n' < "$cmdline")
    new="$current cgroup_enable=memory cgroup_memory=1"
    printf '%s' "$new" > "$cmdline"

    # Sanity check: exactly one line, non-empty
    if [ "$(wc -l < "$cmdline")" -gt 1 ] || [ ! -s "$cmdline" ]; then
        warn "cmdline.txt edit looked wrong — restoring backup."
        cp -a "${cmdline}.bak" "$cmdline"
        return 1
    fi

    warn "Enabled memory cgroup in $cmdline. A REBOOT is required for this to take effect."
    warn "Without it, docker-compose mem_limit settings are silently ignored on Raspberry Pi OS."
}

tune_host() {
    tune_sysctls
    enable_pi_cgroup_memory
}

# ---------------------------------------------------------------------------
# Route reconciler — manages extra static routes from a YAML config so the
# sinkhole can reply to clients on VLANs that aren't directly attached.
# ---------------------------------------------------------------------------

install_route_reconciler() {
    local script_dst="/usr/local/bin/rs-route-reconciler.py"
    local svc_dst="/etc/systemd/system/rs-route-reconciler.service"
    local path_dst="/etc/systemd/system/rs-route-reconciler.path"
    local timer_dst="/etc/systemd/system/rs-route-reconciler.timer"
    local data_cfg="$(pwd)/data/config/extra_routes.yml"
    local example_src="$(pwd)/scripts/extra_routes.yml.example"
    local etc_link="/etc/sinkhole/extra_routes.yml"

    if [ ! -f "scripts/route-reconciler.py" ]; then
        warn "scripts/route-reconciler.py missing — skipping route reconciler install."
        return 0
    fi

    if ! command -v nmcli &>/dev/null; then
        warn "nmcli not found — skipping route reconciler (only needed if you use NetworkManager + extra VLANs)."
        return 0
    fi

    info "Installing route reconciler..."

    install -m 0755 scripts/route-reconciler.py "$script_dst"

    # Seed the config in data/config (so it's part of the backup) if absent.
    mkdir -p "$(dirname "$data_cfg")"
    if [ ! -f "$data_cfg" ] && [ -f "$example_src" ]; then
        cp "$example_src" "$data_cfg"
        info "Seeded $data_cfg (no extra routes by default — edit to add)."
    fi

    # Convenience symlink so the docs path /etc/sinkhole/extra_routes.yml works.
    mkdir -p /etc/sinkhole
    [ -f "$data_cfg" ] && ln -sfn "$data_cfg" "$etc_link"

    # Substitute the real config path into the unit templates — systemd path
    # units watch via inotify and don't follow symlinks, so they need the
    # canonical file location, not the /etc/sinkhole/ alias.
    sed "s|__CONFIG_PATH__|${data_cfg}|g" scripts/rs-route-reconciler.service > "$svc_dst"
    sed "s|__CONFIG_PATH__|${data_cfg}|g" scripts/rs-route-reconciler.path    > "$path_dst"
    install -m 0644 scripts/rs-route-reconciler.timer "$timer_dst"
    chmod 0644 "$svc_dst" "$path_dst"

    systemctl daemon-reload
    systemctl reset-failed rs-route-reconciler.service rs-route-reconciler.path rs-route-reconciler.timer 2>/dev/null || true
    systemctl enable --now rs-route-reconciler.path rs-route-reconciler.timer >/dev/null 2>&1 || true
    systemctl start rs-route-reconciler.service \
        || warn "Initial route reconciler run failed — check: journalctl -u rs-route-reconciler"
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
    tune_host
    install_route_reconciler
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
