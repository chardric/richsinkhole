# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Structured JSON logging — shared configuration for every Python service
running inside the sinkhole container (dashboard, dns, updater, yt-proxy).

Output is a single JSON object per line on stdout so Docker's json-file
driver (and any downstream log shipper) can parse it directly. Every
record carries a request_id correlation id when one is bound.

Usage:
    from jsonlog import configure, get_logger, bind_request_id
    configure()                                  # once at startup
    log = get_logger("dashboard")
    log.info("login", extra={"user": "admin"})   # → {"ts":...,"level":"INFO",...}
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

# Correlation id — bound per request via middleware, flows through logs.
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

# Fields that logging.LogRecord sets itself — excluded from the `extra` passthrough.
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = _request_id.get()
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        # Merge structured extras
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = str(value)
        return json.dumps(payload, default=str, ensure_ascii=False)


_configured = False


def configure(level: str | None = None) -> None:
    """Install the JSON formatter on the root logger exactly once.
    Idempotent — safe to call from every service entrypoint."""
    global _configured
    if _configured:
        return
    lvl_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    # Replace any pre-existing handlers (uvicorn installs default plain handlers)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(lvl)

    # Align uvicorn/FastAPI loggers with ours
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(lvl)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def bind_request_id(rid: str | None = None) -> str:
    rid = rid or uuid.uuid4().hex[:16]
    _request_id.set(rid)
    return rid


def current_request_id() -> str:
    return _request_id.get()
