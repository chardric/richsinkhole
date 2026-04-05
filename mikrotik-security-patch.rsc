# MikroTik Security Patch — Incremental (safe to import)
# Does NOT replace existing config — only adds missing rules and tweaks settings
#
# BEFORE IMPORTING:
#   1. Open Winbox → connect to MikroTik
#   2. Press Ctrl+X to enable Safe Mode (auto-reverts on disconnect)
#   3. Open Terminal in Winbox
#   4. Run: /import file-name=mikrotik-security-patch.rsc
#   5. Test internet (ping 8.8.8.8, browse a website, open dashboard)
#   6. If OK, press Ctrl+X again to save (exit Safe Mode)
#   7. If disconnected, wait 10 seconds — changes auto-revert
#
# RouterOS 6.49.19 compatible
# Network: Omada router (10.10.10.254) NATs all VLAN traffic (172.16.x.x)
#          to 10.10.10.254 before reaching MikroTik

# ── 1. WAN anti-spoofing (bogon protection) ─────────────────────────
# Drop packets from private IPs arriving on WAN (prevents IP spoofing)
# Placed at the TOP of the forward chain (before fasttrack)
/ip firewall filter
add chain=forward in-interface-list=WAN src-address=10.0.0.0/8 \
    action=drop comment="SPOOF: Drop RFC1918 10.x from WAN" place-before=0
add chain=forward in-interface-list=WAN src-address=172.16.0.0/12 \
    action=drop comment="SPOOF: Drop RFC1918 172.16.x from WAN" place-before=1
add chain=forward in-interface-list=WAN src-address=192.168.0.0/16 \
    action=drop comment="SPOOF: Drop RFC1918 192.168.x from WAN" place-before=2

# Also drop on input chain
add chain=input in-interface-list=WAN src-address=10.0.0.0/8 \
    action=drop comment="SPOOF: Drop RFC1918 10.x from WAN (input)" place-before=0
add chain=input in-interface-list=WAN src-address=172.16.0.0/12 \
    action=drop comment="SPOOF: Drop RFC1918 172.16.x from WAN (input)" place-before=1
add chain=input in-interface-list=WAN src-address=192.168.0.0/16 \
    action=drop comment="SPOOF: Drop RFC1918 192.168.x from WAN (input)" place-before=2

# ── 2. Inter-VLAN isolation: Omada direct devices → Servers blocked ──
# The Omada router (10.10.10.254) NATs all VLAN client traffic, so from
# MikroTik's view, all VLAN traffic comes from 10.10.10.254. We MUST
# allow the Omada router through, otherwise all VLAN clients lose access.
#
# Only block direct Omada-network devices (10.10.10.1-253) that are NOT
# the Omada router itself. This prevents rogue devices plugged directly
# into the Omada network from reaching servers.
/ip firewall filter
add chain=forward src-address=10.10.10.254 dst-address=10.254.254.0/24 \
    action=accept \
    comment="VLAN: Allow Omada router (NATs all VLAN clients) -> Servers" \
    place-before=0
add chain=forward src-address=10.10.10.0/24 dst-address=10.254.254.4 \
    dst-port=53 protocol=udp action=accept \
    comment="VLAN: Allow Omada direct -> Sinkhole DNS (UDP)" place-before=1
add chain=forward src-address=10.10.10.0/24 dst-address=10.254.254.4 \
    dst-port=53 protocol=tcp action=accept \
    comment="VLAN: Allow Omada direct -> Sinkhole DNS (TCP)" place-before=2
add chain=forward src-address=10.10.10.0/24 dst-address=10.254.254.0/24 \
    connection-state=new action=drop \
    comment="VLAN: Block Omada direct devices -> Server network" place-before=3

# ── 3. NTP server — stop broadcasting on WAN ────────────────────────
/system ntp server set broadcast=no multicast=no

# ── 4. Restrict Winbox to server network only ────────────────────────
/ip service set winbox address=10.254.254.0/24

# ── 5. Disable MAC-Telnet/Winbox discovery (bypasses IP ACLs) ───────
/tool mac-server set allowed-interface-list=none
/tool mac-server mac-winbox set allowed-interface-list=none

# ── 6. Remove dead DNS rules (after the drop-all, never evaluated) ──
# These are safe to remove since allow-remote-requests is disabled
:foreach i in=[/ip firewall filter find where comment~"DNS:"] do={ \
    /ip firewall filter remove $i; \
}

# ── Done ─────────────────────────────────────────────────────────────
:log warning "Security patch applied. Test internet then exit Safe Mode (Ctrl+X)."
:put "Patch applied. Test your internet NOW."
:put "If OK: press Ctrl+X in Winbox to save."
:put "If broken: disconnect Winbox — auto-reverts in 10 seconds."
