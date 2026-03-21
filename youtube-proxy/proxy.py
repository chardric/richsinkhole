#!/usr/bin/env python3
# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
RichSinkhole YouTube Transparent Proxy
- Streams all responses without buffering (fast video loads)
- Intercepts ad-related API endpoints and strips ad fields from JSON
"""

import json
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("yt-proxy")

_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        verify=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        limits=httpx.Limits(
            max_connections=200,
            max_keepalive_connections=50,
            keepalive_expiry=30,
        ),
        follow_redirects=False,
    )
    yield
    await _client.aclose()


app = FastAPI(lifespan=lifespan)

UPSTREAM_MAP = {
    # YouTube
    "youtube.com":               "https://www.youtube.com",
    "www.youtube.com":           "https://www.youtube.com",
    "m.youtube.com":             "https://m.youtube.com",
    "youtu.be":                  "https://youtu.be",
    "yt.be":                     "https://yt.be",
    "youtubei.googleapis.com":   "https://youtubei.googleapis.com",
    "suggestqueries.google.com": "https://suggestqueries.google.com",
    # Facebook
    "facebook.com":              "https://www.facebook.com",
    "www.facebook.com":          "https://www.facebook.com",
    "m.facebook.com":            "https://m.facebook.com",
    "web.facebook.com":          "https://web.facebook.com",
    "fb.com":                    "https://www.facebook.com",
    "www.fb.com":                "https://www.facebook.com",
}

AD_FIELDS = [
    "playerAds",
    "adSlots",
    "adPlacements",
    "adBreakHeartbeatParams",
    "auxiliaryUi",
    "interstitialAdRenderer",
    "paidContentOverlay",
    "adBreaks",
    "playerLegacyDesktopWatchAdsPayloadEntity",
    "linearAd",
    "nonLinearAd",
    "companionAdRenderer",
    "promotedVideoRenderer",
    "adInfoRenderer",
    "adPreviewRenderer",
    "skipOrPreviewRenderer",
]

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
}

# Endpoints whose JSON responses are buffered and stripped of ad fields.
# Everything else (video segments, images, etc.) is streamed directly.
AD_STRIP_PATHS = (
    "youtubei/v1/player",
    "youtubei/v1/next",
    "youtubei/v1/browse",
    "youtubei/v1/ad_break",
)


def _upstream(host: str) -> str:
    host = host.split(":")[0].lower()
    return UPSTREAM_MAP.get(host, f"https://{host}")


def _filter_headers(headers) -> dict:
    return {
        k: v for k, v in headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "content-length"
    }


def _strip_ads(content: bytes, content_type: str) -> bytes:
    if "json" not in content_type:
        return content
    try:
        data = json.loads(content)
        removed = []

        for field in AD_FIELDS:
            if field in data:
                data.pop(field)
                removed.append(field)

        if isinstance(data.get("streamingData"), dict):
            if "adBreaks" in data["streamingData"]:
                data["streamingData"].pop("adBreaks")
                removed.append("streamingData.adBreaks")

        # Strip from embedded stringified playerResponse (used in some API paths)
        if isinstance(data.get("playerResponse"), str):
            try:
                pr = json.loads(data["playerResponse"])
                pr_removed = []
                for field in AD_FIELDS:
                    if field in pr:
                        pr.pop(field)
                        pr_removed.append(f"playerResponse.{field}")
                if isinstance(pr.get("streamingData"), dict) and "adBreaks" in pr["streamingData"]:
                    pr["streamingData"].pop("adBreaks")
                    pr_removed.append("playerResponse.streamingData.adBreaks")
                if pr_removed:
                    data["playerResponse"] = json.dumps(pr)
                    removed.extend(pr_removed)
            except Exception:
                pass

        if removed:
            log.info("Stripped ad fields: %s", removed)
        return json.dumps(data).encode()
    except Exception:
        return content


async def start_yt_proxy(host: str = "0.0.0.0", port: int = 8000):
    """Start the YouTube proxy programmatically on the given host:port.

    Used by the unified sinkhole entrypoint. Runs uvicorn as an async task.
    """
    import uvicorn
    config = uvicorn.Config(
        app, host=host, port=port,
        proxy_headers=True, forwarded_allow_ips="*",
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def proxy(request: Request, path: str):
    host = request.headers.get("host", "youtube.com")
    upstream = _upstream(host)
    url = f"{upstream}/{path}"
    if request.url.query:
        url += f"?{request.url.query}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() not in ("host", "accept-encoding")
    }
    headers["host"] = host.split(":")[0]
    # Force gzip — httpx decompresses automatically; brotli would corrupt output
    headers["accept-encoding"] = "gzip, deflate"

    body = await request.body()
    # Note: FastAPI strips leading slash from {path:path}
    should_strip = any(ep in path for ep in AD_STRIP_PATHS)

    try:
        if should_strip:
            # Buffer the response so we can parse and strip ad fields
            resp = await _client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
            content_type = resp.headers.get("content-type", "")
            content = _strip_ads(resp.content, content_type)
            return Response(
                content=content,
                status_code=resp.status_code,
                headers=_filter_headers(resp.headers),
                media_type=content_type.split(";")[0].strip() or None,
            )
        else:
            # Stream response — no buffering, starts delivering to client immediately
            req = _client.build_request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
            )
            resp = await _client.send(req, stream=True)
            content_type = resp.headers.get("content-type", "")
            return StreamingResponse(
                resp.aiter_bytes(chunk_size=65536),
                status_code=resp.status_code,
                headers=_filter_headers(resp.headers),
                media_type=content_type.split(";")[0].strip() or None,
                background=BackgroundTask(resp.aclose),
            )

    except Exception as exc:
        log.error("Proxy error for %s: %s", url, exc)
        return Response(content=b"Bad Gateway", status_code=502)
