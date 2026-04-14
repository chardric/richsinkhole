# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Built-in blocklist sources that ship with RichSinkhole.

Focus: ads, scam, phishing, malware. No aggressive tracking lists
that break legitimate apps (banking, shopping, productivity).

These cannot be removed from the dashboard UI. If a source fails
3 consecutive fetches, it is automatically disabled until it recovers.
"""

DEFAULT_SOURCES = [
    # Ad blocking (foundational — well-curated, minimal false positives)
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "https://adaway.org/hosts.txt",
    "https://raw.githubusercontent.com/anudeepND/blacklist/master/adservers.txt",
    # Adult content blocking
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn/hosts",
    "https://raw.githubusercontent.com/mhhakim/pihole-blocklist/master/porn.txt",
    "https://blocklistproject.github.io/Lists/porn.txt",
    # Phishing / scam (daily updated, catches fake sites)
    "https://curbengh.github.io/phishing-filter/phishing-filter-hosts.txt",
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/fake.txt",
    # Popup / popunder ad networks (Hagezi, daily)
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/popupads.txt",
    # Active threat intelligence: malware, stalkerware, cryptominers, scam shops,
    # phishing (Hagezi TIF aggregates OpenPhish, PhishTank, URLhaus, DigitalSide,
    # ThreatFox, etc.). Daily updated, low false-positive rate.
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/hosts/tif.txt",
]

# Max consecutive failures before a default source is auto-disabled
MAX_FAILURES = 3
