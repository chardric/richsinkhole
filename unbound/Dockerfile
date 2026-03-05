FROM alpine:3.21

RUN apk add --no-cache unbound drill

# Create working directory and pre-generate DNSSEC trust anchor
RUN mkdir -p /var/lib/unbound && \
    unbound-anchor -a /var/lib/unbound/root.key || true && \
    chown -R unbound:unbound /var/lib/unbound

COPY unbound.conf /etc/unbound/unbound.conf

# Verify config at build time
RUN unbound-checkconf /etc/unbound/unbound.conf

EXPOSE 53/udp 53/tcp

CMD ["unbound", "-d", "-c", "/etc/unbound/unbound.conf"]
