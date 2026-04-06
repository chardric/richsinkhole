FROM alpine:3.21

RUN apk add --no-cache unbound drill openssl

# Create working directory, DNSSEC trust anchor, and control keys
RUN mkdir -p /var/lib/unbound && \
    unbound-anchor -a /var/lib/unbound/root.key || true && \
    unbound-control-setup && \
    chown -R unbound:unbound /var/lib/unbound /etc/unbound

COPY unbound.conf /etc/unbound/unbound.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Verify config at build time
RUN unbound-checkconf /etc/unbound/unbound.conf

EXPOSE 53/udp 53/tcp

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD drill @127.0.0.1 localhost >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/entrypoint.sh"]
