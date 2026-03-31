# Changelog

All notable changes to RichSinkhole are documented here.

---

## 2026-03-31

### Added
- **Bandwidth estimation** — per-device bandwidth saved (blocked x 75KB) and used (forwarded x 300KB) in `/api/devices/{ip}/stats`
- **Bedtime grace period** — `grace_minutes` field on schedule rules (0-60 min); during grace, DNS redirects to warning page instead of hard-blocking
- **Family activity digest** — email digest now includes per-device breakdown: top 10 devices by query volume with name, type, queries, blocked count, block percentage
- **DNS speed test** — `/api/speedtest` endpoint with historical latency stats (avg/min/max/p50/p95 from last 24h) and live probes against 5 well-known domains
- **IoT quarantine profile** — new `quarantine` device profile allows only essential DNS (captive portal detection, NTP, OCSP); all other queries sinkholed. Auto-quarantine for new devices (opt-in via `auto_quarantine` config flag)
- **Guest profile** — new `guest` device profile applies strict blocking (same as `strict` plus service blocks); designed for temporary/unknown devices
- **Dark web monitoring** — detects `.onion` and `.i2p` resolution attempts and known Tor infrastructure domains; logs as `darkweb_attempt` / `darkweb_access` security events
- **App usage dashboard** — `/api/app-usage/{ip}` endpoint maps DNS queries to 18 apps (YouTube, Facebook, Instagram, TikTok, WhatsApp, Netflix, Spotify, etc.); estimates session count and usage time via 5-minute session clustering

### UI
- **Speed test panel** in Settings tab — historical latency stats (avg/p50/p95/max) + live probe results with color-coded latency; "Run Speed Test" button
- **App usage tab** in device stats modal — per-device app breakdown with estimated usage time, session count, and query count for 18 apps; lazy-loaded on first click
- **Bandwidth cards** in device stats modal — shows bandwidth saved (blocked) and estimated bandwidth used (forwarded) in MB
- **Grace period field** in schedule rule form — input for 0-60 minutes warning before hard block; persisted and editable
- **Quarantine/Guest profiles** in device profile dropdown — two new options alongside Normal/Strict/Passthrough
- **Dark web events** visible in Security tab — new `darkweb_attempt` and `darkweb_access` event types from `.onion`/`.i2p` detection

### Fixed
- **Device fingerprint accuracy overhaul** — removed false-positive Android signals (`android.clients.google.com`, `mtalk.google.com`) that Chrome on any OS queries; added truly OS-exclusive signals: Android GMS (`checkin.googleapis.com`, `play.googleapis.com`, `ota.googlezip.net`), Windows (`dns.msftncsi.com`, `prod.do.dsp.mp.microsoft.com`, `client.wns.windows.com`), Linux (`archive.ubuntu.com`, `api.snapcraft.io`, `packages.linuxmint.com`), Apple (`captive.apple.com`, `albert.apple.com`, `mesu.apple.com`), ChromeOS (`cros-omahaproxy.appspot.com`)
- **Automatic hostname detection** — devices that query bare hostnames (e.g. `chadpc`, `rpihole`) or `.local` names get auto-labeled; runs on both forwarded and NXDOMAIN responses

---

## 2026-03-30

### Added
- **Redirect chain detection** — real-time detection of affiliate hijacking (unknown -> attribution -> deep link pattern within 3s); auto-blocks trigger domains and logs security events
- **Blocked services: Tracking & Redirects** — 3 new toggleable services: Affiliate Redirects (onelink.me, adjust.com, branch.io, etc.), Ad Trackers (pangle.io, criteo, taboola, etc.), Piracy File Hosts (downloadwella.com, mixdrop, streamtape, etc.); auto-enabled on startup
- **14 default blocklist sources** — built-in feeds for ads, trackers, popups, phishing, scam, adult content, Samsung/Xiaomi/TikTok native trackers (Hagezi, ShadowWhisperer, curbengh, BlockListProject); shown with `default` badge in UI, cannot be removed
- **AdBlock format parsing** — updater now supports `||domain^` format in addition to hosts and plain domain lists
- **Stale source auto-disable** — sources unchanged for N days (configurable 30-365, default 90) auto-disabled; 3+ consecutive fetch failures also auto-disable
- **Blocklist update progress bar** — real-time progress (fetching N/M sources, writing DB, indexing, finalizing) with `/api/updater/progress` endpoint polled every 2s
- **130+ privacy report company mappings** — covers Google, Meta, Microsoft, Amazon, ByteDance, Samsung, Xiaomi, Shopee, Tencent, Cloudflare, Akamai, Brave, Reddit, DuckDuckGo, GCash, Maya, Atlassian, and many more; unmatched domains show parent domain instead of generic "Other"
- **Tab persistence** — active dashboard tab saved in URL hash; browser refresh stays on current tab
- **Custom modal dialogs** — dark-themed confirm/prompt dialogs replace all 7 native browser dialogs
- **Login rate limiting** — 5 failed attempts per IP in 5-minute window, then locked out; applies to both web form and `/api/auth/login` (returns 429)
- **Configurable digest frequency** — weekly/monthly/yearly email digest replaces daily; configurable day-of-week, day-of-month, and hour

### Fixed
- **Starlette 1.0.0 breaking change** — updated all 8 TemplateResponse calls to new `(request, name, context=)` signature; pinned FastAPI <1.0 and uvicorn <1.0 in Dockerfile
- **Blocked queries excluded from rate/burst counters** — ad SDK bursts (AppsFlyer, Pangle, inner-active) no longer penalize legitimate DNS from the same device
- **Windows "No Internet" status** — removed Windows NCSI domains (msftconnecttest.com, msftncsi.com, ipv6.msftconnecttest.com) from captive portal redirect
- **Device fingerprint accuracy** — removed connectivitycheck.gstatic.com from Android signals (Chrome on any OS queries it); boosted Windows-exclusive and Android-exclusive signal weights
- **Digest re-send on restart** — `_last_digest_sent` now initializes to today's date on startup

### Changed
- `/health` returns only `{"status":"ok"}` to unauthenticated requests; full breakdown requires auth
- `/metrics` removed from public paths — now requires authentication
- Health check error messages sanitized (no exception details exposed)
- Blocklist sources split into default (hardcoded in `default_sources.py`) and user-added (in `sources.yml`)

---

## 2026-03-24

### Added
- AdGuard-style blocked services with DNS enforcement

---

## 2026-03-21

### Added
- Facebook MITM proxy, whitelist UI, startup optimization

---

## 2026-03-16

### Changed
- Merged 4 Python services (DNS, dashboard, updater, YouTube proxy) into single sinkhole container for Raspberry Pi 3B support
