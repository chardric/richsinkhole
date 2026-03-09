#!/bin/sh
# Use dashboard-managed config if it exists, otherwise use built-in default
if [ -f /data/unbound.conf ]; then
    cp /data/unbound.conf /etc/unbound/unbound.conf
fi
exec unbound -d -c /etc/unbound/unbound.conf
