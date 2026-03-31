FROM alpine:3.21

RUN apk add --no-cache chrony && \
    mkdir -p /var/lib/chrony /var/log/chrony

COPY chrony.conf /etc/chrony/chrony.conf

EXPOSE 123/udp

CMD ["sh", "-c", "rm -f /var/run/chrony/chronyd.pid && chronyd -d -f /etc/chrony/chrony.conf"]
