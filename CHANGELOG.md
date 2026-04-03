# Changelog

All notable changes to RichSinkhole are documented here.

---

## 2026-04-01

### Native Apps
- **Updated types.ts** — added BlockedServices, SpeedTest, AppUsage, DeviceStats, NtpClients, UpdaterProgress, PrivacyReportDevice types
- **Devices screen** — added Guest/Quarantine profiles; device detail now shows bandwidth stats (saved/used MB) and app usage chart (top 8 apps with estimated time)
- **Schedules screen** — rewritten to match current API (label, client_ip, digit-string days, grace_minutes); removed old profile mode radio buttons
- **Settings screen** — added DNS Speed Test panel (historical p50/p95 + live probes), NTP synced clients display, source_stale_days setting
- **Blocklist screen** — added Update Now button with real-time progress bar; new "Services" tab with toggleable blocked services grid (Social Media, Streaming, Gaming, Shopping, AI, Adult, Gambling, Tracking)
- **Privacy screen** — updated to match current API format (companies with progress bars instead of old categories); shows device_type and company percentages

## 2026-04-03

### Added
- **Backup & Restore UI** — Settings tab panel with Backup Now button (spinner), backup list with date+time folders, Restore and Delete per backup, configurable backup directory path
- **Backup API** — `/api/backups` (list), `/api/backups/run` (trigger), `/api/backups/restore` (restore), `/api/backups/{date}` (delete), `/api/backups/config` (get/set backup dir)
- **NAS data storage** — sinkhole data and backups stored on NAS via NFS; configurable via `DATA_DIR` and `BACKUP_DIR` env vars in docker-compose

### Changed
- **Captive portal one-shot** — redirects new devices only ONCE to show cert install page, then stops so connectivity checks pass normally; no more persistent "no internet"
- **Replaced Google DNS everywhere** — switched to Quad9 (9.9.9.9) + Cloudflare (1.1.1.1) in docker-compose, dashboard, and QR code generator
- **Docker-compose data volumes** — configurable via `DATA_DIR` and `BACKUP_DIR` env vars; supports NAS mount paths

### Fixed
- **Fresh install allowlist** — restored 30 essential domains (YouTube CDN, Shopee, GCash, Maya, Lazada, Garena, Apple, Firebase) for Philippine apps on new installs

---

### Added
- **GeoIP country blocking** — blocks domains resolving to Chinese IPs using a 326k-range ip2country database (auto-downloaded from GitHub). Applies to ALL devices including passthrough. Exempt list protects Shopee, GCash, Lazada, TikTok, Maya. Configurable via `geo_block_enabled` and `geo_block_countries` in config.
- **Spyware/surveillance detection** — blocks known stalkerware (mSpy, FlexiSpy, Cocospy, Spyera, etc.), Chinese surveillance SDKs (Igexin, ADUPS, Ragentek), and commercial spyware (NSO Group Pegasus, Cytrox Predator). Applies to ALL devices — never exempt. Logged as `spyware_detected` security events.
- **Chinese telemetry blocklist** — 40 domains covering Alibaba Cloud, Tencent, Baidu, Xiaomi, Huawei, Oppo/Vivo, ByteDance, Qihoo 360, and Chinese ad networks

### Changed
- **Default sources reduced from 14 to 9** — removed ShadowWhisperer Tracking (~97k, broke Teams/YouTube/Shopee/GCash), Hagezi referral (broke GCash via adzerk CNAME), Hagezi Samsung/Xiaomi/TikTok native trackers (too aggressive). Kept: ads (3), porn (3), phishing/scam (2), popups (1)
- **CNAME cloaking changed to log-only** — was blocking legitimate apps that CNAME to shared CDN/ad infrastructure (GCash->adzerk, Maya->hubspot, Teams->trafficmanager). Now logs as security event without blocking
- **Auto-block entries tagged `source='auto'`** — prevents stale `source=NULL` entries from accumulating after table swaps
- **Allowlist cleaned to 10 entries** — only YouTube/Google CDN essentials; was 101 entries of band-aid fixes

### Added
- **DNS-over-HTTPS bypass detection** — blocks devices from resolving known DoH/DoT providers (dns.google, cloudflare-dns.com, dns.quad9.net, dns.nextdns.io, dns.adguard.com, and 25+ more); prevents malware and browsers from bypassing the sinkhole via encrypted DNS. Three modes: `block` (default), `log` (monitor only), `off`. Configurable via `doh_bypass_mode` in config. Logged as `doh_bypass` security events. Includes Firefox canary domain (`use-application-dns.net`) which disables Firefox's built-in DoH when blocked.

### Improved
- **DNS caching** — sinkhole cache increased from 5k to 15k entries; minimum TTL enforced at 300s (5 min) to reduce re-queries for low-TTL CDN domains; Unbound serve-expired-ttl raised to 24h with 1.8s client timeout for instant stale responses; freed 96MB RAM on Pi by reducing Unbound cache sizes

### Fixed
- **YouTube thumbnails blocked** — `i.ytimg.com` was a stale blocklist entry; added YouTube CDN domains (`i.ytimg.com`, `i1.ytimg.com`, `s.ytimg.com`, `yt3.ggpht.com`, `s.youtube.com`) to permanent allowlist
- **Microsoft Teams blocked** — CNAME cloaking detection false positive: `config.edge.skype.com` CNAME'd to `*.trafficmanager.net` which was in blocklist feeds; added Teams/Skype/Office essential domains to allowlist and `trafficmanager.net`
- **Teams telemetry blocked** — parent domain `data.microsoft.com` (custom entry) caught `teams.events.data.microsoft.com` via parent matching; added to allowlist
- **CNAME cloaking bypass for allowed domains** — CNAME cloaking check now skips if the original domain is in the allowlist, preventing false positives where allowed domains CNAME to blocked infrastructure (e.g. Azure Traffic Manager, Akamai CDN)

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

### Added
- **NTP synced clients UI** — Settings tab > NTP Server > "Show Clients" button shows table of devices syncing with the sinkhole NTP (IP, label, device type, sync count, last sync with color-coded recency); Docker internal IPs filtered out

### Fixed
- **JS syntax error broke entire dashboard** — escaped backtick in NTP clients template literal caused app.js parse failure; rewrote as string concatenation
- **NTP clients parsing** — Docker exec stream header byte prepended to first IP (showed `0172.16.10.3`); fixed with regex IP extraction
- **App usage false positives** — minimum 5 queries per app required to show in usage report; filters out browser prefetches and embedded widgets (e.g. Discord showing from 2 CDN queries)
- **NTP server crash loop** — stale PID file from previous run prevented chronyd from starting; now cleaned on container start
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
