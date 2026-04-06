# RichSinkhole

A self-hosted DNS sinkhole and ad blocker for your home network. Blocks ads, trackers, malware, phishing, spyware, and Chinese telemetry at the DNS level — network-wide, no per-device software needed. Runs on any Linux machine including a Raspberry Pi 3B.

## Features

- **DNS blocking** — 1M+ domains blocked from 9 curated feeds; custom blocklist, allowlist, and service toggles (Social Media, Streaming, Gaming, etc.)
- **Security** — DNS rebinding shield, DGA detection, tunneling detection, typosquat protection, DoH bypass detection, GeoIP country blocking, spyware detection, CSP nonces, container hardening (read-only rootfs, non-root, cap_drop ALL)
- **Auth** — PBKDF2 password hashing, TOTP 2FA, DB-backed sessions with rotation + revocation, 15-min lockout, Secure cookies
- **Audit** — append-only activity logs, error logs, email logs with admin UI, structured JSON logging with request-ID correlation
- **Parental controls** — per-device profiles (Normal, Strict, Guest, Quarantine, Passthrough); screen time budgets, bedtime schedules, app usage tracking, family activity digest emails
- **YouTube ad blocking** — transparent HTTPS proxy strips pre/post-roll ads via SNI routing
- **Privacy** — per-device privacy report with 130+ company mappings; GeoIP blocks Chinese telemetry from IoT devices
- **Network** — captive portal, reverse proxy manager (`.lan` hostnames), DNS-over-HTTPS endpoint, NTP server
- **Dashboard** — dark-themed PWA with real-time query log, stats, heatmap, network score, and device fingerprinting
- **CI** — GitHub Actions: pip-audit, Trivy image scan, Python lint
- **Native apps** — Linux (AppImage/DEB), Windows (NSIS), Android (APK)

## Prerequisites

- Linux (x86_64 or ARM64 / Raspberry Pi 3B+)
- Docker Engine 24+ and Docker Compose v2+
- A static LAN IP address

## Installation

```bash
git clone https://github.com/chardric/richsinkhole.git
cd richsinkhole
cp .env.example .env
# Edit .env — set HOST_IP to your machine's LAN IP
./install.sh
```

Point your router's primary DNS to the `HOST_IP`. Open the dashboard at `http://<HOST_IP>/richsinkhole/`.

## Usage

1. **Dashboard** — view real-time DNS queries, blocked domains, and network statistics
2. **Settings** — configure blocklists, allowlists, service toggles, and sync schedule
3. **Parental Controls** — create per-device profiles with screen time and bedtime rules
4. **Native Apps** — build from `apps/` directory: `npm install && npm run build`

### Backup & Restore

```bash
./backup.sh              # saves to ./backups/
./restore.sh ./backups/richsinkhole-2026-03-09.tar.gz
```

## License

Licensed under the [Apache License 2.0](LICENSE).

---

Developed by:
<br>
Richard R. Ayuyang, PhD [https://chadlinuxtech.net]
<br>
Professor II, CSU
<br>
Copyright (c) 2026 DownStreamTech [https://downstreamtech.net]. All rights reserved.
