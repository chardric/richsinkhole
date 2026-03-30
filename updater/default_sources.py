# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Built-in blocklist sources that ship with RichSinkhole.

These cannot be removed from the dashboard UI. If a source fails
3 consecutive fetches, it is automatically disabled until it recovers.
"""

DEFAULT_SOURCES = [
    # Ad blocking (foundational)
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "https://adaway.org/hosts.txt",
    "https://raw.githubusercontent.com/anudeepND/blacklist/master/adservers.txt",
    # Adult content blocking
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn/hosts",
    "https://raw.githubusercontent.com/mhhakim/pihole-blocklist/master/porn.txt",
    "https://blocklistproject.github.io/Lists/porn.txt",
    # Affiliate tracking / redirect links (Hagezi, daily, ~1.4k)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/blocklist-referral-native.txt",
    # Popup / popunder ad networks (Hagezi, daily, ~53k)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/popupads.txt",
    # Fake shops / scam redirect infrastructure (Hagezi, daily, ~14k)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/fake.txt",
    # General tracking — SDK, analytics, telemetry (ShadowWhisperer, ~97k)
    "https://raw.githubusercontent.com/ShadowWhisperer/BlockLists/master/RAW/Tracking",
    # Phishing landing pages (curbengh, 12-hourly, ~24k)
    "https://curbengh.github.io/phishing-filter/phishing-filter-hosts.txt",
    # Samsung native device trackers (Hagezi)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/native.samsung.txt",
    # Xiaomi native device trackers (Hagezi)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/native.xiaomi.txt",
    # TikTok native trackers (Hagezi)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/native.tiktok.txt",
]

# Max consecutive failures before a default source is auto-disabled
MAX_FAILURES = 3
