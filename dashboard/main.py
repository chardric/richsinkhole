# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

import asyncio
import base64
import hashlib
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import notifier
from routers import allowlist, app_usage, audit_logs, backup, blocked_services, blocklist, canary, device_stats, devices, dns_records, doh, health, heatmap, logs, metrics, network_score, ntp, parental, privacy_report, proxy_rules, qr, schedules, security, services, sessions as sessions_router, settings, speedtest, stats, unbound_settings, updater
import audit
import auth
import jsonlog
from security_headers import SecurityHeadersMiddleware

jsonlog.configure()
_log = jsonlog.get_logger("dashboard")

SINKHOLE_DB = "/data/sinkhole.db"
BLOCKLIST_DB = "/local/blocklist.db"
CERT_PATH = "/certs/ca.crt"

HOST_IP = os.getenv("HOST_IP", "")
# Sub-path prefix when served behind a reverse proxy (e.g. /richsinkhole)
ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")


def _portal_url(request: Request) -> str:
    """Return absolute URL to the captive portal page."""
    if HOST_IP:
        return f"http://{HOST_IP}/captive-portal"
    # Fall back to the request's own host
    return str(request.base_url).rstrip("/") + "/captive-portal"


def _real_ip(request: Request) -> str:
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.client.host
    )


def _is_whitelisted(ip: str) -> bool:
    try:
        with sqlite3.connect(SINKHOLE_DB) as conn:
            row = conn.execute(
                "SELECT 1 FROM captive_whitelist WHERE ip=?", (ip,)
            ).fetchone()
            return row is not None
    except Exception:
        return False


def _whitelist_ip(ip: str) -> None:
    # Never whitelist infrastructure/router IPs — they forward DNS on behalf of
    # many clients, so whitelisting them would redirect YouTube for all clients
    try:
        import yaml
        with open("/config/config.yml") as f:
            cfg = yaml.safe_load(f) or {}
        if ip in set(cfg.get("rate_limit_exempt_ips", [])):
            return
    except Exception:
        pass
    with sqlite3.connect(SINKHOLE_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO captive_whitelist (ip, ts) VALUES (?, datetime('now'))",
            (ip,),
        )
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.ensure_session_secret()
    for db_path in (SINKHOLE_DB, BLOCKLIST_DB):
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()
    # Captive portal whitelist table
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS captive_whitelist (
                ip TEXT PRIMARY KEY,
                ts TEXT NOT NULL
            )
        """)
        await db.commit()
    # Parental control tables + column migrations
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await parental.ensure_tables(db)
    # Audit tables: activity_logs, error_logs, email_logs, sessions
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await audit.ensure_tables(db)
    # Auto-enable tracking/redirect blocking services on first run
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS blocked_services (
            service_id TEXT PRIMARY KEY,
            enabled_at TEXT DEFAULT (datetime('now'))
        )""")
        for svc_id in ("affiliate_redirects", "ad_trackers", "piracy_hosts"):
            await db.execute(
                "INSERT OR IGNORE INTO blocked_services (service_id) VALUES (?)",
                (svc_id,),
            )
        await db.commit()
    asyncio.create_task(notifier.run_notifier())
    yield


app = FastAPI(title="RichSinkhole Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],          # same-origin only; no cross-origin access
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

from starlette.middleware.base import BaseHTTPMiddleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=auth.auth_middleware)


# ── Global exception → error_logs ─────────────────────────────────────────────
@app.exception_handler(Exception)
async def _exception_to_audit(request: Request, exc: Exception):
    audit.log_error(
        f"Unhandled {type(exc).__name__}: {exc}",
        exc=exc,
        request=request,
    )
    _log.exception("unhandled_exception", extra={"path": request.url.path})
    return JSONResponse({"error": "internal_server_error"}, status_code=500)

app.mount("/static", StaticFiles(directory="/dashboard/static"), name="static")
templates = Jinja2Templates(directory="/dashboard/templates")

app.include_router(stats.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(blocklist.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(updater.router, prefix="/api")
app.include_router(qr.router, prefix="/api")
app.include_router(security.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(device_stats.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")
app.include_router(allowlist.router, prefix="/api")
app.include_router(dns_records.router, prefix="/api")
app.include_router(canary.router, prefix="/api")
app.include_router(privacy_report.router, prefix="/api")
app.include_router(proxy_rules.router, prefix="/api")
app.include_router(ntp.router, prefix="/api")
app.include_router(heatmap.router, prefix="/api")
app.include_router(network_score.router, prefix="/api")
app.include_router(unbound_settings.router, prefix="/api")
app.include_router(services.router, prefix="/api")
app.include_router(blocked_services.router, prefix="/api")
app.include_router(speedtest.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(app_usage.router, prefix="/api")
app.include_router(audit_logs.router, prefix="/api")
app.include_router(sessions_router.router, prefix="/api")
app.include_router(parental.router)
app.include_router(metrics.router)
app.include_router(health.router)

app.include_router(doh.router)


# ─── Captive portal detection endpoints ────────────────────────────────────────

# Expected success responses per OS (path suffix → response)
_CAPTIVE_SUCCESS = {
    "hotspot-detect.html":          (200, "text/html",  "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"),
    "library/test/success.html":    (200, "text/html",  "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"),
    "success.html":                 (200, "text/html",  "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"),
    "canonical.html":               (200, "text/html",  '<meta http-equiv="refresh" content="0;url=https://support.mozilla.org/kb/captive-portal">'),
    "generate_204":                 (204, "text/plain", ""),
    "check_network_status.txt":     (204, "text/plain", ""),
    "connecttest.txt":              (200, "text/plain", "Microsoft Connect Test"),
    "ncsi.txt":                     (200, "text/plain", "Microsoft NCSI"),
    "success.txt":                  (200, "text/plain", ""),
}


@app.api_route("/captive/{path:path}", methods=["GET", "HEAD"])
async def captive_check(request: Request, path: str):
    client_ip = _real_ip(request)
    if _is_whitelisted(client_ip):
        key = path.lstrip("/")
        status, ctype, body = _CAPTIVE_SUCCESS.get(key, (200, "text/html", "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"))
        return Response(content=body.encode(), status_code=status, media_type=ctype)
    return RedirectResponse(url=_portal_url(request), status_code=302)


@app.post("/captive/accept")
async def captive_accept(request: Request):
    client_ip = _real_ip(request)
    _whitelist_ip(client_ip)
    return JSONResponse({"status": "ok", "ip": client_ip})


@app.post("/captive/skip")
async def captive_skip(request: Request):
    """Skip the cert install — whitelist the device so internet works."""
    client_ip = _real_ip(request)
    _whitelist_ip(client_ip)
    return JSONResponse({"status": "ok", "ip": client_ip})


@app.get("/captive-portal", response_class=HTMLResponse)
async def captive_portal(request: Request):
    client_ip = _real_ip(request)
    cert_confirmed = _is_whitelisted(client_ip)
    host_ip = HOST_IP or request.headers.get("host", "").split(":")[0]
    # Auto-whitelist on page visit — internet access is never blocked
    if not cert_confirmed:
        _whitelist_ip(client_ip)
    return templates.TemplateResponse(request, "captive.html", context={
        "host_ip": host_ip,
        "cert_confirmed": cert_confirmed,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    })


# ─── CA cert and mobileconfig ─────────────────────────────────────────────────

@app.get("/install-cert.sh")
async def install_cert_script(request: Request):
    raw_ip = HOST_IP or request.headers.get("host", "").split(":")[0]
    # Sanitize — only allow valid IP/hostname characters to prevent shell injection
    import re as _re
    server_ip = raw_ip if _re.match(r'^[a-zA-Z0-9\.\-]+$', raw_ip) else "10.254.254.4"
    script = f"""#!/usr/bin/env bash
set -e

SERVER="{server_ip}"
CERT_URL="http://$SERVER/ca.crt"
CERT_NAME="richsinkhole-ca"
CERT_FILE="/tmp/$CERT_NAME.crt"

echo "==> Downloading RichSinkhole CA certificate..."
curl -fsSL "$CERT_URL" -o "$CERT_FILE"

echo "==> Installing system-wide (requires sudo)..."
sudo cp "$CERT_FILE" "/usr/local/share/ca-certificates/$CERT_NAME.crt"
sudo update-ca-certificates

install_nss() {{
    local db="$1"
    if [ -d "$db" ]; then
        certutil -A -n "RichSinkhole CA" -t "CT,," -i "$CERT_FILE" -d "sql:$db" 2>/dev/null && \\
            echo "   Installed in: $db" || true
    fi
}}

if command -v certutil &>/dev/null; then
    echo "==> Installing in browser NSS databases..."
    # Firefox profiles
    for db in "$HOME/.mozilla/firefox/"*.default* "$HOME/.mozilla/firefox/"*.default-release*; do
        install_nss "$db"
    done
    # Flatpak Firefox
    for db in "$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox/"*.default*; do
        install_nss "$db"
    done
    # Chrome / Chromium
    mkdir -p "$HOME/.pki/nssdb"
    certutil -d "sql:$HOME/.pki/nssdb" -N --empty-password 2>/dev/null || true
    install_nss "$HOME/.pki/nssdb"
else
    echo "   [!] certutil not found — skipping browser install."
    echo "   Run: sudo apt install libnss3-tools"
    echo "   Then re-run this script."
fi

echo "==> Whitelisting this device..."
curl -fsS -X POST "http://$SERVER/captive/accept" -o /dev/null

echo ""
echo "Done! YouTube ads are now blocked on this device."
echo "You may need to restart your browser for the certificate to take effect."
"""
    return Response(
        content=script.encode(),
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="install-cert.sh"'},
    )


@app.get("/ca.crt")
async def ca_cert():
    try:
        content = Path(CERT_PATH).read_bytes()
    except FileNotFoundError:
        return Response(content=b"Certificate not found", status_code=404)
    return Response(
        content=content,
        media_type="application/x-x509-ca-cert",
        headers={"Content-Disposition": 'attachment; filename="richsinkhole-ca.crt"'},
    )


@app.get("/ca.mobileconfig")
async def ca_mobileconfig():
    try:
        pem = Path(CERT_PATH).read_text()
    except FileNotFoundError:
        return Response(content=b"Certificate not found", status_code=404)
    # Strip PEM headers to get raw base64 DER
    cert_b64 = "\n".join(
        line for line in pem.strip().splitlines() if not line.startswith("-----")
    )
    profile = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>PayloadCertificateFileName</key>
      <string>richsinkhole-ca.crt</string>
      <key>PayloadContent</key>
      <data>{cert_b64}</data>
      <key>PayloadDescription</key>
      <string>RichSinkhole CA Certificate</string>
      <key>PayloadDisplayName</key>
      <string>RichSinkhole CA</string>
      <key>PayloadIdentifier</key>
      <string>com.richsinkhole.ca.cert</string>
      <key>PayloadType</key>
      <string>com.apple.security.root</string>
      <key>PayloadUUID</key>
      <string>{str(uuid.uuid4()).upper()}</string>
      <key>PayloadVersion</key>
      <integer>1</integer>
    </dict>
  </array>
  <key>PayloadDescription</key>
  <string>Installs the RichSinkhole CA certificate for transparent YouTube ad blocking</string>
  <key>PayloadDisplayName</key>
  <string>RichSinkhole Network</string>
  <key>PayloadIdentifier</key>
  <string>com.richsinkhole.profile</string>
  <key>PayloadOrganization</key>
  <string>RichSinkhole</string>
  <key>PayloadType</key>
  <string>Configuration</string>
  <key>PayloadUUID</key>
  <string>{str(uuid.uuid4()).upper()}</string>
  <key>PayloadVersion</key>
  <integer>1</integer>
</dict></plist>"""
    return Response(
        content=profile.encode(),
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": 'attachment; filename="richsinkhole.mobileconfig"'},
    )


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def api_login(request: Request, payload: dict = Body(...)):
    """JSON login endpoint for native mobile/desktop apps. Returns a Bearer token."""
    client_ip = request.headers.get("x-real-ip", request.headers.get("x-forwarded-for", request.client.host or "")).split(",")[0].strip()
    password = str(payload.get("password", ""))
    totp_code = str(payload.get("totp", "") or payload.get("code", ""))
    if not auth.is_password_set():
        # First-run: set password via app
        if len(password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        auth.set_password(password)
        audit.log_activity("auth.password_initial_set", request=request)
    else:
        if not auth.check_login_rate(client_ip):
            audit.log_activity("auth.rate_limited", request=request, details={"ip": client_ip})
            raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
        if not auth.check_password(password):
            auth.record_login_attempt(client_ip)
            audit.log_activity("auth.login_failed", request=request, details={"ip": client_ip})
            raise HTTPException(401, "Invalid credentials")
        if auth.is_totp_enabled():
            if not totp_code or not auth.verify_totp_code(totp_code):
                auth.record_login_attempt(client_ip)
                audit.log_activity("auth.totp_failed", request=request)
                raise HTTPException(401, "Invalid 2FA code")
    auth.clear_login_attempts(client_ip)
    token = auth.make_session_token()
    auth.persist_session(token, request)
    audit.log_activity("auth.login", request=request)
    return {"token": token}


@app.post("/api/auth/refresh")
async def api_refresh(request: Request):
    """Rotate the current session token (refresh-token rotation).
    Returns a new token; the old one is invalidated. Replay of the old token
    burns the entire family and forces re-auth (compromise detection)."""
    header = request.headers.get("Authorization", "")
    old = header[7:] if header.startswith("Bearer ") else request.cookies.get("rs_session", "")
    if not old or not auth.verify_session_token(old, touch=False):
        raise HTTPException(401, "Invalid session")
    new_token = auth.rotate_session_token(old, request)
    if not new_token:
        audit.log_activity("auth.refresh_replay_detected", request=request)
        raise HTTPException(401, "Session replay detected — re-authenticate")
    audit.log_activity("auth.refresh", request=request)
    return {"token": new_token}


@app.post("/api/auth/change-password")
async def api_change_password(request: Request, payload: dict = Body(...)):
    """Change admin password. Requires current password for verification.
    All existing sessions are revoked (global rule)."""
    current = str(payload.get("current_password", ""))
    new_pw  = str(payload.get("new_password", ""))
    if not auth.check_password(current):
        audit.log_activity("auth.password_change_failed", request=request)
        raise HTTPException(401, "Current password is incorrect")
    if len(new_pw) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    auth.set_password(new_pw)     # also revokes all sessions
    audit.log_activity("auth.password_changed", request=request)
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", context={
        "error": error,
        "root_path": ROOT_PATH,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
        "totp_required": auth.is_totp_enabled(),
    })


@app.post("/login")
async def login_submit(request: Request):
    nonce = getattr(request.state, "csp_nonce", "")
    def _login_err(msg, **extra):
        return templates.TemplateResponse(request, "login.html", context={
            "error": msg, "root_path": ROOT_PATH, "csp_nonce": nonce, **extra,
        })
    client_ip = request.headers.get("x-real-ip", request.headers.get("x-forwarded-for", request.client.host or "")).split(",")[0].strip()
    form = await request.form()
    password = form.get("password", "")
    totp_code = str(form.get("totp", ""))
    if not auth.is_password_set():
        if len(str(password)) < 8:
            return _login_err("Password must be at least 8 characters.", setup=True)
        auth.set_password(str(password))
        audit.log_activity("auth.password_initial_set", request=request)
    else:
        if not auth.check_login_rate(client_ip):
            audit.log_activity("auth.rate_limited", request=request, details={"ip": client_ip})
            return _login_err("Too many login attempts. Try again in 15 minutes.")
        if not auth.check_password(str(password)):
            auth.record_login_attempt(client_ip)
            audit.log_activity("auth.login_failed", request=request, details={"ip": client_ip})
            return _login_err("Incorrect password.", totp_required=auth.is_totp_enabled())
        if auth.is_totp_enabled():
            if not totp_code or not auth.verify_totp_code(totp_code):
                auth.record_login_attempt(client_ip)
                audit.log_activity("auth.totp_failed", request=request)
                return _login_err("Invalid 2FA code.", totp_required=True)
    auth.clear_login_attempts(client_ip)
    token = auth.make_session_token()
    auth.persist_session(token, request)
    audit.log_activity("auth.login", request=request)
    resp = RedirectResponse(url=f"{ROOT_PATH}/", status_code=302)
    auth.set_session_cookie(resp, token, request)
    return resp


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("rs_session", "")
    if token:
        audit.revoke_by_token(token)
    audit.log_activity("auth.logout", request=request)
    resp = RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)
    resp.delete_cookie("rs_session", path="/")
    return resp


# ─── Main pages ───────────────────────────────────────────────────────────────

_BOOT_TS = str(int(time.time()))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", context={
        "root_path": ROOT_PATH,
        "cache_bust": _BOOT_TS,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    })


@app.get("/admin/audit", response_class=HTMLResponse)
async def audit_page(request: Request):
    return templates.TemplateResponse(request, "audit.html", context={
        "root_path": ROOT_PATH,
        "cache_bust": _BOOT_TS,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    })


@app.get("/admin/sessions", response_class=HTMLResponse)
async def sessions_page(request: Request):
    return templates.TemplateResponse(request, "sessions.html", context={
        "root_path": ROOT_PATH,
        "cache_bust": _BOOT_TS,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    })


# ─── PWA ─────────────────────────────────────────────────────────────────────

@app.get("/manifest.webmanifest")
async def pwa_manifest():
    start = f"{ROOT_PATH}/" if ROOT_PATH else "/"
    return JSONResponse({
        "name": "RichSinkhole",
        "short_name": "Sinkhole",
        "description": "Self-hosted DNS sinkhole, ad blocker, and family network guardian",
        "start_url": start,
        "scope": start,
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "orientation": "any",
        "icons": [
            {"src": "static/icon-192.png", "sizes": "192x192", "type": "image/png",
             "purpose": "any maskable"},
            {"src": "static/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any maskable"},
        ],
    }, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/sw.js")
async def pwa_service_worker():
    sw_path = Path("/dashboard/static/sw.js")
    try:
        body = sw_path.read_bytes()
    except FileNotFoundError:
        body = b"// service worker missing"
    return Response(
        content=body,
        media_type="application/javascript",
        headers={
            # Must be re-fetched on every navigation so updates roll out
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": f"{ROOT_PATH}/" if ROOT_PATH else "/",
        },
    )


@app.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    import socket
    host_ip = HOST_IP
    if not host_ip:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("9.9.9.9", 80))
            host_ip = s.getsockname()[0]
            s.close()
        except Exception:
            host_ip = "YOUR_SERVER_IP"
    http_port = os.getenv("HTTP_PORT", "80")
    return templates.TemplateResponse(request, "setup.html", context={
        "root_path": ROOT_PATH,
        "host_ip": host_ip,
        "http_port": http_port,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    })
