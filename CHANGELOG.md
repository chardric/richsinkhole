# Changelog

All notable changes to RichSinkhole are documented here.

---

## 2026-04-15

### Fixed — Scheduled backups silently producing 0-byte snapshots since 2026-04-04
- The cron entry on the host invoked `/usr/local/bin/sinkhole-backup.sh` directly, but the script's data paths (`/data/sinkhole.db`, `/data/blocklist.db`) only resolve **inside** the sinkhole container — on the host they don't exist, so SQLite errored with "unable to open database file" and the script left an empty dated folder behind every night. Worse: even when run from inside the container (the dashboard "Backup Now" button), `/data/sinkhole.db` was the stale Mar 24 file from the old storage layout — the live DBs moved to `/local/` (per `dns/server.py:49-50`) and the script was never updated.
- Fixes:
  - `scripts/sinkhole-backup.sh` (now version-controlled — was previously only on prod) reads from `/local/{sinkhole.db,blocklist.db,geoip-country.csv}` to match the live volume layout, also backs up `extra_routes.yml`, and refuses to leave a 0-byte folder (sanity check at the end deletes the dir and exits non-zero if the result is empty — a silent empty backup is worse than no backup at all).
  - Cron line updated on host to `docker exec -u root richsinkhole-sinkhole-1 /usr/local/bin/sinkhole-backup.sh ...` so it runs in the right namespace with NAS-write permission.
  - `dashboard/routers/backup.py:_update_cron()` now writes the same `docker exec` form when the user changes the schedule via the UI.
  - `install.sh` now installs the script via in-place truncate-write (so the docker bind mount stays valid without restarting the container) and seeds the cron entry on first run.
- Today's first good backup: 654.9 MB, 5 files (sinkhole.db 333 MB, blocklist.db 313 MB, geoip 9.6 MB, config.yml, extra_routes.yml).

### Added — Dashboard UI for static routes (Settings tab)
- New "STATIC ROUTES" card with a form to add `net / via / dev` triples and a per-row Remove button. The `dev` field is a dropdown auto-populated from the host's NICs (read from `host_interfaces.json`, written by the reconciler each run). A "Re-scan NICs" button touches the YAML to re-trigger the reconciler when a new LAN port is plugged in, so the new interface shows up in the dropdown without waiting for the 5-min safety-net timer.
- Backend: new `dashboard/routers/routes.py` with `GET/POST/DELETE /api/routes`, `GET /api/routes/interfaces`, `POST /api/routes/refresh`. YAML writes are atomic (tempfile + `os.replace`) so the path watcher never reads a half-written file.
- Reconciler now writes a `host_interfaces.json` snapshot next to the YAML on every run; service unit's `ReadWritePaths` was extended to include the data dir so `ProtectHome=read-only` doesn't block the snapshot write.

### Added — Static route reconciler for VLANs not directly attached to the sinkhole
- `scripts/route-reconciler.py` reads `/etc/sinkhole/extra_routes.yml` (real file lives at `data/config/extra_routes.yml` so it's part of the backup) and reconciles NetworkManager's `ipv4.routes` on each named device to exactly that list. Adds missing, removes stale, and applies live via `nmcli device reapply` without bouncing the connection. Idempotent — a no-op when state already matches.
- Three systemd units glue it together: a oneshot **service** (run on demand), a **path** unit (re-runs the service on file change via inotify), and a **timer** (5-minute safety-net reconcile in case the path watcher ever misses an event after a flurry of edits). Installer wires all three at install time and substitutes the real config path into the unit templates so inotify watches the actual file, not the `/etc/sinkhole/` symlink.
- Use case: the sinkhole had legs in only two of the six Omada VLANs (`172.16.10/24`, `172.16.30/24`), so DNS replies to clients on the other four (`172.16.20/40/50/60`) were black-holed by Linux's default-route fallback to MikroTik. Edit one YAML file to add a route via the Omada gateway on the eth2 subnet and the route appears live within seconds — same procedure for any future VLAN.
- File format:
  ```yaml
  routes:
    - { net: 172.16.20.0/24, via: 172.16.10.1, dev: eth2 }
  ```

### Fixed — Microsoft Teams sign-in / connectivity broken on client devices
- Whitelisted three Microsoft Edge service-ring endpoints that upstream hosts lists (StevenBlack, anudeepND) tag as telemetry but Teams requires: `a-ring.msedge.net`, `k-ring.msedge.net`, `fp.msedge.net`. Teams uses them for service discovery, connection routing, and health checks; sinkholing them to 0.0.0.0 leaves the client stuck on "Loading" or "We couldn't sign you in."
- Added the three hosts to the `whitelist:` block in `updater/sources.yml` so future syncs exclude them at fetch time, and allowlisted them on prod (`allowed_domains`) for immediate effect.
- Scope is intentionally narrow — only the three specific subdomains, not `*.msedge.net`. Other msedge.net hosts (e.g. `dual-s-msedge.net`, `ax-msedge.net`) already resolve normally and are the actual content/routing endpoints.

---

## 2026-04-14

### Added — Hagezi Threat Intelligence Feed (TIF) as a default source
- `updater/default_sources.py` now ships with Hagezi's TIF list (`hosts/tif.txt`), aggregating active threat data from OpenPhish, PhishTank, URLhaus, DigitalSide, and ThreatFox. Adds malware C2, stalkerware, cryptominers, scam shops, phishing kits, Magecart skimmers. Daily updates, curated for low false-positive rate. Roughly 1.1M domains on top of the existing ad/porn/phishing lists.

### Fixed — IG DMs/calls/refresh broken on mobile clients
- Removed `test-gateway.instagram.com` from `blocked_domains` on prod. This is Instagram's production MQTT realtime gateway (CNAME → `dgw-ig.c10r.facebook.com`), not a test server — the `test-` prefix is legacy naming from the pre-2019 FB/IG backend split. Blocking it silently kills DMs, call signaling, typing indicators, and feed refresh on IG mobile apps.
- Root cause: legacy `_AUTO_BLOCK_PATTERNS` heuristic auto-added any `test-*` hostname under `instagram.com`. The pattern list has since been emptied in code (`dns/server.py:366`), so new installs are unaffected, but the DB entry persisted on long-running instances.
- Also purged 13 other stale `source='auto'` entries that were legit services (Apple universal-link, NTP pool, Shopee/Garena CDNs, etc.) — same defunct heuristic's debris.

### Ops — Allowlist cleanup on prod
- Dropped the custom allowlist from 31 entries to 0. Audited each against the active blocklist feeds: 30 were redundant (nothing in any feed had them as a parent-domain match), and the only "currently blocked" entry (`app-measurement.com`) is a Firebase tracker most apps tolerate being blocked. If a real break surfaces, we add back one targeted entry with a documented note.

---

## 2026-04-13

### Fixed — Dashboard memory leaks (RSS growth on long-running instances)
- **`app_usage` cache unbounded** — `_usage_cache` keyed by `{ip}:{range}` grew forever as new devices queried the endpoint. Added hard cap of 500 entries with LRU eviction and opportunistic expiry sweep (`dashboard/routers/app_usage.py`).
- **Login rate-limit dicts unbounded** — `_login_attempts` and `_lockouts` in `dashboard/auth.py` only pruned the current IP on check; IPs from scanners, brute-force attempts, and DHCP churn stayed in memory forever. Added hourly sweep that drops IPs with no fresh attempts and expired lockouts.
- **SSE log stream — no lifetime or concurrency cap** — `/api/logs/stream` ran `while True`, holding an aiosqlite connection until the client disconnected. A stale browser tab kept the task alive indefinitely. Capped at 10 concurrent streams (503 beyond that) and 1-hour max per stream; `EventSource` auto-reconnects on close.

### Added — Host tuning in installer
- `install.sh` now runs a `tune_host` step that writes `/etc/sysctl.d/99-sinkhole.conf` (swappiness, UDP/socket buffers, netdev backlog) and, on Raspberry Pi hosts, appends `cgroup_enable=memory cgroup_memory=1` to `cmdline.txt` so `docker-compose` `mem_limit` is actually enforced. Both steps are idempotent and back up any file they touch; the Pi cgroup change requires a reboot to activate.

### Ops
- Applied sysctl tuning on prod (`/etc/sysctl.d/99-sinkhole.conf`): `vm.swappiness=10`, `net.core.rmem_max=4MB`, `net.core.netdev_max_backlog=5000`, `net.ipv4.udp_rmem_min=16KB`.
- Enabled memory cgroup controller on prod (added `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt`) so `mem_limit` in `docker-compose.yml` is actually enforced. Verified live after reboot.

---

## 2026-04-09

### Fixed — Passthrough bypass, timezone, fingerprinting
- **Passthrough no longer bypasses ad blocking** — `passthrough` profile previously skipped all blocking checks (blocklist, service blocks, DoH bypass detection). Now it only exempts devices from rate limiting, burst detection, schedule/bedtime, captive portal, YouTube redirect, and parental controls. Ad blocking and security checks remain enforced for all profiles.
- **SQLite timezone mismatch** — timestamps were stored in local time (Asia/Manila) but all `datetime('now')` comparisons used UTC, causing every time-filtered query (stats, session expiry, rate-limit expiry, data retention) to be off by 8 hours. Fixed 18 files to use `datetime('now', 'localtime')`.
- **Device fingerprint misclassification** — bare hostname DNS lookups (e.g. querying `icecast`) were wrongly treated as device self-identification, causing the querying device to be classified as the target service type. Now only `.local` mDNS and device probe results are used for type inference.
- **Missing devices in device list** — servers with static IPs that only query infrastructure domains never appeared in the Devices list. Now every IP that makes a DNS query gets a device entry automatically.
- **Unbound crash on restart** — `read_only: true` container with no tmpfs for `/var/lib/unbound` caused DNSSEC trust anchor writes to fail. Added tmpfs mount with correct ownership (uid=100/gid=101).
- **Unbound entrypoint** — re-creates DNSSEC root trust anchor on startup since tmpfs wipes `/var/lib/unbound` on each restart.

### Added
- `tp-link.com` device signature for TP-Link/Omada router fingerprinting
- `local-data/` added to `.gitignore` to prevent accidental database wipes during sync

### Removed
- `mikrotik-dns-force.txt`, `mikrotik-security-patch.rsc` — one-time MikroTik scripts no longer needed

---

## 2026-04-06

### Added — Security & Observability Hardening
- **Activity logs** — append-only `activity_logs` table tracking all admin actions (login, password change, settings, session revocations) with IP, user-agent, and JSON details
- **Error logs** — append-only `error_logs` table auto-capturing unhandled exceptions with stack traces and request context
- **Email logs** — `email_logs` table logging every outbound SMTP attempt (success/fail) for deliverability auditing
- **Admin audit UI** — `/admin/audit` page with 3 tabs (Activity, Errors, Email), search, pagination, CSV export
- **Structured JSON logging** — `jsonlog.py` replaces default logging with JSON-formatted stdout (ts, level, logger, message, request_id)
- **Request-ID correlation** — per-request UUID bound via middleware, flows through all logs and returned as `X-Request-ID` header
- **CSP with nonces** — `Content-Security-Policy` header with per-request random nonces; `unsafe-inline` eliminated from all 7 templates
- **Security headers middleware** — belt-and-braces X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy from app level
- **TOTP 2FA** — stdlib-only RFC 6238 implementation (no new deps); setup → QR URI → verify → enable; login requires TOTP when active
- **Session management** — persistent DB-backed `sessions` table with IP/UA fingerprints; `/admin/sessions` UI to list and revoke sessions
- **Refresh token rotation** — `POST /api/auth/refresh` rotates tokens in same family; replay of old token burns entire family (compromise detection)
- **15-minute lockout** — after 5 failed login attempts (was 5-min), rate limit + hard lockout
- **Secure cookie flag** — `rs_session` cookie gets `Secure` when `X-Forwarded-Proto: https` detected
- **PWA** — `manifest.webmanifest`, service worker (`sw.js`) with cache-first static / network-first API strategies, 192+512 icons, install support
- **Health endpoints** — `GET /health/live` (fast liveness), `GET /health/ready` (DNS + SQLite readiness, 503 on failure)
- **HEALTHCHECK** added to ntp (chronyc), unbound (drill), nginx (wget) in Dockerfiles/compose
- **Non-root USER** in sinkhole Dockerfile (UID 1000 `app` user)
- **Read-only rootfs** on all 4 containers (ntp, unbound, sinkhole, nginx) with tmpfs for writable dirs
- **GitHub Actions CI** — `security-scan.yml` with pip-audit (Python CVEs), py_compile lint

### Changed
- CDN dependency removed from `screen_time_warning.html` — Bootstrap now self-hosted
- Password change now revokes all active sessions
- Logout now revokes the session in DB (not just deletes cookie)
- Login error responses include `csp_nonce` for CSP compliance
- All `<script>` and `<style>` tags across all templates now carry `nonce` attributes
- **`sinkhole.db` moved from NAS to local SD card** — all critical databases now on local storage; DNS and dashboard survive NAS outages. NAS used only for updater status files and backups.
- **DGA detection upgraded** — composite scoring (entropy + consonant streaks + vowel-consonant transitions) replaces simple entropy-only check; log-only mode (too many CDN false positives for active blocking)
- **CSP `style-src`** — added `unsafe-inline` for dynamically generated inline styles (heatmap grid)

---

## 2026-04-05

### Added
- **Host-level mDNS/NetBIOS device probe** (`/usr/local/bin/rs-host-probe`) — runs hourly via cron to auto-label devices on the network. Uses multicast mDNS on directly-connected interfaces (eth0, eth1, eth2) and NetBIOS unicast for Windows PCs. Discovers real hostnames like `jellyfin`, `rpi3-home`, `chard-optiplex` without requiring changes to devices.
- **Hostname pattern inference** for device type classification — matches patterns like `rpi-*`, `jellyfin`, `eap225-*`, `raspberrypi` to auto-classify devices.
- **40+ new device signatures** — Tuya (iotbing.com), Xiaomi IoT, Raspberry Pi, Shelly, Sonoff, Philips Hue, Roku, Ring, Nest, Samsung/LG TVs, PlayStation, Xbox, Debian/Arch/Alpine Linux distros, and more.
- **Infrastructure device-type lock** — once a device matches network gear signatures (MikroTik, TP-Link, Ubiquiti), consumer-OS signals are ignored. Prevents routers from being mis-classified as Android/Apple due to DNS forwarding.

### Changed — NAS Resilience (Hybrid Storage)
- **`blocklist.db` + `geoip-country.csv` + `config/` moved to local SD** — critical files now survive NAS outages. If the NAS goes down, DNS resolution continues working.
- **`sinkhole.db` moved to local SD (2026-04-06)** — all databases now on local storage for full NAS independence.
- New `LOCAL_DATA` env var and `/local` volume mount in docker-compose.
- Updated 12 source files to read blocklist/geoip from `/local/` instead of `/data/`.
- Updated `backup.sh` and restore logic to handle split data directories.

### Fixed
- **Broken auto-labelling** — garbage labels like `xggd&F|x&gzo` were captured from malformed DNS queries. Now validates hostnames against RFC 1123 format and rejects hex hashes/UUIDs.
- **Omada router mis-classified as Android** — TP-Link signatures drowned out by Android queries being forwarded through the router. Fixed with infrastructure type lock.
- **mDNS parser skipped responses with qdcount=0** — mDNS responders may omit the question section; parser now handles this correctly.

## 2026-04-04

### Security Patches
- **CORS hardened** — removed wildcard `allow_origins=["*"]`; same-origin only
- **Sensitive fields stripped** — `GET /api/settings` no longer exposes session_secret, admin_password_hash, or SMTP password
- **Auth bypass fixed** — `/api/parental/snooze` now requires authentication
- **Session secret hardened** — removed "changeme" fallback; auto-generates if missing
- **Unbound upstream IP validation** — rejects non-IP input to prevent config injection
- **Backup path traversal fixed** — restricted `backup_dir` to safe prefixes (`/mnt/`, `/data/backups`)
- **Proxy rule injection fixed** — tightened URL regex to block nginx config metacharacters
- **DNS reply validation** — verifies upstream source IP and transaction ID to mitigate cache poisoning
- **Unbounded dict pruning** — periodic cleanup of rate/burst/anomaly counters; 10K IP cap prevents OOM
- **Pattern cache race fix** — added lock to blocker pattern reload
- **IPv6 rate limit bypass fixed** — normalizes `::ffff:` mapped addresses
- **DOM XSS fixed** — `confirmDialog` and `promptDialog` now escape all HTML
- **Host header injection fixed** — `install-cert.sh` sanitizes IP/hostname input
- **Parental block page XSS fixed** — `x-blocked-host` header sanitized
- **Verbose errors removed** — generic messages for backup config and pairing mode errors
- **Nginx security headers** — X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy
- **Docker hardening** — `cap_drop: ALL` + selective `cap_add` on all containers; `no-new-privileges` on sinkhole/ntp/nginx; pinned nginx image to `1.27-alpine`
- **Forwarded-allow-ips restricted** — only trusts proxy headers from private network ranges (was `*`)

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
- **Tuya Pairing Mode** — Settings toggle that temporarily unblocks Tuya/SmartLife domains for 5-120 minutes to pair new IoT devices; auto-re-blocks after timeout
- **Configurable backup schedule** — hour, minute, and retention days editable from dashboard; updates host cron automatically
- **Rate limit exempt IPs** — configurable in Settings > Rate Limits; infrastructure devices (routers) skip rate limiting but still get blocklist/GeoIP filtering
- **Hidden infrastructure in logs** — exempt IPs hidden from live query log and log API; only client devices shown
- **Infrastructure whitelist protection** — exempt IPs (routers) can never be captive-whitelisted, preventing YouTube redirect from breaking all clients behind the router
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
