# RichSinkhole — Lite

A stripped-down native build of [RichSinkhole](../README.md) for the
**Raspberry Pi Zero v1.3** (ARMv6, 1 GHz single core, 512 MB RAM, USB
networking). The full Docker stack does not fit; this variant trades features
for footprint.

> Same project identity, same `sources.yml` format, same admin look-and-feel.
> Different goal: keep a tiny edge box honest about ads, trackers, malware
> and phishing without breaking the LAN.

## What you get

- DNS sinkhole on `:53` via **dnsmasq** (cache 4096 entries, forwards to
  1.1.1.1 / 9.9.9.9, `addn-hosts` blocklist).
- Daily blocklist refresh from `sources.yml` (defaults: StevenBlack, AdAway,
  anudeepND, Hagezi *fake* + *popupads*, curbengh phishing-filter — Hagezi TIF
  is intentionally excluded to keep memory low).
- Service-bundle blocking (Facebook, Instagram, TikTok, Snapchat, Reddit, …)
  toggled from the dashboard.
- A small Flask dashboard on `:8080` with Status, Blocklist, Allowlist,
  Services, Logs and Settings pages.
- Single super_admin password (bcrypt, set on first run), HttpOnly + SameSite
  cookies, CSP headers.
- `log2ram` for SD-wear protection (when available), WAL + `synchronous=NORMAL`
  on SQLite, atomic-rename writes for the generated hosts file.

## What you do **not** get (vs the full project)

These are deliberately out of scope on a Pi Zero — the full repo is the place
for them:

- mitmproxy, YouTube ad proxy, captive portal, DoH endpoint
- Threat-scoring DNS server (entropy / consonants / DGA / tunnel detection)
- Parental controls, schedules, canary tokens, device fingerprinting
- GeoIP country blocking
- Activity / audit / email / error log dashboards
- PWA, full WCAG/Core-Web-Vitals tuning, i18n
- HTTPS / reverse proxy (LAN-only by design — see *Hardening* below)
- Built-in backup (see *Backup* below — host-side rsync recommended)

## Quickstart

On the Pi (DietPi / Raspberry Pi OS Lite):

```bash
# from your workstation:
scp -r lite/  pi@<pi-ip>:/tmp/rs-lite-src/
ssh pi@<pi-ip>
cd /tmp/rs-lite-src
sudo bash install-lite.sh
```

When it finishes, browse to `http://<pi-ip>:8080`, set the admin password,
and point your router's primary DNS at the Pi.

To remove:
```bash
sudo bash /tmp/rs-lite-src/uninstall-lite.sh           # keeps state
sudo bash /tmp/rs-lite-src/uninstall-lite.sh --purge   # nukes state too
```

## Layout

```
lite/
├── install-lite.sh / uninstall-lite.sh   # native installer/uninstaller
├── requirements.txt                       # Flask, gunicorn, PyYAML, requests, bcrypt
├── etc/                                   # dropped onto / by the installer
│   ├── dnsmasq.d/rs-lite.conf
│   ├── systemd/rs-lite-dashboard.service
│   ├── systemd/rs-lite-updater.{service,timer}
│   ├── logrotate.d/rs-lite
│   └── polkit-1/rules.d/50-rs-lite-dnsmasq.rules
└── rs_lite/                               # the Python app
    ├── dashboard.py / config.py / db.py / auth.py
    ├── updater.py                         # one-shot blocklist refresh
    ├── querylog.py                        # bounded tail of dnsmasq.log
    ├── services_data.py                   # vendored from dashboard/services_data.py
    ├── blueprints/{auth,status,blocklist,allowlist,services,logs,settings}.py
    ├── templates/*.html
    └── static/{css/style.css, js/app.js}
```

Filesystem layout after install:

| Path                        | What lives there                              |
|-----------------------------|-----------------------------------------------|
| `/opt/rs-lite/`             | Source + Python venv                          |
| `/var/lib/rs-lite/state.db` | settings, allowlist, services_blocked         |
| `/var/lib/rs-lite/blocked.hosts` | dnsmasq `0.0.0.0` hosts file (atomic write) |
| `/var/log/rs-lite/dnsmasq.log` | dnsmasq query log (rotated daily, 7 d)     |
| `/etc/rs-lite/sources.yml`  | Optional extra sources / whitelist            |
| `/etc/dnsmasq.d/rs-lite.conf` | dnsmasq drop-in (`addn-hosts`, log-queries) |

## Memory budget

Sized for the Pi Zero's 512 MB (≈ 427 MB usable):

| Component                 |    RAM |
|---------------------------|-------:|
| dnsmasq                   |  ~5 MB |
| gunicorn (1 sync worker)  | ~35 MB |
| Updater (peak, refresh only) | ~50 MB |
| Kernel + DietPi base      | ~120 MB |
| **Total target**          | **~210 / 427 MB** |

Verify with `free -m` while the device is idle and again during a refresh.

## Hardening

The dashboard runs **plain HTTP on the LAN**. Global rule
([`security.md`](../../.claude/rules/security.md)) calls for a reverse proxy in
production. For a single-admin LAN box this is acceptable, but if you expose
the device beyond your home network you must put HTTPS in front of it. One-line
add: install Caddy and point a `:443` site at `127.0.0.1:8080` — Caddy will
auto-issue a cert via DNS-01 if you set that up. We do not bundle Caddy here
to keep the runtime predictable.

Other notes:
- `dnsmasq` listens on `eth0`. Bind to a single interface or add a UFW rule if
  you have multiple NICs.
- `state.db` and `blocked.hosts` are owned `rs-lite:rs-lite` mode `0750`.
- The systemd unit drops privileges (`User=rs-lite`), reads only what it needs,
  and is capped to 128 MB.

## Backup (out of scope, but read this)

Global rule mandates automated backup. We do **not** ship one in Lite. The
device is small enough that the recommended pattern is to back it up *from
elsewhere* — your main RPi or NAS:

```bash
# on the host that already has rs-backup configured:
rsync -aP --delete pi@<pi-ip>:/var/lib/rs-lite/ /backups/rs-lite/
```

Daily cron + your existing 7d/4w/12m retention will cover the device.

## Verification (post-install sanity check)

After running `install-lite.sh`:

1. `dig @<pi-ip> +short example.com` — returns a real IP.
2. `dig @<pi-ip> +short doubleclick.net` — returns `0.0.0.0`.
3. Browser → `http://<pi-ip>:8080`, set password, Status page shows non-zero
   query count.
4. Add `example.com` to the Allowlist, click *Refresh now* on Blocklist, then
   `dig @<pi-ip> example.com` — still resolves normally.
5. `free -m` during a refresh — peak ≤ 250 MB used.
6. `sudo reboot`; both `rs-lite-dashboard.service` and `dnsmasq.service` come
   back healthy without manual intervention.

## License & attribution

Apache License 2.0 — see [`../LICENSE`](../LICENSE).

Developed by:
<br>
Richard R. Ayuyang, PhD [https://chadlinuxtech.net]
<br>
Professor II, CSU
<br>
Copyright (c) 2026 DownStreamTech [https://downstreamtech.net]. All rights reserved.
