# Centralised paths and tunables for the Lite variant.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

import os
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


# Filesystem layout — all overridable via env for testing.
STATE_DIR    = _env_path("RS_LITE_STATE_DIR",  "/var/lib/rs-lite")
LOG_DIR      = _env_path("RS_LITE_LOG_DIR",    "/var/log/rs-lite")
CONFIG_DIR   = _env_path("RS_LITE_CONFIG_DIR", "/etc/rs-lite")

STATE_DB     = STATE_DIR / "state.db"
BLOCKED_HOSTS_FILE = STATE_DIR / "blocked.hosts"
SOURCES_YML        = CONFIG_DIR / "sources.yml"
DNSMASQ_LOG  = LOG_DIR / "dnsmasq.log"

# Networking.
DASHBOARD_HOST = os.environ.get("RS_LITE_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("RS_LITE_PORT", "8080"))

# Updater knobs — kept conservative for ARMv6.
HTTP_TIMEOUT_SECS    = 30
MAX_DOMAINS_PER_FEED = 200_000
DNSMASQ_RELOAD_CMD   = ["sudo", "-n", "systemctl", "reload", "dnsmasq"]

# Query-log view limits — bounded reads so we never OOM on a 512 MB box.
QUERYLOG_MAX_BYTES = 5 * 1024 * 1024  # tail at most 5 MB
QUERYLOG_MAX_LINES = 5_000

# Session.
SESSION_COOKIE_NAME = "rs_lite_session"
SESSION_LIFETIME_HOURS = 12
