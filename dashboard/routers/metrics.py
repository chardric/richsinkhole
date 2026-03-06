"""
Prometheus-compatible /metrics endpoint.
Exposes DNS sinkhole stats in text exposition format (no library needed).
"""
import aiosqlite
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

SINKHOLE_DB  = "/data/sinkhole.db"
BLOCKLIST_DB = "/data/blocklist.db"

router = APIRouter()


def _gauge(name: str, help_text: str, value, labels: dict | None = None) -> str:
    label_str = ""
    if labels:
        pairs = ",".join(f'{k}="{v}"' for k, v in labels.items())
        label_str = f"{{{pairs}}}"
    return f"# HELP {name} {help_text}\n# TYPE {name} gauge\n{name}{label_str} {value}\n"


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def prometheus_metrics():
    lines: list[str] = []

    async with aiosqlite.connect(SINKHOLE_DB) as db:
        (total,)    = (await db.execute_fetchall("SELECT COUNT(*) FROM query_log"))[0]
        (blocked,)  = (await db.execute_fetchall("SELECT COUNT(*) FROM query_log WHERE action='blocked'"))[0]
        (forwarded,)= (await db.execute_fetchall("SELECT COUNT(*) FROM query_log WHERE action IN ('forwarded','allowed','cached')"))[0]
        (redirected,)=(await db.execute_fetchall("SELECT COUNT(*) FROM query_log WHERE action IN ('captive','youtube','redirected')"))[0]
        (scheduled,)= (await db.execute_fetchall("SELECT COUNT(*) FROM query_log WHERE action='scheduled'"))[0]
        (clients,)  = (await db.execute_fetchall("SELECT COUNT(DISTINCT client_ip) FROM query_log"))[0]
        (rl_24h,)   = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM query_log WHERE action='ratelimited' AND ts >= datetime('now','-1 day')"
        ))[0]

        # Security events (24h)
        sec_rows = await db.execute_fetchall(
            "SELECT event_type, COUNT(*) FROM security_events WHERE ts >= datetime('now','-1 day') GROUP BY event_type"
        )

        # Active client blocks
        (active_blocks,) = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM client_blocks WHERE expires_at > datetime('now')"
        ))[0]

        # Device count
        (devices,) = (await db.execute_fetchall("SELECT COUNT(*) FROM device_fingerprints"))[0]

    async with aiosqlite.connect(BLOCKLIST_DB) as db:
        (blocked_domains,) = (await db.execute_fetchall("SELECT COUNT(*) FROM blocked_domains"))[0]
        (allowed_domains,) = (await db.execute_fetchall(
            "SELECT COUNT(*) FROM allowed_domains"
        ))[0] if (await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name='allowed_domains'")) else (0,)
        # Threat intel domains
        ti_rows = await db.execute_fetchall(
            "SELECT COUNT(*) FROM blocked_domains WHERE source='threat_intel'"
        ) if (await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type='column' AND name='source'")) else [(0,)]
        threat_intel_domains = ti_rows[0][0] if ti_rows else 0

    block_pct = round(blocked / total * 100, 2) if total else 0.0
    ad_revenue = round(blocked * 0.0035, 2)

    lines.append(_gauge("richsinkhole_queries_total", "Total DNS queries logged", total))
    lines.append(_gauge("richsinkhole_queries_blocked_total", "Total blocked DNS queries", blocked))
    lines.append(_gauge("richsinkhole_queries_forwarded_total", "Total forwarded DNS queries", forwarded))
    lines.append(_gauge("richsinkhole_queries_redirected_total", "Total redirected DNS queries (captive/youtube)", redirected))
    lines.append(_gauge("richsinkhole_queries_scheduled_total", "Total DNS queries blocked by schedule rules", scheduled))
    lines.append(_gauge("richsinkhole_block_percent", "Percentage of queries blocked", block_pct))
    lines.append(_gauge("richsinkhole_clients_total", "Unique client IPs seen", clients))
    lines.append(_gauge("richsinkhole_ratelimited_24h", "Rate-limited queries in last 24h", rl_24h))
    lines.append(_gauge("richsinkhole_active_client_blocks", "Currently blocked client IPs", active_blocks))
    lines.append(_gauge("richsinkhole_blocklist_domains_total", "Total domains in blocklist", blocked_domains))
    lines.append(_gauge("richsinkhole_allowlist_domains_total", "Total domains in custom allowlist", allowed_domains))
    lines.append(_gauge("richsinkhole_threat_intel_domains_total", "Threat intel domains blocked", threat_intel_domains))
    lines.append(_gauge("richsinkhole_devices_fingerprinted", "Number of fingerprinted devices", devices))
    lines.append(_gauge("richsinkhole_bandwidth_saved_mb", "Estimated bandwidth saved (MB)", round(blocked * 75 / 1024, 1)))
    lines.append(_gauge("richsinkhole_ad_revenue_denied_usd", "Estimated ad revenue denied (USD)", ad_revenue))

    for event_type, count in sec_rows:
        lines.append(_gauge("richsinkhole_security_events_24h", f"Security events in last 24h", count, {"type": event_type}))

    return "".join(lines)
