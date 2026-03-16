#!/usr/bin/env python3
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Unified sinkhole entrypoint — runs DNS server, dashboard, updater,
and YouTube proxy in a single Python process.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

# Add service directories to Python path so their imports resolve
sys.path.insert(0, "/app/dns")
sys.path.insert(0, "/app/dashboard")
sys.path.insert(0, "/app/updater")
sys.path.insert(0, "/app/youtube-proxy")

# Import the dashboard app and its original lifespan
from main import app, lifespan as _dashboard_lifespan  # noqa: E402

log = logging.getLogger("sinkhole")


@asynccontextmanager
async def lifespan(application):
    # ── DNS server (threaded — returns immediately) ──
    from server import start_dns
    start_dns()
    log.info("DNS server started")

    # ── YouTube proxy on :8000 (async task) ──
    from proxy import start_yt_proxy
    yt_task = asyncio.create_task(start_yt_proxy())
    log.info("YouTube proxy starting on :8000")

    # ── Updater (blocking loop in a thread) ──
    from updater import start_updater_sync
    updater_task = asyncio.create_task(asyncio.to_thread(start_updater_sync))
    log.info("Updater started in background thread")

    # ── Run original dashboard lifespan ──
    async with _dashboard_lifespan(application) as value:
        yield value

    # Cleanup on shutdown
    yt_task.cancel()
    updater_task.cancel()


# Replace the dashboard app's lifespan with our combined one
app.router.lifespan_context = lifespan
