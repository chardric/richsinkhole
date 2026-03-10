# RichSinkhole

A self-hosted DNS sinkhole and ad blocker for your home network, built with Python, FastAPI, Unbound, and Docker. Blocks ads, trackers, telemetry, and malicious domains at the DNS level — network-wide, no per-device software needed. Runs on any Linux machine including a Raspberry Pi.

---

## Features

### Blocking
- **DNS-level blocking** — blocks ads, trackers, telemetry, and malware for every device on the network
- **2.2M+ domains blocked** out of the box via curated subscription feeds
- **Subscription feed manager** — add/remove blocklist URLs; feeds auto-sync on a configurable schedule (daily, weekly, or monthly)
- **Custom block list** — manually block individual domains
- **Allowlist** — permanently whitelist domains so they survive feed re-syncs
- **Threat intel feeds** — URLhaus and ThreatFox malware/phishing domains refreshed every 6 hours

### Security
- **DNS rebinding shield** — blocks public domains resolving to private IPs
- **DGA detection** — composite entropy + bigram + consonant scoring flags suspected beaconing
- **DNS tunneling detection** — entropy + length + TXT record flood detection
- **Typosquat shield** — Levenshtein + homoglyph normalization protects against brand impersonation
- **NRD blocking** — daily newly-registered domain feed (HaGeZi NRD); Off/Warn/Block mode
- **ARP correlation** — enriches devices with MAC/vendor info; ghost detection for ARP-only devices
- **DNS leak detection** — probes upstream latency and DNSSEC health; flags devices bypassing the sinkhole
- **Protected brands** — configurable brand list for typosquat protection
- **Query burst auto-blocking** — rate limiting with per-device IoT thresholds and 60s startup grace period
- **NXDOMAIN flood detection** — auto-blocks clients generating excessive NXDOMAIN responses

### Parental Controls
- **Per-device parental controls** — block social media and gaming domains per device
- **Screen time budgets** — daily query limits per category (social/gaming); snooze button on warning page
- **Circadian / bedtime profiles** — schedule-based blocking (Block All / Bedtime / Strict modes)
- **Block page** — smart per-device block page showing remaining budget and snooze option

### YouTube
- **YouTube ad blocking** — transparent HTTPS proxy strips pre/post-roll ads
- **SNI-based routing** — nginx routes `youtube.com` to the local proxy; other domains go to dashboard
- **CA certificate** — downloadable at `/ca.crt` and `/ca.mobileconfig` (Apple); one-time install per device
- **Devices without cert** — get real YouTube IPs; no breakage

### Network
- **Captive portal** — soft portal that auto-whitelists devices on page visit
- **Reverse proxy manager** — map `.lan` hostnames to LAN services (e.g. `nas.lan → 192.168.1.50:5000`)
- **DNS-over-HTTPS** — built-in DoH endpoint (`/dns-query`) compatible with all major browsers
- **NTP server** — built-in chrony NTP server (port 123/UDP); toggle from Settings
- **HTTPS dashboard** — nginx serves dashboard on port 443 with self-signed cert

### Devices
- **Device fingerprinting** — auto-identifies device type by DNS patterns (Apple, Android, Windows, Samsung TV, Xbox, MikroTik, Xiaomi, Router, and more)
- **Per-device blocking profiles** — Normal, Strict, or Passthrough
- **MAC/vendor info** — ARP-correlated vendor names shown per device
- **Ghost detection** — devices with ARP entries but no DNS queries in 24h marked with 👻
- **Schedule rules** — time-based blocking per device or network-wide

### Dashboard & Apps
- **React web dashboard** — dark theme, real-time query log, stat cards, query activity heatmap, network health score, SSE activity stream
- **Privacy report** — per-device domain breakdown with 24h/7d time range filter
- **Service controls** — restart DNS, Unbound, and Nginx containers from the Settings tab
- **Configurable update schedule** — set blocklist sync frequency (daily/weekly/monthly), day, and time from Settings
- **Native desktop app** — Electron wrapper for Linux (AppImage + DEB) and Windows (NSIS installer); system tray with minimize-to-tray
- **Android app** — Capacitor-based APK
- **Webhook notifications** — alerts for blocklist updates, new devices, and daily summaries

---

## Tech Stack

| Service | Technology | Purpose |
|---------|------------|---------|
| DNS Sinkhole | Python, dnslib | DNS blocking, device fingerprinting, query logging |
| Dashboard | Python, FastAPI, Jinja2 | Web UI, REST API, SSE live log |
| Recursive Resolver | Unbound | DNSSEC validation, DNS rebinding protection |
| Blocklist Updater | Python | Scheduled fetch, dedup, SQLite writer |
| YouTube Proxy | Python, httpx | Ad-stripping reverse proxy |
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
  ┌─────────────┐
  │  DNS Server │  (Python / dnslib)
  │  server.py  │──► blocked → NXDOMAIN / sinkhole IP
  └──────┬──────┘
         │ allowed queries
         v
  ┌─────────────┐
  │   Unbound   │  recursive resolver w/ DNSSEC
  └──────┬──────┘
         │
         v
   Root DNS servers (no third-party DNS)

  ┌──────────────────┐
  │  Dashboard       │  FastAPI + React (port 8080 internal)
  └──────────────────┘

  ┌──────────────────┐
  │  YouTube Proxy   │  httpx transparent proxy (port 8000)
  └──────────────────┘

  ┌──────────────────┐
  │  NTP Server      │  chrony (port 123/UDP)
  └──────────────────┘

  ┌──────────────────┐
  │  Updater         │  blocklist sync + ARP scan + threat intel
  └──────────────────┘

  ┌──────────────────┐
  │  Nginx           │  reverse proxy (ports 80/443), SNI routing
  └──────────────────┘
```

All services run in Docker containers orchestrated by Docker Compose.

---

## Requirements

- Linux machine (x86_64 or ARM64 / Raspberry Pi 4+)
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

The **Blocklist → Subscriptions** tab shows all feed sources. Built-in feeds (defined in `updater/sources.yml`) are labeled **built-in** and auto-sync on the configured schedule (daily by default at 3:00 AM). The update schedule — frequency (daily/weekly/monthly), day, and time — is configurable from **Settings → Blocklist Update Schedule**.

To add a custom feed:
1. Go to **Blocklist → Subscriptions**
2. Click **Add Feed**
3. Paste a URL — supports hosts file format (`0.0.0.0 domain.com`) or plain domain lists (one per line)

To remove a custom feed, click the delete button on the feed card. All domains from that feed are removed immediately.

### Unblocking a domain from a feed

Individual domains from subscription feeds cannot be deleted (they return on the next sync). Instead, add the domain to the **Allowlist** tab — it will be permanently whitelisted even after re-sync.

### Custom blocked domains

Go to **Blocklist → Custom** to manually block specific domains. These are independent of subscription feeds and can be deleted individually.

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
./deploy.sh dashboard
./deploy.sh dashboard dns updater
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

### Blocklist sources (`updater/sources.yml`)

```yaml
sources:
  - https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts
  - https://adaway.org/hosts.txt
  # add more URLs here

update_interval_hours: 24

whitelist:
  - youtube.com
  - www.youtube.com
```

Additional feeds can also be added from the dashboard without editing this file.

---

## Project Structure

```
richsinkhole/
├── apps/                       # Native app (Electron + Android)
│   ├── src/                    # React + TypeScript frontend
│   │   ├── screens/            # Dashboard, Logs, Blocklist, Devices, Security, Settings
│   │   ├── components/         # Shared UI components
│   │   ├── api/                # API client and type definitions
│   │   └── context/            # Auth and Toast providers
│   ├── electron/               # Electron main process
│   ├── android/                # Capacitor Android project
│   ├── electron-builder.yml    # Desktop build config
│   └── package.json
├── dashboard/                  # FastAPI backend
│   ├── main.py                 # App entry, auth middleware, captive portal
│   ├── auth.py                 # HMAC session tokens, password hashing
│   ├── routers/
│   │   ├── blocklist.py        # Feed subscriptions, custom domains, allowlist
│   │   ├── logs.py             # Query log REST + SSE stream
│   │   ├── stats.py            # Aggregate stats with cache
│   │   ├── devices.py          # Device CRUD, profiles, parental settings
│   │   ├── device_stats.py     # Per-device query stats
│   │   ├── security.py         # Active blocks, security events, unblock
│   │   ├── settings.py         # Config read/write, update schedule, NTP toggle
│   │   ├── services.py         # Service restart controls (DNS, Unbound, Nginx)
│   │   ├── health.py           # Health check endpoint
│   │   ├── heatmap.py          # Query activity heatmap (7×24 grid)
│   │   ├── network_score.py    # Network health score
│   │   ├── privacy_report.py   # Per-device privacy/tracker report
│   │   ├── parental.py         # Parental controls, screen time, circadian profiles
│   │   ├── schedules.py        # Time-based blocking schedules
│   │   ├── proxy_rules.py      # .lan reverse proxy rule management
│   │   ├── dns_records.py      # Custom DNS record management
│   │   ├── doh.py              # DNS-over-HTTPS endpoint
│   │   ├── ntp.py              # NTP server toggle
│   │   ├── nrd.py              # NRD feed status and mode
│   │   ├── dns_leak.py         # DNS leak detection results
│   │   ├── metrics.py          # Prometheus-style metrics
│   │   ├── qr.py               # QR code generator
│   │   └── updater.py          # Blocklist updater status
│   └── templates/              # Jinja2 templates (login, captive portal, block pages)
├── dns/                        # DNS sinkhole server
│   ├── server.py               # DNS server (dnslib), blocking + security checks
│   ├── dga.py                  # DGA domain scoring
│   ├── tunnel_detect.py        # DNS tunneling detection
│   └── typosquat.py            # Typosquat / homoglyph detection
├── updater/                    # Scheduled background tasks
│   ├── updater.py              # Blocklist sync, ARP scan, threat intel, DNS leak probe
│   ├── arp_scan.py             # ARP table correlation for device enrichment
│   ├── oui.txt                 # IEEE OUI vendor database
│   └── sources.yml             # Blocklist source URLs and whitelist
├── unbound/                    # Recursive DNS resolver
│   └── unbound.conf
├── youtube-proxy/              # YouTube transparent proxy
│   └── proxy.py
├── ntp/                        # NTP time server
│   ├── Dockerfile
│   └── chrony.conf
├── nginx/                      # Reverse proxy
│   ├── nginx.conf              # Main config (router-level DNS setup)
│   ├── conf.d/                 # Dynamic per-hostname proxy rules
│   ├── 50x.html                # Custom error page
│   └── certs/                  # CA and server TLS certificates
├── installer/
│   ├── linux/                  # AppImage + DEB
│   ├── windows/                # NSIS installer
│   └── mobile/                 # Android APK
├── docker-compose.yml
├── .env.example
├── install.sh
├── deploy.sh
├── backup.sh
└── restore.sh
```

---

## Services & Ports

| Service | Port | Description |
|---------|------|-------------|
| `dns` | `53/udp`, `53/tcp` | DNS sinkhole |
| `unbound` | internal | Recursive DNS resolver |
| `ntp` | `123/udp` | NTP time server |
| `dashboard` | `8080` (internal) | Web UI and REST API |
| `youtube-proxy` | `8000` (internal) | YouTube ad-stripping proxy |
| `nginx` | `80`, `443` | Reverse proxy (public) |
| `updater` | — | Background scheduler |

---

## Persistent Data

All persistent data lives in `./data/` (bind-mounted into containers):

| Path | Contents |
|------|----------|
| `./data/sinkhole.db` | Query log, devices, parental usage, security events |
| `./data/blocklist.db` | Blocked domains, feeds table, allowlist, NRD domains |
| `./data/updater_status.json` | Last sync time and domain count |
| `./data/config/config.yml` | DNS and feature configuration |

Use `./backup.sh` to snapshot and `./restore.sh` to migrate to a new machine.

---

## Backup & Restore

```bash
# Create backup
./backup.sh
# → saves to ./backups/richsinkhole-YYYY-MM-DD.tar.gz

# Restore
./restore.sh ./backups/richsinkhole-2026-03-09.tar.gz
```

---

## Security

- No default credentials — password set on first run, stored as PBKDF2 hash
- Session tokens are HMAC-signed; also accepted as `Authorization: Bearer <token>` for native apps
- Unbound provides DNSSEC validation and DNS rebinding protection out of the box
- Nginx handles TLS termination; self-signed CA generated on first install
- CA private key excluded from git (`.gitignore`)
- All API inputs validated server-side; internal errors never exposed to clients
- Rate limiting, burst detection, NXDOMAIN flood detection with per-device thresholds
- 9 active security features: rebinding, DGA, tunneling, typosquat, NRD, ARP correlation, ghost detection, DNS leak, screen time enforcement

---

## License

MIT — © 2026 [DownStreamTech](https://downstreamtech.net). All rights reserved.
Developed by Richard R. Ayuyang, PhD
