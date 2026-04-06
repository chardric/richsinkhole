# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

FROM python:3.12-slim

WORKDIR /app

# All deps from all 4 services (deduplicated)
RUN pip install --no-cache-dir \
    dnslib pyyaml \
    "fastapi>=0.115,<1.0" "uvicorn[standard]>=0.30,<1.0" aiosqlite httpx \
    jinja2 python-multipart "qrcode[pil]" \
    schedule

# Copy all service code into known paths
COPY dns/            /app/dns/
COPY dashboard/      /app/dashboard/
COPY updater/        /app/updater/
COPY youtube-proxy/  /app/youtube-proxy/

# Symlinks so hardcoded paths in each service still resolve
# dashboard: /dashboard/static, /dashboard/templates
# dns: /dns/config.yml (CONFIG_DEFAULT)
# updater: /updater/sources.yml
RUN ln -s /app/dashboard /dashboard && \
    ln -s /app/dns /dns && \
    ln -s /app/updater /updater

# Unified entrypoint
COPY sinkhole/main.py /app/sinkhole_main.py

EXPOSE 53/udp 53/tcp 8080 8000

# Non-root user — UID 1000 matches data volume ownership
RUN groupadd -r app && useradd -r -g app -u 1000 app && \
    mkdir -p /data /local /config && chown -R app:app /app /data /local /config
USER app

# Only trust proxy headers from Docker internal network (nginx container)
CMD ["uvicorn", "sinkhole_main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips=172.16.0.0/12,192.168.0.0/16,10.0.0.0/8", "--loop", "asyncio"]
