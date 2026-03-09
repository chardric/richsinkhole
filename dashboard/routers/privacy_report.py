# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
IoT Privacy Leak Report — maps DNS queries per device to their parent company.
"""
import ipaddress
import time
import aiosqlite
from fastapi import APIRouter

SINKHOLE_DB = "/data/sinkhole.db"

router = APIRouter()

_privacy_cache: list | None = None
_privacy_cache_ts: float = 0.0
_PRIVACY_TTL = 60.0  # heavier query — cache for 1 minute

# Domain suffix → parent company
# Ordered longest-first so more specific rules match first
_COMPANY_MAP: list[tuple[str, str]] = [
    # Google / Alphabet
    ("doubleclick.net",         "Google"),
    ("googlesyndication.com",   "Google"),
    ("googletagmanager.com",    "Google"),
    ("google-analytics.com",    "Google"),
    ("googleadservices.com",    "Google"),
    ("googlevideo.com",         "Google"),
    ("gstatic.com",             "Google"),
    ("googleapis.com",          "Google"),
    ("google.com",              "Google"),
    ("gmail.com",               "Google"),
    ("youtube.com",             "Google"),
    ("ytimg.com",               "Google"),
    # Meta
    ("facebook.com",            "Meta"),
    ("fbcdn.net",               "Meta"),
    ("instagram.com",           "Meta"),
    ("whatsapp.com",            "Meta"),
    ("whatsapp.net",            "Meta"),
    ("threads.net",             "Meta"),
    ("fb.com",                  "Meta"),
    # Amazon
    ("amazonaws.com",           "Amazon"),
    ("amazon.com",              "Amazon"),
    ("amazon-adsystem.com",     "Amazon"),
    ("amazonvideo.com",         "Amazon"),
    ("alexa.com",               "Amazon"),
    ("awsstatic.com",           "Amazon"),
    # Apple
    ("icloud.com",              "Apple"),
    ("mzstatic.com",            "Apple"),
    ("apple.com",               "Apple"),
    ("apple-dns.net",           "Apple"),
    # Microsoft
    ("microsoft.com",           "Microsoft"),
    ("microsoftonline.com",     "Microsoft"),
    ("office365.com",           "Microsoft"),
    ("outlook.com",             "Microsoft"),
    ("msftconnecttest.com",     "Microsoft"),
    ("windowsupdate.com",       "Microsoft"),
    ("live.com",                "Microsoft"),
    ("bing.com",                "Microsoft"),
    ("azure.com",               "Microsoft"),
    # Samsung
    ("samsung.com",             "Samsung"),
    ("samsungcloudsolution.com","Samsung"),
    ("samsungqbe.com",          "Samsung"),
    ("samsungdm.com",           "Samsung"),
    # ByteDance / TikTok
    ("tiktok.com",              "ByteDance"),
    ("tiktokv.com",             "ByteDance"),
    ("bytedance.com",           "ByteDance"),
    ("byteimg.com",             "ByteDance"),
    # Netflix
    ("netflix.com",             "Netflix"),
    ("nflxvideo.net",           "Netflix"),
    ("nflxext.com",             "Netflix"),
    # Cloudflare
    ("cloudflare.com",          "Cloudflare"),
    ("cloudflare-dns.com",      "Cloudflare"),
    ("cf-cdn.net",              "Cloudflare"),
    # Akamai
    ("akamai.net",              "Akamai"),
    ("akamaiedge.net",          "Akamai"),
    ("akamaitechnologies.com",  "Akamai"),
    # Alibaba
    ("aliyuncs.com",            "Alibaba"),
    ("alicdn.com",              "Alibaba"),
    ("alipay.com",              "Alibaba"),
    # Twitter / X
    ("twitter.com",             "X (Twitter)"),
    ("twimg.com",               "X (Twitter)"),
    ("t.co",                    "X (Twitter)"),
    # Snap
    ("snapchat.com",            "Snap"),
    ("snap.com",                "Snap"),
    # Spotify
    ("spotify.com",             "Spotify"),
    ("scdn.co",                 "Spotify"),
    # MikroTik
    ("mikrotik.com",            "MikroTik"),
    # Tuya
    ("tuya.com",                "Tuya"),
    ("tuyaeu.com",              "Tuya"),
    # Cloudfront (Amazon CDN — separate from Amazon services)
    ("cloudfront.net",          "Amazon CDN"),
    # Fastly
    ("fastly.net",              "Fastly"),
    # Akamai
    ("edgesuite.net",           "Akamai"),
]


# Docker compose default bridge — not real clients
_DOCKER_NET = ipaddress.ip_network("172.18.0.0/16")


def _is_container(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_loopback or addr in _DOCKER_NET
    except ValueError:
        return False


def _classify(domain: str) -> str:
    domain = domain.lower().rstrip(".")
    for suffix, company in _COMPANY_MAP:
        if domain == suffix or domain.endswith("." + suffix):
            return company
    return "Other"


@router.get("/privacy-report")
async def privacy_report():
    """Aggregate DNS queries per device, grouped by parent company."""
    global _privacy_cache, _privacy_cache_ts
    if _privacy_cache is not None and time.monotonic() - _privacy_cache_ts < _PRIVACY_TTL:
        return _privacy_cache

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(
            """SELECT client_ip, domain, COUNT(*) AS cnt
               FROM query_log
               WHERE action NOT IN ('blocked', 'ratelimited', 'scheduled')
               GROUP BY client_ip, domain"""
        )

    # Build per-device company totals (skip Docker containers / loopback)
    device_map: dict[str, dict[str, int]] = {}
    for client_ip, domain, cnt in rows:
        if _is_container(client_ip):
            continue
        company = _classify(domain)
        if client_ip not in device_map:
            device_map[client_ip] = {}
        device_map[client_ip][company] = device_map[client_ip].get(company, 0) + cnt

    # Fetch device labels for display
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        label_rows = await db.execute_fetchall(
            "SELECT ip, label, device_type FROM device_fingerprints"
        )
    labels = {r[0]: (r[1] or "", r[2] or "") for r in label_rows}

    result = []
    for ip, companies in device_map.items():
        total = sum(companies.values())
        breakdown = sorted(
            [{"company": c, "count": n, "pct": round(n / total * 100, 1)}
             for c, n in companies.items()],
            key=lambda x: -x["count"]
        )
        lbl, dtype = labels.get(ip, ("", ""))
        result.append({
            "ip": ip,
            "label": lbl,
            "device_type": dtype,
            "total_forwarded": total,
            "companies": breakdown[:12],
        })

    result.sort(key=lambda x: -x["total_forwarded"])
    _privacy_cache = result
    _privacy_cache_ts = time.monotonic()
    return result


@router.get("/privacy-report/{ip}")
async def privacy_report_device(ip: str):
    """Detailed company breakdown for a single device."""
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(
            """SELECT domain, COUNT(*) AS cnt FROM query_log
               WHERE client_ip=? AND action NOT IN ('blocked','ratelimited','scheduled')
               GROUP BY domain ORDER BY cnt DESC""",
            (ip,),
        )

    company_totals: dict[str, int] = {}
    company_domains: dict[str, list] = {}
    for domain, cnt in rows:
        company = _classify(domain)
        company_totals[company] = company_totals.get(company, 0) + cnt
        if company not in company_domains:
            company_domains[company] = []
        if len(company_domains[company]) < 5:
            company_domains[company].append({"domain": domain, "count": cnt})

    total = sum(company_totals.values())
    breakdown = sorted(
        [{"company": c, "count": n, "pct": round(n / total * 100, 1),
          "top_domains": company_domains.get(c, [])}
         for c, n in company_totals.items()],
        key=lambda x: -x["count"]
    )
    return {"ip": ip, "total_forwarded": total, "companies": breakdown}
