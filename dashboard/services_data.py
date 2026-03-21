# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""Blocked-services definitions — pure data, no framework imports."""

GROUPS = [
    {"id": "social", "name": "Social Media"},
    {"id": "streaming", "name": "Streaming & Video"},
    {"id": "messaging", "name": "Messaging"},
    {"id": "gaming", "name": "Gaming"},
    {"id": "shopping", "name": "Shopping"},
    {"id": "ai", "name": "AI Services"},
    {"id": "adult", "name": "Adult Content"},
    {"id": "gambling", "name": "Gambling"},
]

SERVICES = [
    # ── Social Media ─────────────────────────────────────────────────────────
    {
        "id": "facebook",
        "name": "Facebook",
        "group": "social",
        "domains": [
            "facebook.com", "fb.com", "fbcdn.net", "fbcdn.com",
            "fbsbx.com", "m.me",
        ],
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "group": "social",
        "domains": ["instagram.com", "cdninstagram.com", "ig.me"],
    },
    {
        "id": "twitter",
        "name": "X (Twitter)",
        "group": "social",
        "domains": ["twitter.com", "x.com", "twimg.com", "t.co"],
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "group": "social",
        "domains": [
            "tiktok.com", "tiktokcdn.com", "tiktokv.com",
            "musical.ly", "byteoversea.com", "byteimg.com",
        ],
    },
    {
        "id": "snapchat",
        "name": "Snapchat",
        "group": "social",
        "domains": ["snapchat.com", "snap.com", "snapkit.co", "sc-cdn.net"],
    },
    {
        "id": "reddit",
        "name": "Reddit",
        "group": "social",
        "domains": [
            "reddit.com", "redd.it", "redditmedia.com", "redditstatic.com",
        ],
    },
    {
        "id": "linkedin",
        "name": "LinkedIn",
        "group": "social",
        "domains": ["linkedin.com", "licdn.com"],
    },
    {
        "id": "pinterest",
        "name": "Pinterest",
        "group": "social",
        "domains": ["pinterest.com", "pinimg.com"],
    },
    {
        "id": "tumblr",
        "name": "Tumblr",
        "group": "social",
        "domains": ["tumblr.com"],
    },

    # ── Streaming & Video ────────────────────────────────────────────────────
    {
        "id": "youtube",
        "name": "YouTube",
        "group": "streaming",
        "domains": [
            "youtube.com", "youtu.be", "yt.be", "youtube-nocookie.com",
            "youtubekids.com", "ytimg.com", "googlevideo.com", "ggpht.com",
        ],
    },
    {
        "id": "netflix",
        "name": "Netflix",
        "group": "streaming",
        "domains": [
            "netflix.com", "nflxvideo.net", "nflximg.net", "nflximg.com",
            "nflxext.com", "nflxso.net",
        ],
    },
    {
        "id": "twitch",
        "name": "Twitch",
        "group": "streaming",
        "domains": [
            "twitch.tv", "twitchcdn.net", "twitchsvc.net", "jtvnw.net",
        ],
    },
    {
        "id": "spotify",
        "name": "Spotify",
        "group": "streaming",
        "domains": ["spotify.com", "scdn.co", "spotifycdn.com"],
    },
    {
        "id": "disneyplus",
        "name": "Disney+",
        "group": "streaming",
        "domains": [
            "disneyplus.com", "disney-plus.net", "dssott.com",
            "bamgrid.com", "disney.io",
        ],
    },
    {
        "id": "hulu",
        "name": "Hulu",
        "group": "streaming",
        "domains": ["hulu.com", "hulustream.com", "huluim.com"],
    },
    {
        "id": "amazon_video",
        "name": "Amazon Video",
        "group": "streaming",
        "domains": ["primevideo.com", "amazonvideo.com", "aiv-cdn.net"],
    },

    # ── Messaging ────────────────────────────────────────────────────────────
    {
        "id": "whatsapp",
        "name": "WhatsApp",
        "group": "messaging",
        "domains": ["whatsapp.com", "whatsapp.net", "wa.me"],
    },
    {
        "id": "telegram",
        "name": "Telegram",
        "group": "messaging",
        "domains": ["telegram.org", "telegram.me", "t.me", "telesco.pe"],
    },
    {
        "id": "discord",
        "name": "Discord",
        "group": "messaging",
        "domains": [
            "discord.com", "discord.gg", "discordapp.com",
            "discordapp.net", "discord.media",
        ],
    },
    {
        "id": "signal",
        "name": "Signal",
        "group": "messaging",
        "domains": ["signal.org", "signal.art"],
    },
    {
        "id": "viber",
        "name": "Viber",
        "group": "messaging",
        "domains": ["viber.com", "viber.io"],
    },

    # ── Gaming ───────────────────────────────────────────────────────────────
    {
        "id": "steam",
        "name": "Steam",
        "group": "gaming",
        "domains": [
            "steampowered.com", "steamcommunity.com", "steamstatic.com",
            "steamcdn-a.akamaihd.net", "steamcontent.com",
        ],
    },
    {
        "id": "epicgames",
        "name": "Epic Games",
        "group": "gaming",
        "domains": ["epicgames.com", "unrealengine.com", "fortnite.com"],
    },
    {
        "id": "roblox",
        "name": "Roblox",
        "group": "gaming",
        "domains": ["roblox.com", "rbxcdn.com", "roblox.cn"],
    },
    {
        "id": "xbox",
        "name": "Xbox",
        "group": "gaming",
        "domains": ["xbox.com", "xboxlive.com", "xboxab.com"],
    },
    {
        "id": "playstation",
        "name": "PlayStation",
        "group": "gaming",
        "domains": [
            "playstation.com", "playstation.net",
            "sonyentertainmentnetwork.com",
        ],
    },
    {
        "id": "minecraft",
        "name": "Minecraft",
        "group": "gaming",
        "domains": ["minecraft.net", "mojang.com"],
    },

    # ── Shopping ─────────────────────────────────────────────────────────────
    {
        "id": "amazon",
        "name": "Amazon",
        "group": "shopping",
        "domains": [
            "amazon.com", "amazon.co.uk", "amazon.de", "amazon.co.jp",
            "amazon.in", "amazon.fr", "amazon.it", "amazon.es",
            "amazon.ca", "amazon.com.au", "amazon.com.br", "amazon.sg",
            "images-amazon.com", "ssl-images-amazon.com", "media-amazon.com",
        ],
    },
    {
        "id": "ebay",
        "name": "eBay",
        "group": "shopping",
        "domains": [
            "ebay.com", "ebayimg.com", "ebaystatic.com", "ebayrtm.com",
        ],
    },
    {
        "id": "aliexpress",
        "name": "AliExpress",
        "group": "shopping",
        "domains": ["aliexpress.com", "aliexpress.ru", "alicdn.com"],
    },
    {
        "id": "shopee",
        "name": "Shopee",
        "group": "shopping",
        "domains": [
            "shopee.com", "shopee.ph", "shopee.sg", "shopee.co.id",
            "shopee.co.th", "shopee.vn", "shopee.com.my", "shopee.com.br",
        ],
    },
    {
        "id": "lazada",
        "name": "Lazada",
        "group": "shopping",
        "domains": [
            "lazada.com", "lazada.co.id", "lazada.co.th",
            "lazada.com.my", "lazada.com.ph", "lazada.sg", "lazada.vn",
        ],
    },
    {
        "id": "temu",
        "name": "Temu",
        "group": "shopping",
        "domains": ["temu.com"],
    },

    # ── AI Services ──────────────────────────────────────────────────────────
    {
        "id": "chatgpt",
        "name": "ChatGPT",
        "group": "ai",
        "domains": [
            "chat.openai.com", "openai.com", "chatgpt.com",
            "oaiusercontent.com", "oaistatic.com",
        ],
    },
    {
        "id": "claude",
        "name": "Claude",
        "group": "ai",
        "domains": ["claude.ai", "anthropic.com"],
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "group": "ai",
        "domains": ["gemini.google.com", "bard.google.com"],
    },
    {
        "id": "copilot",
        "name": "Copilot",
        "group": "ai",
        "domains": ["copilot.microsoft.com", "copilot.cloud.microsoft"],
    },
    {
        "id": "perplexity",
        "name": "Perplexity",
        "group": "ai",
        "domains": ["perplexity.ai"],
    },

    # ── Adult Content ────────────────────────────────────────────────────────
    {
        "id": "pornhub",
        "name": "Pornhub",
        "group": "adult",
        "domains": ["pornhub.com", "phncdn.com"],
    },
    {
        "id": "xvideos",
        "name": "XVideos",
        "group": "adult",
        "domains": ["xvideos.com", "xvideos-cdn.com"],
    },
    {
        "id": "xnxx",
        "name": "XNXX",
        "group": "adult",
        "domains": ["xnxx.com", "xnxx-cdn.com"],
    },
    {
        "id": "xhamster",
        "name": "xHamster",
        "group": "adult",
        "domains": ["xhamster.com", "xhcdn.com"],
    },
    {
        "id": "onlyfans",
        "name": "OnlyFans",
        "group": "adult",
        "domains": ["onlyfans.com"],
    },

    # ── Gambling ─────────────────────────────────────────────────────────────
    {
        "id": "bet365",
        "name": "Bet365",
        "group": "gambling",
        "domains": ["bet365.com"],
    },
    {
        "id": "draftkings",
        "name": "DraftKings",
        "group": "gambling",
        "domains": ["draftkings.com", "draftkings.io"],
    },
    {
        "id": "fanduel",
        "name": "FanDuel",
        "group": "gambling",
        "domains": ["fanduel.com"],
    },
    {
        "id": "betway",
        "name": "Betway",
        "group": "gambling",
        "domains": ["betway.com"],
    },
    {
        "id": "pokerstars",
        "name": "PokerStars",
        "group": "gambling",
        "domains": ["pokerstars.com", "pokerstars.net"],
    },
]

# Fast lookup: service_id → service dict
SERVICES_BY_ID = {s["id"]: s for s in SERVICES}
