# RichSinkhole

A self-hosted DNS sinkhole and ad blocker for your home network. Blocks ads, trackers, malware, phishing, spyware, and Chinese telemetry at the DNS level — network-wide, no per-device software needed. Runs on any Linux machine including a Raspberry Pi 3B.

## Features

**DNS Blocking** — 1M+ domains blocked out of the box from 9 curated feeds. Custom blocklist, allowlist, and service toggles (Social Media, Streaming, Gaming, etc.). Auto-syncing on a configurable schedule with real-time progress.

**Security** — DNS rebinding shield, DGA detection, tunneling detection, typosquat protection, rate limiting, redirect chain detection, DoH bypass detection, GeoIP country blocking (default: China), spyware/surveillance detection, and dark web monitoring.

**Parental Controls** — Per-device blocking profiles (Normal, Strict, Guest, Quarantine, Passthrough). Screen time budgets, bedtime schedules with grace periods, app usage tracking for 18 apps, and family activity digest emails.

**YouTube Ad Blocking** — Transparent HTTPS proxy strips pre/post-roll ads via SNI routing. One-time CA cert install per device; devices without the cert are unaffected.

**Privacy** — Per-device privacy report with 130+ company mappings. GeoIP blocks Chinese telemetry from IoT devices. Spyware domains blocked unconditionally for all devices.

**Network** — Captive portal, reverse proxy manager (`.lan` hostnames), DNS-over-HTTPS endpoint, NTP server, and HTTPS dashboard.

**Dashboard & Apps** — Dark-themed web dashboard with real-time query log, stats, heatmap, network score, and device fingerprinting. Native apps for Linux (AppImage/DEB), Windows (NSIS), and Android (APK).

## Prerequisites

- Linux (x86_64 or ARM64 / Raspberry Pi 3B+)
- Docker Engine 24+ and Docker Compose v2+
- A static LAN IP address

## Quick Start

```bash
git clone https://github.com/chardric/richsinkhole.git
cd richsinkhole
cp .env.example .env
# Edit .env — set HOST_IP to your machine's LAN IP
./install.sh
```

Point your router's primary DNS to the `HOST_IP`. Open the dashboard at `http://<HOST_IP>/richsinkhole/`.

## Configuration

Edit `.env` for basic settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_IP` | *(required)* | LAN IP of the host machine |
| `HTTP_PORT` | `80` | Port for nginx |
| `TZ` | `Asia/Manila` | Timezone |

Everything else is configurable from the dashboard (Settings tab).

## Native Apps

Build from the `apps/` directory:

```bash
cd apps && npm install && npm run build
./build-linux.sh     # AppImage + DEB
./build-windows.sh   # NSIS installer
./build-android.sh   # APK
```

Installers are output to `installer/linux/`, `installer/windows/`, and `installer/mobile/`.

## Deploying to Raspberry Pi

```bash
# One-time setup for cross-compilation
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
docker buildx create --name multiarch --driver docker-container --use

# Deploy
./deploy.sh              # all services
./deploy.sh sinkhole     # single service
```

## Backup & Restore

```bash
./backup.sh              # saves to ./backups/
./restore.sh ./backups/richsinkhole-2026-03-09.tar.gz
```

## Tech Stack

Python, FastAPI, dnslib, Unbound, chrony, nginx, Docker Compose, SQLite, React + TypeScript (native apps), Electron, Capacitor.

---

Developed by:
<br>
Richard R. Ayuyang, PhD [https://chadlinuxtech.net]
<br>
Professor II, CSU
<br>
Copyright (c) 2026 DownStreamTech [https://downstreamtech.net]. All rights reserved.
