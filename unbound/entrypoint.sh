#!/bin/sh
# Re-create DNSSEC trust anchor (tmpfs wipes /var/lib/unbound on restart)
# tmpfs is mounted with uid=100(unbound), so unbound-anchor can write directly
unbound-anchor -a /var/lib/unbound/root.key 2>/dev/null || true

# Use dashboard-managed config if it exists, otherwise use built-in default
if [ -f /data/unbound.conf ]; then
    cp /data/unbound.conf /etc/unbound/unbound.conf
fi
exec unbound -d -c /etc/unbound/unbound.conf
