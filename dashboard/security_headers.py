# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Per-request CSP nonce + application-level security headers.

nginx also sets baseline headers (X-Frame-Options, X-Content-Type-Options,
Referrer-Policy, Permissions-Policy) but it cannot mint a per-request
nonce, so CSP is enforced here. Templates read `request.state.csp_nonce`
and emit it as `<script nonce="...">` / `<style nonce="...">`.
"""
from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

import jsonlog


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Bind a request id for structured logging correlation
        rid = jsonlog.bind_request_id(request.headers.get("x-request-id"))
        # Mint a fresh CSP nonce for this request
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # CSP — nonce-based, no 'unsafe-inline'. Bootstrap is self-hosted so
        # 'self' is sufficient for scripts/styles. data: URIs are only allowed
        # for images (dashboard uses an inline SVG favicon).
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'nonce-{nonce}' 'unsafe-hashes'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Request-ID", rid)
        # Belt-and-braces — nginx sets these too but we want them even when the
        # dashboard is hit directly during local dev / healthchecks.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        return response
