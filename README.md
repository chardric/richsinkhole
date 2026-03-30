# RichSinkhole

A self-hosted DNS sinkhole and ad blocker for your home network, built with Python, FastAPI, Unbound, and Docker. Blocks ads, trackers, telemetry, and malicious domains at the DNS level — network-wide, no per-device software needed. Runs on any Linux machine including a Raspberry Pi 3B+.

---

## Features

### Blocking
- **DNS-level blocking** — blocks ads, trackers, telemetry, and malware for every device on the network
- **1M+ domains blocked** out of the box via 14 curated default feeds (ads, trackers, popups, phishing, scam, adult content, Samsung/Xiaomi/TikTok native trackers)
- **Subscription feed manager** — add/remove blocklist URLs; feeds auto-sync on a configurable schedule (daily, weekly, or monthly). Supports hosts file, plain domain list, and AdBlock (`||domain^`) formats
- **Default sources** — 14 built-in feeds that cannot be removed (Hagezi, ShadowWhisperer, curbengh, BlockListProject, etc.); user can add custom feeds on top
- **Stale source auto-disable** — sources with unchanged content for N days (configurable, default 90) are automatically disabled; sources with 3+ consecutive fetch failures also auto-disabled
- **Custom block list** — manually block individual domains
- **Allowlist** — permanently whitelist domains so they survive feed re-syncs
- **Threat intel feeds** — URLhaus and ThreatFox malware/phishing domains refreshed every 6 hours
- **Update progress bar** — real-time progress indicator when updating blocklists (fetching, writing, indexing, finalizing)

### Security
- **DNS rebinding shield** — blocks public domains resolving to private IPs
- **DGA detection** — composite entropy + bigram + consonant scoring flags suspected beaconing
- **DNS tunneling detection** — entropy + length + TXT record flood detection
- **Typosquat shield** — Levenshtein + homoglyph normalization protects against brand impersonation
- **NRD blocking** — daily newly-registered domain feed (HaGeZi NRD); Off/Warn/Block mode
- **ARP correlation** — enriches devices with MAC/vendor info; ghost detection for ARP-only devices
- **DNS leak detection** — probes upstream latency and DNSSEC health; flags devices bypassing the sinkhole
- **Protected brands** — configurable brand list for typosquat protection
- **Query burst auto-blocking** — rate limiting with per-device IoT thresholds and 60s startup grace period; blocked queries excluded from rate/burst counters to prevent ad SDK bursts from penalizing legitimate traffic
- **NXDOMAIN flood detection** — auto-blocks clients generating excessive NXDOMAIN responses
- **Redirect chain detection** — real-time detection of affiliate hijacking patterns (unknown domain -> attribution -> deep link within 3 seconds); auto-blocks trigger domains
- **Blocked services** — AdGuard-style toggleable service blocks: Social Media, Streaming, Messaging, Gaming, Shopping, AI, Adult, Gambling, Tracking & Redirects (affiliate redirects, ad trackers, piracy file hosts)
- **Login rate limiting** — 5 failed attempts per IP in 5-minute window, then locked out (web + API)
- **Protected endpoints** — `/metrics` requires auth; `/health` returns minimal data to unauthenticated requests
- **IoT quarantine** — new device profile that allows only essential DNS (captive portal, NTP, OCSP); auto-quarantine for new devices (opt-in)
- **Guest mode** — strict blocking profile for temporary/unknown devices
- **Dark web monitoring** — detects `.onion`/`.i2p` resolution attempts and known Tor infrastructure; logs security events
- **DNS speed test** — historical latency stats (avg/p50/p95) and live probes against well-known domains

### Parental Controls
- **Per-device parental controls** — block social media and gaming domains per device
- **Screen time budgets** — daily query limits per category (social/gaming); snooze button on warning page
- **Circadian / bedtime profiles** — schedule-based blocking with optional grace period (1-60 min warning before hard-block)
- **Block page** — smart per-device block page showing remaining budget and snooze option
- **App usage dashboard** — per-device app usage with estimated session time for 18 apps (YouTube, Facebook, TikTok, Netflix, Spotify, etc.)
- **Family activity digest** — periodic email includes per-device breakdown with queries, blocks, and block rate

### YouTube
- **YouTube ad blocking** — transparent HTTPS proxy strips pre/post-roll ads
- **SNI-based routing** — nginx routes `youtube.com` to the local proxy; other domains go to dashboard
- **CA certificate** — downloadable at `/ca.crt` and `/ca.mobileconfig` (Apple); one-time install per device
- **Devices without cert** — get real YouTube IPs; no breakage

### Network
- **Captive portal** — soft portal that auto-whitelists devices on page visit
- **Reverse proxy manager** — map `.lan` hostnames to LAN services (e.g. `nas.lan -> 192.168.1.50:5000`)
- **DNS-over-HTTPS** — built-in DoH endpoint (`/dns-query`) compatible with all major browsers
- **NTP server** — built-in chrony NTP server (port 123/UDP); toggle from Settings
- **HTTPS dashboard** — nginx serves dashboard on port 443 with self-signed cert

### Devices
- **Device fingerprinting** — auto-identifies device type by DNS patterns (Apple, Android, Windows, Samsung TV, Xbox, MikroTik, Xiaomi, Router, and more); improved accuracy by excluding Chrome-triggered signals from Android detection and boosting OS-exclusive signals
- **Per-device blocking profiles** — Normal, Strict, Passthrough, Quarantine, or Guest
- **Bandwidth estimation** — per-device estimated bandwidth saved and used
- **MAC/vendor info** — ARP-correlated vendor names shown per device
- **Ghost detection** — devices with ARP entries but no DNS queries in 24h marked with ghost icon
- **Schedule rules** — time-based blocking per device or network-wide

### Dashboard & Apps
- **React web dashboard** — dark theme, real-time query log, stat cards, query activity heatmap, network health score, SSE activity stream; tab persistence via URL hash (refresh stays on current tab)
- **Privacy report** — per-device domain breakdown with 130+ company mappings (Google, Meta, Microsoft, Amazon, ByteDance, Shopee, Tencent, and more); unmatched domains show parent domain name instead of generic "Other"
- **Custom modal dialogs** — dark-themed confirm/prompt dialogs replace native browser dialogs
- **Service controls** — restart Sinkhole, Unbound, and Nginx containers from the Settings tab
- **Configurable update schedule** — set blocklist sync frequency (daily/weekly/monthly), day, and time from Settings
- **Email digest** — configurable weekly/monthly/yearly digest reports (replaces daily); won't re-send on restart
- **Native desktop app** — Electron wrapper for Linux (AppImage + DEB) and Windows (NSIS installer); system tray with minimize-to-tray
- **Android app** — Capacitor-based APK
- **Webhook notifications** — alerts for blocklist updates, new devices, and daily summaries

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Sinkhole | Python, dnslib, FastAPI, httpx | DNS blocking, dashboard, updater, YouTube proxy |
| Recursive Resolver | Unbound | DNSSEC validation, DNS rebinding protection |
| NTP Server | chrony (Alpine) | Network time server |
| Reverse Proxy | Nginx | TLS, routing, static files |
| Infrastructure | Docker Compose | Container orchestration |

---

## Architecture

```
Clients (phones, laptops, smart TVs)
        |
        | DNS queries (port 53)
        v
  ┌─────────────────────────────────────┐
  │         Sinkhole Container          │
  │                                     │
  │  DNS Server (:53)                   │  blocks / forwards queries
  │  Dashboard  (:8080)                 │  web UI + REST API
  │  Updater    (background)            │  blocklist sync + threat intel
  │  YouTube Proxy (:8000)              │  ad-stripping reverse proxy
  └──────────────┬──────────────────────┘
                 │ allowed queries
                 v
  ┌─────────────────────┐
  │      Unbound        │  recursive resolver w/ DNSSEC
  └──────────┬──────────┘
             v
       Root DNS servers

  ┌─────────────────────┐
  │  NTP Server         │  chrony (port 123/UDP)
  └─────────────────────┘

  ┌─────────────────────┐
  │  Nginx              │  reverse proxy (ports 80/443), SNI routing
  └─────────────────────┘
```

All Python services run in a single container (one Python runtime) to minimize memory usage — fits comfortably on a Raspberry Pi 3B (1 GB RAM). Total steady-state: ~210 MB across all containers.

---

## Requirements

- Linux machine (x86_64 or ARM64 / Raspberry Pi 3B+)
- Docker Engine 24+
- Docker Compose v2+
- A static LAN IP address

---

## Quick Start

1. Clone the repo:

```bash
git clone https://github.com/chardric/richsinkhole.git
cd richsinkhole
```

2. Configure environment:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# LAN IP of this machine (required)
HOST_IP=192.168.1.10

# Host port for the web dashboard
HTTP_PORT=80

# Timezone
TZ=Asia/Manila
```

3. Install and start:

```bash
chmod +x install.sh
./install.sh
```

The installer will:
- Check for Docker and Docker Compose
- Generate a self-signed CA certificate for HTTPS interception
- Build all Docker images
- Start all services
- Verify health

4. Point your router's **primary DNS** to the `HOST_IP` you configured. All devices on your network will now have ads and trackers blocked at the DNS level.

5. Open the dashboard:

```
http://<HOST_IP>/richsinkhole/
```

Or use the **native desktop app** — see the [Native Apps](#native-apps) section below.

---

## Dashboard

| Tab | Description |
|-----|-------------|
| **Dashboard** | Query stats (total, blocked, block rate, clients), top blocked domains, query activity heatmap, network health score, live recent activity |
| **Query Logs** | Real-time DNS log with filter chips (All / Blocked / Allowed / Forwarded / Parental); inline Block/Allow actions |
| **Blocklist** | Subscription feed management, custom blocked domains, allowlist |
| **Devices** | Fingerprinted devices with MAC/vendor, per-device profile, parental controls, per-device stats |
| **Security** | Active blocks, security events (DGA, tunnel, typosquat, NRD, rebinding, burst), protected brands, DNS leak status |
| **Privacy** | Per-device domain breakdown and tracker analysis (24h/7d range) |
| **Schedules** | Time-based blocking rules per device or network-wide |
| **Settings** | Feature toggles (YouTube redirect, captive portal, NTP), NRD mode, blocklist update schedule, service controls, DNS leak results, change password, About |

---

## Blocklist Management

### Subscription feeds

The **Blocklist > Subscriptions** tab shows all feed sources. Built-in feeds (defined in `updater/sources.yml`) are labeled **built-in** and auto-sync on the configured schedule (daily by default at 3:00 AM). The update schedule — frequency (daily/weekly/monthly), day, and time — is configurable from **Settings > Blocklist Update Schedule**.

To add a custom feed:
1. Go to **Blocklist > Subscriptions**
2. Click **Add Feed**
3. Paste a URL — supports hosts file format (`0.0.0.0 domain.com`) or plain domain lists (one per line)

To remove a custom feed, click the delete button on the feed card. All domains from that feed are removed immediately.

### Unblocking a domain from a feed

Individual domains from subscription feeds cannot be deleted (they return on the next sync). Instead, add the domain to the **Allowlist** tab — it will be permanently whitelisted even after re-sync.

### Custom blocked domains

Go to **Blocklist > Custom** to manually block specific domains. These are independent of subscription feeds and can be deleted individually.

---

## YouTube Ad Blocking

1. Device visits `http://<HOST_IP>/richsinkhole/` (captive portal page)
2. Click **Install CA Certificate** and follow the instructions for your device
3. Once the cert is trusted, DNS for `youtube.com` and related domains is redirected to the local proxy
4. The proxy strips ad fields (`playerAds`, `adPlacements`, etc.) from YouTube API responses

Devices **without** the cert installed get real YouTube IPs — no breakage.

---

## Native Apps

Pre-built installers are in the `installer/` directory after running a build.

| Platform | Format | Location |
|----------|--------|----------|
| Linux (x64) | AppImage | `installer/linux/` |
| Linux (x64) | DEB package | `installer/linux/` |
| Windows | NSIS installer | `installer/windows/` |
| Android | APK | `installer/mobile/` |

### Building the apps

```bash
cd apps
npm install

# Build the React frontend
npm run build

# Build Linux packages (AppImage + DEB)
./node_modules/.bin/electron-builder --linux

# Build Windows installer (from Linux, via wine/cross-compile)
./node_modules/.bin/electron-builder --win

# Build Android APK
npx cap sync android
cd android && ./gradlew assembleDebug
```

### Desktop app features
- Connects to any RichSinkhole server by IP (http or https)
- Minimizes to system tray; **Quit** from tray menu to exit
- No maximize button (fixed window size for consistent layout)

---

## Deploying to a Raspberry Pi

RichSinkhole includes a deploy script that cross-compiles ARM64 images locally and transfers them to the Pi over SSH.

### Prerequisites (one-time)

```bash
# Install QEMU for cross-compilation
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes

# Create a multi-arch buildx builder
docker buildx create --name multiarch --driver docker-container --use
```

### Deploy

```bash
# Deploy all services
./deploy.sh

# Deploy specific services
./deploy.sh sinkhole
./deploy.sh sinkhole nginx
```

The script builds `linux/arm64` images, transfers them via `docker save | gzip | ssh docker load`, and restarts the affected containers on the Pi.

---

## Configuration

### Environment variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_IP` | *(required)* | LAN IP of the host machine |
| `HTTP_PORT` | `80` | Port for nginx |
| `NGINX_CONFIG` | `nginx.conf` | Nginx config file to use |
| `TZ` | `Asia/Manila` | Timezone for logs and scheduler |

### Blocklist sources

RichSinkhole ships with 14 default blocklist feeds defined in `updater/default_sources.py` — these cannot be removed from the dashboard (shown with a `default` badge). They cover ads, trackers, popups, phishing, scam, adult content, and native device trackers for Samsung, Xiaomi, and TikTok.

User-added feeds are stored in `updater/sources.yml` and can be managed from the dashboard:

```yaml
sources:
  - https://example.com/my-custom-blocklist.txt

whitelist:
  - youtube.com
  - www.youtube.com
```

Supported formats: hosts file (`0.0.0.0 domain`), plain domain list (one per line), and AdBlock syntax (`||domain^`).

Sources that fail 3 consecutive fetches or remain unchanged for 90+ days (configurable in Settings) are automatically disabled.

---

## Project Structure

```
richsinkhole/
├── sinkhole/                      # Unified container entrypoint
│   ├── Dockerfile                 # Single image with all Python services
│   └── main.py                    # Orchestrator: starts DNS, dashboard, updater, YT proxy
├── dashboard/                     # FastAPI backend
│   ├── main.py                    # App entry, auth middleware, captive portal
│   ├── auth.py                    # HMAC session tokens, password hashing
│   ├── routers/
│   │   ├── blocklist.py           # Feed subscriptions, custom domains, allowlist
│   │   ├── logs.py                # Query log REST + SSE stream
│   │   ├── stats.py               # Aggregate stats with cache
│   │   ├── devices.py             # Device CRUD, profiles, parental settings
│   │   ├── device_stats.py        # Per-device query stats
│   │   ├── security.py            # Active blocks, security events, unblock
│   │   ├── settings.py            # Config read/write, update schedule, NTP toggle
│   │   ├── services.py            # Service restart controls (Sinkhole, Unbound, Nginx)
│   │   ├── health.py              # Health check endpoint
│   │   ├── heatmap.py             # Query activity heatmap (7x24 grid)
│   │   ├── network_score.py       # Network health score
│   │   ├── privacy_report.py      # Per-device privacy/tracker report
│   │   ├── parental.py            # Parental controls, screen time, circadian profiles
│   │   ├── schedules.py           # Time-based blocking schedules
│   │   ├── proxy_rules.py         # .lan reverse proxy rule management
│   │   ├── dns_records.py         # Custom DNS record management
│   │   ├── doh.py                 # DNS-over-HTTPS endpoint
│   │   ├── ntp.py                 # NTP server toggle
│   │   ├── metrics.py             # Prometheus-style metrics
│   │   ├── qr.py                  # QR code generator
│   │   └── updater.py             # Blocklist updater status
│   └── templates/                 # Jinja2 templates (login, captive portal, block pages)
├── dns/                           # DNS sinkhole server
│   ├── server.py                  # DNS server (dnslib), blocking + security checks
│   └── blocker.py                 # Blocklist lookup engine
├── updater/                       # Scheduled background tasks
│   ├── updater.py                 # Blocklist sync, threat intel, query log prune
│   ├── default_sources.py         # Built-in blocklist feed URLs (cannot be removed from UI)
│   └── sources.yml                # User-added blocklist source URLs and whitelist
├── youtube-proxy/                 # YouTube transparent proxy
│   └── proxy.py                   # Ad-stripping reverse proxy
├── unbound/                       # Recursive DNS resolver
│   └── unbound.conf
├── ntp/                           # NTP time server
│   ├── Dockerfile
│   └── chrony.conf
├── nginx/                         # Reverse proxy
│   ├── nginx.conf                 # Production config (RPi)
│   ├── nginx-standalone.conf      # Dev/standalone config
│   ├── conf.d/                    # Dynamic per-hostname proxy rules
│   └── certs/                     # CA and server TLS certificates
├── apps/                          # Native app (Electron + Android)
│   ├── src/                       # React + TypeScript frontend
│   ├── electron/                  # Electron main process
│   ├── android/                   # Capacitor Android project
│   └── package.json
├── docker-compose.yml
├── .env.example
├── install.sh
├── deploy.sh
├── backup.sh
└── restore.sh
```

---

## Services & Ports

| Container | Port | Description |
|-----------|------|-------------|
| `sinkhole` | `53/udp`, `53/tcp` | DNS sinkhole |
| `sinkhole` | `8080` (internal) | Web UI and REST API |
| `sinkhole` | `8000` (internal) | YouTube ad-stripping proxy |
| `unbound` | internal | Recursive DNS resolver |
| `ntp` | `123/udp` | NTP time server |
| `nginx` | `80`, `443` | Reverse proxy (public) |

---

## Persistent Data

All persistent data lives in `./data/` (bind-mounted into containers):

| Path | Contents |
|------|----------|
| `./data/sinkhole.db` | Query log, devices, parental usage, security events |
| `./data/blocklist.db` | Blocked domains, feeds table, allowlist, NRD domains |
| `./data/updater_status.json` | Last sync time and domain count |
| `./data/updater_progress.json` | Real-time blocklist update progress |
| `./data/config/config.yml` | DNS and feature configuration |

Use `./backup.sh` to snapshot and `./restore.sh` to migrate to a new machine.

---

## Backup & Restore

```bash
# Create backup
./backup.sh
# -> saves to ./backups/richsinkhole-YYYY-MM-DD.tar.gz

# Restore
./restore.sh ./backups/richsinkhole-2026-03-09.tar.gz
```

---

## Security

- No default credentials — password set on first run, stored as PBKDF2-HMAC-SHA256 (200k iterations)
- Session tokens are HMAC-signed; also accepted as `Authorization: Bearer <token>` for native apps
- Login rate limiting — 5 failed attempts per IP in 5-minute window, then locked out (web + API)
- Unbound provides DNSSEC validation and DNS rebinding protection out of the box
- Nginx handles TLS termination; self-signed CA generated on first install
- CA private key excluded from git (`.gitignore`)
- All API inputs validated server-side; internal errors never exposed to clients
- `/health` returns only `{"status":"ok"}` to unauthenticated requests; `/metrics` requires authentication
- Rate limiting, burst detection, NXDOMAIN flood detection with per-device thresholds
- Blocked queries excluded from rate/burst counters (prevents ad SDK bursts from penalizing legitimate traffic)
- 10 active security features: rebinding, DGA, tunneling, typosquat, NRD, ARP correlation, ghost detection, DNS leak, screen time enforcement, redirect chain detection


---

Developed by: [Engr. Richard R. Ayuyang, PhD](https://chadlinuxtech.net)
<br>Professor II, CSU
<br>Copyright 2026 [DownStreamTech](https://downstreamtech.net). All rights reserved.
<br>Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
