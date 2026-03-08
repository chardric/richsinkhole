# RichSinkhole

A self-hosted DNS sinkhole and ad blocker for your home network, built with Python, FastAPI, Unbound, and Docker. Blocks ads, trackers, telemetry, and malicious domains at the DNS level — network-wide, no per-device software needed. Runs on any Linux machine including a Raspberry Pi.

---

## Features

- **DNS-level blocking** — blocks ads, trackers, telemetry, and malware domains for every device on your network
- **841,000+ domains blocked** out of the box via curated blocklist sources
- **Live query log** — real-time DNS activity stream with SSE
- **Dashboard** — stats, top blocked domains, top clients, live query log with animated activity bar
- **YouTube ad redirect** — intercepts YouTube DNS and proxies requests through a local server that strips pre/post-roll ads (per-device via captive portal)
- **Captive portal** — soft portal that auto-whitelists devices on page visit; no forced blocking
- **Unbound upstream** — recursive DNS with DNSSEC validation, DNS rebinding protection, and rate limiting (no third-party DNS required)
- **NTP server** — built-in chrony NTP server (port 123/UDP); serve accurate time to all LAN devices; enable/disable from dashboard
- **Blocklist auto-updater** — pulls from configurable source URLs, deduplicates, and rebuilds the blocklist daily at 3 AM
- **Threat intel feeds** — automatic integration of URLhaus and ThreatFox malware/phishing domains (refreshed every 6 hours)
- **Quick Block presets** — one-click toggle for domains across Ads, Tracking, Telemetry, Social Trackers, Malware & Phishing, and Gambling categories
- **Reverse proxy manager** — define `.lan` hostnames that route to any LAN service (e.g. `nas.lan` → `192.168.1.50:5000`)
- **Device fingerprinting** — auto-identifies devices by DNS query patterns (Apple, Android, Windows, Samsung TV, Xbox, MikroTik, Xiaomi, and more)
- **Per-device blocking profiles** — Normal, Strict (extra keyword blocking), or Passthrough (no blocking) per device
- **Per-device stats** — click any device to see top blocked/forwarded domains and recent queries
- **Privacy report** — per-device breakdown of forwarded domains grouped by tracker category
- **Security monitoring** — DNS rebinding detection, DGA suspect flagging, query burst auto-blocking, NXDOMAIN flood detection
- **Canary tokens** — configure DNS tripwire domains; get notified if any device queries them
- **Schedule rules** — time-based blocking per device or network-wide (e.g. block social media after midnight)
- **Webhook notifications** — alerts for blocklist updates, new devices, and daily summaries
- **DNS-over-HTTPS (DoH)** — built-in DoH endpoint (`/dns-query`) compatible with all major browsers
- **Backup & restore** — single-command archive of all persistent data
- **ARM64 / Raspberry Pi ready** — includes a cross-compilation deploy script

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
  │  blocker.py │──► blocked → NXDOMAIN / 0.0.0.0
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
  │  Dashboard       │  FastAPI + Jinja2 (port 8080)
  │  (stats, logs,   │
  │   settings, UI)  │
  └──────────────────┘

  ┌──────────────────┐
  │  YouTube Proxy   │  httpx reverse proxy (port 8000)
  │  (ad stripping)  │
  └──────────────────┘

  ┌──────────────────┐
  │  NTP Server      │  chrony (port 123/UDP)
  └──────────────────┘

  ┌──────────────────┐
  │  Updater         │  scheduled blocklist puller
  └──────────────────┘

  ┌──────────────────┐
  │  Nginx           │  reverse proxy (ports 80/443)
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

---

## Dashboard

| Tab | Description |
|-----|-------------|
| **Dashboard** | Query stats, top blocked domains, top clients, live query log with animated activity bar |
| **Blocklist** | Auto-update status, blocklist sources, Quick Block presets, YouTube CDN nodes, threat intel status |
| **Devices** | Fingerprinted devices, per-device blocking profile (Normal/Strict/Passthrough), per-device stats |
| **Security** | Active blocks, recent security events (rebinding, DGA, query bursts), canary tokens |
| **Privacy** | Per-device forwarded domain breakdown grouped by tracker category |
| **Proxy** | Reverse proxy rules — map `.lan` hostnames to LAN services |
| **Schedules** | Time-based DNS blocking rules per device or network-wide |
| **Settings** | Service toggles (YouTube redirect, captive portal, NTP server), email/webhook notifications, server info |

---

## YouTube Ad Blocking

RichSinkhole can redirect YouTube DNS queries to a local proxy that strips ads.

**How it works:**
1. Device visits `http://<HOST_IP>/richsinkhole/` (captive portal)
2. Device is auto-whitelisted
3. Install the CA certificate on the device (one-time, see Setup Guide in the dashboard)
4. DNS for `youtube.com`, `www.youtube.com`, `youtu.be`, etc. is redirected to the local YouTube proxy
5. The proxy forwards requests to YouTube over HTTPS using Google's DNS (bypasses the sinkhole loop)

Devices **without** the cert installed get real YouTube IPs — no breakage.

---

## Blocklist Management

### Automatic updates

The blocklist updater runs daily at **3:00 AM** and fetches all configured source URLs.

Sources support:
- Hosts file format (`0.0.0.0 domain.com`)
- Plain domain lists (one domain per line)

### Adding sources

In the **Blocklist** tab → **Scheduled Sources** → paste a URL and click **Add**.

Sources are validated before saving:
- URL scheme and hostname check
- HTTP reachability check
- Content-type must be `text/*`
- File size: 50 B – 50 MB
- Minimum 10 valid domains

### Quick Block presets

Curated domains organized into 6 categories, toggled with a switch:

| Category | Examples |
|----------|---------|
| **Ads & Ad Networks** | doubleclick.net, googlesyndication.com, taboola.com, criteo.com |
| **Tracking & Analytics** | google-analytics.com, hotjar.com, clarity.ms, mixpanel.com |
| **Telemetry** | telemetry.mozilla.org, telemetry.microsoft.com, vortex.data.microsoft.com |
| **Social Trackers** | connect.facebook.net, ads.twitter.com, ads.tiktok.com |
| **Malware & Phishing** | malware-domain-list.com entries, known phishing domains |
| **Gambling** | bet365.com, pokerstars.com, draftkings.com and similar |

---

## Backup & Restore

### Backup

```bash
./backup.sh
# saves to ./backups/richsinkhole-YYYY-MM-DD.tar.gz
```

Backs up:
- `./data/` — query logs, blocklist DB, captive whitelist, updater status
- `./data/config/` — `config.yml`
- `updater/sources.yml` — blocklist source URLs
- `nginx/certs/` — CA certificate and private key

### Restore

```bash
./restore.sh ./backups/richsinkhole-2026-03-05.tar.gz
```

Stops containers, restores data, restarts services.

---

## Deploying to a Raspberry Pi

RichSinkhole includes a deploy script that cross-compiles ARM64 images locally and transfers them to the Pi over SSH — no source code is copied to the Pi.

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

# Deploy a single service
./deploy.sh dashboard

# Deploy multiple services
./deploy.sh dashboard dns
```

The script builds `linux/arm64` images, transfers them via `docker save | gzip | ssh docker load`, and restarts the affected containers on the Pi.

---

## Configuration

### Environment variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_IP` | *(required)* | LAN IP of the host machine |
| `HTTP_PORT` | `80` | Port for the nginx reverse proxy |
| `NGINX_CONFIG` | `nginx.conf` | Nginx config file to use |
| `TZ` | `Asia/Manila` | Timezone for logs and scheduler |

### DNS settings (`data/config/config.yml`)

| Key | Description |
|-----|-------------|
| `upstream_dns` | Upstream resolver (`unbound`, `1.1.1.1`, `8.8.8.8`, `9.9.9.9`) |
| `youtube_redirect_enabled` | Enable per-device YouTube DNS redirect |
| `youtube_redirect_ip` | IP to redirect YouTube domains to (auto-set from `HOST_IP`) |
| `captive_portal_enabled` | Enable the soft captive portal |
| `captive_portal_ip` | IP for the captive portal (auto-set from `HOST_IP`) |

---

## Project Structure

```
richsinkhole/
├── dashboard/              # FastAPI web dashboard
│   ├── main.py             # App entry point, captive portal routes
│   ├── routers/
│   │   ├── blocklist.py    # Blocklist CRUD + batch check + import
│   │   ├── logs.py         # Query log REST + SSE stream
│   │   ├── stats.py        # Aggregate stats
│   │   ├── settings.py     # Config read/write
│   │   ├── updater.py      # Updater status, sources, validation, trigger
│   │   ├── health.py       # Health check endpoint
│   │   ├── qr.py           # QR code generation
│   │   └── doh.py          # DNS-over-HTTPS endpoint
│   ├── static/app.js       # Frontend JavaScript
│   └── templates/
│       ├── index.html      # Main dashboard UI
│       ├── setup.html      # Setup guide / captive portal landing
│       └── captive.html    # Captive portal redirect page
├── dns/                    # DNS sinkhole server
│   ├── server.py           # DNS server (dnslib), blocking + redirect logic
│   ├── blocker.py          # Blocklist loader with SQLite
│   └── blocklists/
│       └── default.txt     # Built-in minimal blocklist
├── unbound/                # Recursive DNS resolver
│   └── unbound.conf        # DNSSEC, rebinding protection, rate limiting
├── updater/                # Blocklist updater service
│   ├── updater.py          # Scheduler, fetcher, parser, DB writer
│   └── sources.yml         # Blocklist source URLs and whitelist
├── youtube-proxy/          # YouTube reverse proxy
│   └── proxy.py            # httpx async proxy with connection pooling
├── ntp/                    # NTP time server
│   ├── Dockerfile          # Alpine + chrony
│   └── chrony.conf         # NTP server config (pool.ntp.org, Cloudflare, Google)
├── nginx/                  # Reverse proxy
│   ├── nginx.conf          # Config for router-level DNS setup
│   ├── nginx-standalone.conf  # Config for standalone (no router DNS)
│   ├── conf.d/             # Dynamic per-hostname proxy rule configs
│   └── certs/              # CA and server TLS certificates
├── docker-compose.yml
├── .env.example
├── install.sh              # First-run installer
├── deploy.sh               # Cross-compile and deploy to RPi
├── backup.sh               # Backup persistent data
└── restore.sh              # Restore from backup
```

---

## Services & Ports

| Service | Port | Description |
|---------|------|-------------|
| `dns` | `53/udp`, `53/tcp` | DNS sinkhole server |
| `unbound` | internal | Recursive DNS resolver |
| `ntp` | `123/udp` | NTP time server (chrony) |
| `dashboard` | `8080` (internal) | Web UI and API |
| `youtube-proxy` | `8000` (internal) | YouTube reverse proxy |
| `nginx` | `80`, `443` | Reverse proxy (public) |
| `updater` | — | Background blocklist updater |

---

## Persistent Data

All persistent data lives in `./data/` (bind-mounted):

| Path | Contents |
|------|----------|
| `./data/sinkhole.db` | Query log (SQLite) |
| `./data/blocklist.db` | Blocked domains (SQLite) |
| `./data/captive_whitelist` | Whitelisted client IPs |
| `./data/updater_status.json` | Last update time and stats |
| `./data/config/config.yml` | DNS and feature config |

Use `./backup.sh` to snapshot all of this, and `./restore.sh` to migrate to a new machine.

---

## Security

- No default credentials — password set on first run, stored as PBKDF2 hash
- Session secret auto-generated on first run; stored in `config.yml`
- Unbound provides DNSSEC validation and DNS rebinding protection
- Nginx handles TLS termination
- CA private key is excluded from git (`.gitignore`)
- All API inputs are validated server-side; internal errors are not exposed to clients
- Auto-blocking: rate limiting, NXDOMAIN flood detection, query burst detection with per-device IoT thresholds
- DGA detection: high-entropy DNS labels are flagged as potential beaconing

---

© [DownStreamTech](https://downstreamtech.net) — Licensed under the [MIT License](LICENSE)
