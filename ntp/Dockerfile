FROM alpine:3.21

RUN apk add --no-cache chrony && \
    mkdir -p /var/lib/chrony /var/log/chrony /var/run/chrony && \
    chown -R chrony:chrony /var/lib/chrony /var/log/chrony /var/run/chrony

COPY chrony.conf /etc/chrony/chrony.conf

EXPOSE 123/udp

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD chronyc tracking >/dev/null 2>&1 || exit 1

CMD ["sh", "-c", "rm -f /var/run/chrony/chronyd.pid && chronyd -d -f /etc/chrony/chrony.conf"]
