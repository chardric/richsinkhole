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
from fastapi import APIRouter, Query

SINKHOLE_DB = "/local/sinkhole.db"

router = APIRouter()

# Keyed cache — separate entries per time range
_privacy_cache: dict[str, tuple[float, list]] = {}
_PRIVACY_TTL = 120.0  # heavier query — cache for 2 minutes
_VALID_RANGES = {"24h": "-24 hours", "7d": "-7 days"}

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
    ("aliyuncsslbintl.com",     "Alibaba"),
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
    ("spotifycdn.com",          "Spotify"),
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
    # Microsoft (additional)
    ("office.com",              "Microsoft"),
    ("office.net",              "Microsoft"),
    ("skype.com",               "Microsoft"),
    ("msn.com",                 "Microsoft"),
    ("azure.net",               "Microsoft"),
    ("msftncsi.com",            "Microsoft"),
    # Google (additional)
    ("googleusercontent.com",   "Google"),
    ("chatgpt.com",             "OpenAI"),
    # Meta (additional)
    ("messenger.com",           "Meta"),
    # Mozilla
    ("mozilla.com",             "Mozilla"),
    ("mozilla.org",             "Mozilla"),
    ("firefox.com",             "Mozilla"),
    # Shopee / Sea Group
    ("shopee.ph",               "Shopee"),
    ("shopeemobile.com",        "Shopee"),
    ("susercontent.com",        "Shopee"),
    # GitHub (Microsoft)
    ("github.com",              "GitHub"),
    ("github.io",               "GitHub"),
    ("githubusercontent.com",   "GitHub"),
    # Canonical
    ("ubuntu.com",              "Canonical"),
    # TP-Link
    ("tp-link.com",             "TP-Link"),
    ("tplinkcloud.com",         "TP-Link"),
    ("tplinkdns.com",           "TP-Link"),
    # Anthropic
    ("anthropic.com",           "Anthropic"),
    ("claude.ai",               "Anthropic"),
    # Datadog
    ("datadoghq.com",           "Datadog"),
    # Honor / Huawei
    ("hihonorcloud.com",        "Honor"),
    ("hicloud.com",             "Honor"),
    ("huawei.com",              "Honor"),
    # Qihoo 360
    ("360safe.com",             "Qihoo 360"),
    ("360.cn",                  "Qihoo 360"),
    # Linux Mint
    ("linuxmint.com",           "Linux Mint"),
    # Cloudflare (additional)
    ("argotunnel.com",          "Cloudflare"),
    ("pages.dev",               "Cloudflare"),
    ("cloudflarestorage.com",   "Cloudflare"),
    ("cloudflare.net",          "Cloudflare"),
    # Tuya (additional — iotbing.com is Tuya Smart IoT)
    ("iotbing.com",             "Tuya"),
    # Microsoft (additional)
    ("sharepoint.com",          "Microsoft"),
    ("appcenter.ms",            "Microsoft"),
    ("sfx.ms",                  "Microsoft"),
    ("svc.ms",                  "Microsoft"),
    ("linkedin.com",            "Microsoft"),
    ("onedrive.com",            "Microsoft"),
    ("windows.com",             "Microsoft"),
    ("windows.net",             "Microsoft"),
    ("xboxservices.com",        "Microsoft"),
    ("xboxlive.com",            "Microsoft"),
    ("live.net",                "Microsoft"),
    ("msauth.net",              "Microsoft"),
    ("msftauth.net",            "Microsoft"),
    ("nelreports.net",          "Microsoft"),
    ("s-microsoft.com",         "Microsoft"),
    ("msftstatic.com",          "Microsoft"),
    ("cloud.microsoft",         "Microsoft"),
    ("static.microsoft",        "Microsoft"),
    ("microsoftpersonalcontent.com", "Microsoft"),
    ("fb-t-msedge.net",         "Microsoft"),
    ("azurewebsites.net",       "Microsoft"),
    ("azureedge.net",           "Microsoft"),
    # Google (additional)
    ("pkg.dev",                 "Google"),
    ("gvt1.com",                "Google"),
    ("gvt2.com",                "Google"),
    ("ggpht.com",               "Google"),
    ("pki.goog",                "Google"),
    ("google.cn",               "Google"),
    ("withgoogle.com",          "Google"),
    ("mozgcp.net",              "Google"),
    # Amazon (additional)
    ("pv-cdn.net",              "Amazon"),
    ("a2z.com",                 "Amazon"),
    ("media-amazon.com",        "Amazon"),
    ("ssl-images-amazon.com",   "Amazon"),
    ("awsglobalaccelerator.com","Amazon"),
    # Meta (additional)
    ("fbpigeon.com",            "Meta"),
    ("cdninstagram.com",        "Meta"),
    ("fbsbx.com",               "Meta"),
    # Canonical (additional)
    ("launchpadcontent.net",    "Canonical"),
    # Docker
    ("docker.com",              "Docker"),
    ("docker.io",               "Docker"),
    # Atlassian
    ("atlassian.net",           "Atlassian"),
    ("atlassian.com",           "Atlassian"),
    ("bitbucket.org",           "Atlassian"),
    ("atl-paas.net",            "Atlassian"),
    ("statuspage.io",           "Atlassian"),
    ("opsgenie.com",            "Atlassian"),
    # Vercel
    ("nextjs.org",              "Vercel"),
    ("vercel.com",              "Vercel"),
    ("vercel.app",              "Vercel"),
    # Twingate
    ("twingate.com",            "Twingate"),
    # Telecom standards (3GPP — mobile carrier signaling)
    ("3gppnetwork.org",         "3GPP Mobile"),
    # OpenAI (additional)
    ("openai.com",              "OpenAI"),
    ("oaistatic.com",           "OpenAI"),
    # ByteDance / TikTok (additional)
    ("capcutapi.com",           "ByteDance"),
    ("capcut.com",              "ByteDance"),
    ("ibyteimg.com",            "ByteDance"),
    ("tiktokcdn.com",           "ByteDance"),
    ("i18n-pglstatp.com",       "ByteDance"),
    # Samsung (additional)
    ("samsungcloud.com",        "Samsung"),
    ("samsungapps.com",         "Samsung"),
    ("samsungosp.com",          "Samsung"),
    # Akamai (additional)
    ("akamaized.net",           "Akamai"),
    ("akamaihd.net",            "Akamai"),
    # Fastly (additional)
    ("fastly-edge.com",         "Fastly"),
    # Spotify (additional)
    ("tospotify.com",           "Spotify"),
    # Netflix (additional)
    ("nflxso.net",              "Netflix"),
    # Shopee / Sea Group (additional)
    ("shopeepay.ph",            "Shopee"),
    ("shopee.io",               "Shopee"),
    ("shopee.sg",               "Shopee"),
    ("shopee.com",              "Shopee"),
    ("garena.com",              "Shopee"),
    # Xiaomi
    ("xiaomi.com",              "Xiaomi"),
    ("xiaomi.net",              "Xiaomi"),
    ("miui.com",                "Xiaomi"),
    ("mi.com",                  "Xiaomi"),
    # Brave
    ("brave.com",               "Brave"),
    ("bravesoftware.com",       "Brave"),
    # Tencent
    ("qq.com",                  "Tencent"),
    ("tdatamaster.com",         "Tencent"),
    # Wikimedia
    ("wikimedia.org",           "Wikimedia"),
    ("wikipedia.org",           "Wikimedia"),
    # AppsFlyer
    ("appsflyersdk.com",        "AppsFlyer"),
    ("appsflyer.com",           "AppsFlyer"),
    # Salesforce
    ("herokudns.com",           "Salesforce"),
    ("salesforce.com",          "Salesforce"),
    # Automattic
    ("gravatar.com",            "Automattic"),
    ("wordpress.com",           "Automattic"),
    # Reddit
    ("reddit.com",              "Reddit"),
    # DuckDuckGo
    ("duckduckgo.com",          "DuckDuckGo"),
    # X (Twitter) additional
    ("x.com",                   "X (Twitter)"),
    # Giphy (Shutterstock)
    ("giphy.com",               "Shutterstock"),
    # Let's Encrypt / ISRG
    ("lencr.org",               "Let's Encrypt"),
    # DigiCert
    ("digicert.com",            "DigiCert"),
    # Dell
    ("dell.com",                "Dell"),
    ("dellcdn.com",             "Dell"),
    # Stripe
    ("stripe.com",              "Stripe"),
    # Figma
    ("figma.com",               "Figma"),
    # PUBG / Krafton
    ("gpubgm.com",              "Krafton"),
    # GCash / PayMaya (Philippine fintech)
    ("gcash.com",               "GCash"),
    ("paymaya.com",             "Maya"),
    # Sentry
    ("sentry.io",               "Sentry"),
    # New Relic
    ("newrelic.com",            "New Relic"),
    # Intercom
    ("intercom.io",             "Intercom"),
    ("intercomcdn.com",         "Intercom"),
    # CleverTap
    ("clevertap-prod.com",      "CleverTap"),
    # LaunchDarkly
    ("launchdarkly.com",        "LaunchDarkly"),
    # MediaTek
    ("mediatek.com",            "MediaTek"),
    # AccuWeather
    ("accuweather.com",         "AccuWeather"),
    ("weather.com",             "Weather.com"),
    # jsDelivr CDN
    ("jsdelivr.net",            "jsDelivr"),
    # npm (Microsoft/GitHub)
    ("npmjs.org",               "npm"),
    # Ollama
    ("ollama.ai",               "Ollama"),
    # AdGuard
    ("adguard.com",             "AdGuard"),
    # OpenStreetMap
    ("openstreetmap.org",       "OpenStreetMap"),
    # Niimbot (label printer)
    ("niimbot.com",             "Niimbot"),
    # Qihoo 360 (additional)
    ("360mads.com",             "Qihoo 360"),
    ("360.com",                 "Qihoo 360"),
    ("360totalsecurity.com",    "Qihoo 360"),
    # Scribd
    ("scribd.com",              "Scribd"),
    ("scribdassets.com",        "Scribd"),
    # jQuery / OpenJS
    ("jquery.com",              "jQuery"),
    # Security Bank PH
    ("securitybank.com",        "Security Bank"),
    # Honor (additional)
    ("hihonor.com",             "Honor"),
    # Voyager / Smart (PH telecom)
    ("voyagerapis.com",         "Smart/PLDT"),
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
    # Fallback: use the parent domain as the company name (e.g. "example.org")
    parts = domain.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain or "Unknown"


@router.get("/privacy-report")
async def privacy_report(range: str = Query("24h", pattern="^(24h|7d)$")):
    """Aggregate DNS queries per device, grouped by parent company."""
    cached = _privacy_cache.get(range)
    if cached and time.monotonic() - cached[0] < _PRIVACY_TTL:
        return cached[1]

    sql_range = _VALID_RANGES[range]
    async with aiosqlite.connect(SINKHOLE_DB) as db:
        rows = await db.execute_fetchall(
            f"""SELECT client_ip, domain, COUNT(*) AS cnt
               FROM query_log
               WHERE ts >= datetime('now', 'localtime', '{sql_range}')
                 AND action NOT IN ('blocked', 'ratelimited', 'scheduled')
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
    _privacy_cache[range] = (time.monotonic(), result)
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
