# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""
Email notification background worker for RichSinkhole.

Watches for:
  - New client blocks (security alerts) — checked every 60s
  - Blocklist update results            — checked every 60s
  - Daily digest                        — sent once per day at configured hour
"""
import asyncio
import logging
import smtplib
import sqlite3
import ssl
import time
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yaml

CONFIG_PATH = "/config/config.yml"
SINKHOLE_DB = "/data/sinkhole.db"
STATUS_PATH = "/data/updater_status.json"

log = logging.getLogger("notifier")

# ── Runtime state ─────────────────────────────────────────────────────────────
_last_block_check_ts: str   = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
_last_digest_sent:    str   = ""   # ISO date of last sent digest
_last_update_ts:      str   = ""
_last_alert_sent:     float = 0.0   # monotonic; rate-limits security alert emails
_ALERT_COOLDOWN             = 3600  # seconds — at most 1 security alert email per hour

_FREQ_DAYS = {"weekly": 7, "monthly": 30, "yearly": 365}


# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return (yaml.safe_load(f) or {}).get("email_notifications", {})
    except Exception:
        return {}


# ── HTML email template ───────────────────────────────────────────────────────

def _html_wrap(subtitle: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#24292f">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5">
<tr><td align="center" style="padding:32px 16px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">

  <!-- Header -->
  <tr><td style="background:#0d1117;border-radius:12px 12px 0 0;padding:28px 32px">
    <table width="100%" cellpadding="0" cellspacing="0"><tr>
      <td>
        <div style="font-size:20px;font-weight:700;color:#58a6ff;letter-spacing:-0.5px">
          &#9670; RichSinkhole
        </div>
        <div style="font-size:13px;color:#8b949e;margin-top:4px">{subtitle}</div>
      </td>
      <td align="right">
        <div style="font-size:11px;color:#6e7681">{date.today().strftime("%B %d, %Y")}</div>
      </td>
    </tr></table>
  </td></tr>

  <!-- Body -->
  <tr><td style="background:#ffffff;padding:32px 32px 24px">
    {content}
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#161b22;border-radius:0 0 12px 12px;padding:18px 32px;text-align:center">
    <div style="font-size:12px;color:#6e7681">
      RichSinkhole DNS Sinkhole &bull; Sent automatically &bull; Manage in
      <span style="color:#58a6ff">Settings &rarr; Email Notifications</span>
    </div>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""


def _badge(text: str, color: str) -> str:
    """Inline colored badge for HTML emails."""
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:20px;'
        f'font-size:12px;font-weight:600;background:{color};color:#fff">{text}</span>'
    )


def _stat_card(label: str, value: str, color: str = "#58a6ff") -> str:
    return (
        f'<td style="text-align:center;padding:16px 12px;background:#f6f8fa;'
        f'border-radius:8px;border:1px solid #d0d7de">'
        f'<div style="font-size:26px;font-weight:700;color:{color}">{value}</div>'
        f'<div style="font-size:12px;color:#57606a;margin-top:4px">{label}</div>'
        f'</td>'
    )


# ── Email body builders ───────────────────────────────────────────────────────

def _security_alert_html(blocks: list[dict]) -> str:
    count = len(blocks)
    noun  = "client" if count == 1 else "clients"

    rows = ""
    for b in blocks:
        rows += f"""
        <tr>
          <td style="padding:10px 12px;font-family:monospace;font-size:13px;border-bottom:1px solid #d0d7de">{b['ip']}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #d0d7de">{_badge(b['reason_label'], '#cf222e')}</td>
          <td style="padding:10px 12px;text-align:right;font-size:13px;color:#57606a;border-bottom:1px solid #d0d7de">{b['query_count']:,}</td>
          <td style="padding:10px 12px;font-size:12px;color:#57606a;font-family:monospace;border-bottom:1px solid #d0d7de">{b['blocked_at']}</td>
          <td style="padding:10px 12px;font-size:12px;color:#57606a;font-family:monospace;border-bottom:1px solid #d0d7de">{b['expires_at']}</td>
        </tr>"""

    content = f"""
    <div style="margin-bottom:20px">
      <div style="font-size:18px;font-weight:700;color:#cf222e;margin-bottom:6px">
        &#9888; Security Alert
      </div>
      <div style="font-size:14px;color:#57606a">
        RichSinkhole has auto-blocked <strong>{count} {noun}</strong> for suspicious DNS activity.
      </div>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #d0d7de;border-radius:8px;border-collapse:collapse;overflow:hidden;font-size:13px">
      <thead>
        <tr style="background:#f6f8fa">
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">IP Address</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">Reason</th>
          <th style="padding:10px 12px;text-align:right;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">Queries</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">Blocked At</th>
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">Expires At</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    <div style="margin-top:20px;padding:14px 16px;background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;font-size:13px;color:#633c01">
      You can manually unblock clients from the <strong>Security</strong> tab in the RichSinkhole dashboard.
    </div>"""

    return _html_wrap(f"Security Alert — {count} {noun} auto-blocked", content)


def _security_alert_plain(blocks: list[dict]) -> str:
    lines = ["RichSinkhole has auto-blocked the following client(s):", ""]
    for b in blocks:
        lines += [
            f"  IP          : {b['ip']}",
            f"  Reason      : {b['reason_label']}",
            f"  Queries     : {b['query_count']:,}",
            f"  Blocked at  : {b['blocked_at']}",
            f"  Expires at  : {b['expires_at']}",
            "",
        ]
    lines += ["Unblock clients from the Security tab in your dashboard.", "", "— RichSinkhole"]
    return "\n".join(lines)


def _digest_html(stats: dict, freq: str, days: int) -> str:
    today     = date.today().strftime("%Y-%m-%d")
    pct       = f"{stats['block_pct']:.1f}%"
    label     = freq.capitalize()
    period    = f"Last {days} days" if days > 1 else "Last 24 hours"
    top_rows  = ""
    max_cnt   = stats["top_blocked"][0][1] if stats["top_blocked"] else 1
    for domain, cnt in stats["top_blocked"]:
        bar_w = max(4, round(cnt / max_cnt * 100))
        top_rows += f"""
        <tr>
          <td style="padding:8px 12px;font-family:monospace;font-size:13px;color:#24292f;border-bottom:1px solid #f0f2f5">{domain}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0f2f5">
            <div style="background:#ffd7d5;border-radius:4px;height:8px;width:100%;overflow:hidden">
              <div style="background:#cf222e;border-radius:4px;height:8px;width:{bar_w}%"></div>
            </div>
          </td>
          <td style="padding:8px 12px;text-align:right;font-size:13px;color:#57606a;font-weight:600;border-bottom:1px solid #f0f2f5">{cnt:,}</td>
        </tr>"""

    content = f"""
    <div style="font-size:18px;font-weight:700;color:#0d1117;margin-bottom:4px">{label} Digest</div>
    <div style="font-size:13px;color:#57606a;margin-bottom:24px">{today} &bull; {period}</div>

    <!-- Stat cards -->
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;margin-bottom:24px">
      <tr>
        {_stat_card("Total Queries",   f"{stats['total']:,}",       "#0969da")}
        <td style="width:8px"></td>
        {_stat_card("Blocked",         f"{stats['blocked']:,}",     "#cf222e")}
        <td style="width:8px"></td>
        {_stat_card("Block Rate",      pct,                          "#cf222e")}
        <td style="width:8px"></td>
        {_stat_card("Clients Seen",    f"{stats['clients']:,}",     "#57606a")}
      </tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;margin-bottom:28px">
      <tr>
        {_stat_card("Forwarded",    f"{stats['forwarded']:,}",    "#1a7f37")}
        <td style="width:8px"></td>
        {_stat_card("NXDOMAIN",    f"{stats['nxdomain']:,}",     "#9a6700")}
        <td style="width:8px"></td>
        {_stat_card("Rate Limited", f"{stats['ratelimited']:,}", "#6e40c9")}
        <td style="width:8px"></td>
        {_stat_card("Auto-Blocks",  f"{stats['auto_blocks']:,}", "#cf222e")}
      </tr>
    </table>

    <!-- Top blocked domains -->
    <div style="font-size:14px;font-weight:700;color:#0d1117;margin-bottom:12px">Top Blocked Domains</div>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #d0d7de;border-radius:8px;border-collapse:collapse;overflow:hidden">
      <thead>
        <tr style="background:#f6f8fa">
          <th style="padding:10px 12px;text-align:left;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">Domain</th>
          <th style="padding:10px 12px;border-bottom:1px solid #d0d7de"></th>
          <th style="padding:10px 12px;text-align:right;font-size:12px;color:#57606a;font-weight:600;border-bottom:1px solid #d0d7de">Blocks</th>
        </tr>
      </thead>
      <tbody>{top_rows if top_rows else f'<tr><td colspan="3" style="padding:16px;text-align:center;color:#57606a;font-size:13px">No blocked domains in the {period.lower()}.</td></tr>'}</tbody>
    </table>"""

    return _html_wrap(f"{label} Digest", content)


def _digest_plain(stats: dict, freq: str, days: int) -> str:
    today  = date.today().strftime("%Y-%m-%d")
    label  = freq.capitalize()
    period = f"last {days} days" if days > 1 else "last 24 hours"
    lines = [
        f"{label} Digest — {today}", "=" * 40, "",
        f"  Period            : {period}",
        f"  Total queries     : {stats['total']:,}",
        f"  Blocked           : {stats['blocked']:,}  ({stats['block_pct']:.1f}%)",
        f"  Forwarded         : {stats['forwarded']:,}",
        f"  NXDOMAIN          : {stats['nxdomain']:,}",
        f"  Rate limited      : {stats['ratelimited']:,}",
        f"  Clients seen      : {stats['clients']:,}",
        f"  Auto-blocks       : {stats['auto_blocks']:,}",
        "", "TOP BLOCKED DOMAINS", "-" * 40,
    ]
    for domain, cnt in stats["top_blocked"]:
        lines.append(f"  {cnt:<6} {domain}")
    lines += ["", "— RichSinkhole"]
    return "\n".join(lines)


def _update_html(status: dict) -> str:
    sw     = status.get("status", "unknown")
    color  = "#1a7f37" if sw == "ok" else "#cf222e"
    badge  = _badge(sw.upper(), color)
    added  = status.get("added", status.get("domains_added", 0))
    content = f"""
    <div style="font-size:18px;font-weight:700;color:#0d1117;margin-bottom:6px">Blocklist Updated</div>
    <div style="font-size:13px;color:#57606a;margin-bottom:24px">The blocklist has been refreshed with the latest domain rules.</div>

    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #d0d7de;border-radius:8px;border-collapse:collapse;overflow:hidden">
      <tr style="background:#f6f8fa">
        <td style="padding:12px 16px;font-size:13px;font-weight:600;color:#57606a;border-bottom:1px solid #d0d7de;width:40%">Status</td>
        <td style="padding:12px 16px;font-size:13px;border-bottom:1px solid #d0d7de">{badge}</td>
      </tr>
      <tr>
        <td style="padding:12px 16px;font-size:13px;font-weight:600;color:#57606a;border-bottom:1px solid #d0d7de">Total Domains</td>
        <td style="padding:12px 16px;font-size:13px;font-weight:700;color:#0d1117;border-bottom:1px solid #d0d7de">{status.get('total_domains', 0):,}</td>
      </tr>
      <tr style="background:#f6f8fa">
        <td style="padding:12px 16px;font-size:13px;font-weight:600;color:#57606a;border-bottom:1px solid #d0d7de">Domains Added</td>
        <td style="padding:12px 16px;font-size:13px;color:#1a7f37;font-weight:700;border-bottom:1px solid #d0d7de">+{added:,}</td>
      </tr>
      <tr>
        <td style="padding:12px 16px;font-size:13px;font-weight:600;color:#57606a">Last Updated</td>
        <td style="padding:12px 16px;font-size:13px;font-family:monospace;color:#57606a">{status.get('last_updated', '—')}</td>
      </tr>
    </table>"""
    return _html_wrap("Blocklist Update", content)


def _update_plain(status: dict) -> str:
    added = status.get("added", status.get("domains_added", 0))
    lines = [
        "Blocklist update completed.", "",
        f"  Status        : {status.get('status', 'unknown')}",
        f"  Total domains : {status.get('total_domains', 0):,}",
        f"  Added         : +{added:,}",
        f"  Last updated  : {status.get('last_updated', '—')}",
        "", "— RichSinkhole",
    ]
    return "\n".join(lines)


def _test_html() -> str:
    content = """
    <div style="text-align:center;padding:16px 0 24px">
      <div style="font-size:48px;margin-bottom:12px">&#10003;</div>
      <div style="font-size:20px;font-weight:700;color:#1a7f37;margin-bottom:8px">Test Successful</div>
      <div style="font-size:14px;color:#57606a">
        Your email notification settings are configured correctly.<br>
        RichSinkhole will send alerts to this address automatically.
      </div>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #d0d7de;border-radius:8px;border-collapse:collapse;overflow:hidden">
      <tr style="background:#dafbe1">
        <td style="padding:14px 16px;font-size:13px;color:#116329">
          <strong>Security Alerts</strong> — Sent when a client is auto-blocked (max 1/hour)
        </td>
      </tr>
      <tr>
        <td style="padding:14px 16px;font-size:13px;color:#24292f;border-top:1px solid #d0d7de">
          <strong>Blocklist Updates</strong> — Sent when the daily blocklist refresh completes
        </td>
      </tr>
      <tr style="background:#f6f8fa">
        <td style="padding:14px 16px;font-size:13px;color:#24292f;border-top:1px solid #d0d7de">
          <strong>Periodic Digest</strong> — Weekly, monthly, or yearly summary
        </td>
      </tr>
    </table>"""
    return _html_wrap("Notifications are working", content)


# ── SMTP send ─────────────────────────────────────────────────────────────────

def _send(subject: str, plain: str, html: str | None = None, *, force: bool = False) -> None:
    """Send an email (plain text + optional HTML). Raises on any error.
    Pass force=True to bypass the enabled check (e.g. test button)."""
    ec = _cfg()
    if not force and not ec.get("enabled"):
        return

    host      = ec.get("smtp_host", "").strip()
    port      = int(ec.get("smtp_port", 587))
    user      = ec.get("smtp_user", "").strip()
    password  = ec.get("smtp_password", "")
    from_addr = ec.get("from_addr", user).strip() or user
    to_addr   = ec.get("to_addr", "").strip()

    if not all([host, user, password, to_addr]):
        raise ValueError("Email config is incomplete — check SMTP settings.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[RichSinkhole] {subject}"
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))

    if port == 465:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
            s.login(user, password)
            s.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            if ec.get("tls", True):
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            s.login(user, password)
            s.sendmail(from_addr, [to_addr], msg.as_string())


async def send_async(subject: str, plain: str, html: str | None = None, *, force: bool = False) -> None:
    """Async wrapper — runs _send() in a thread so it doesn't block the event loop."""
    await asyncio.to_thread(lambda: _send(subject, plain, html, force=force))


# ── DB queries ────────────────────────────────────────────────────────────────

_REASON_LABELS = {
    "rate_limit":     "Query flood",
    "nxdomain_flood": "DNS recon (NXDOMAIN flood)",
}


def _new_blocks(since_ts: str) -> list[dict]:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            rows = conn.execute(
                """SELECT ip, blocked_at, expires_at, reason, query_count
                   FROM client_blocks
                   WHERE blocked_at > ?
                   ORDER BY blocked_at ASC""",
                (since_ts,),
            ).fetchall()
        return [
            {
                "ip": r[0], "blocked_at": r[1], "expires_at": r[2],
                "reason": r[3],
                "reason_label": _REASON_LABELS.get(r[3], r[3]),
                "query_count": r[4],
            }
            for r in rows
        ]
    except Exception:
        return []


def _digest_stats(days: int = 7) -> dict:
    try:
        with sqlite3.connect(SINKHOLE_DB, timeout=5) as conn:
            def q(sql, *p):
                return conn.execute(sql, p).fetchone()

            window     = f"datetime('now', '-{days} days')"
            total      = q(f"SELECT COUNT(*) FROM query_log WHERE ts >= {window}")[0]
            blocked    = q(f"SELECT COUNT(*) FROM query_log WHERE action='blocked' AND ts >= {window}")[0]
            forwarded  = q(f"SELECT COUNT(*) FROM query_log WHERE action='forwarded' AND ts >= {window}")[0]
            nxdomain   = q(f"SELECT COUNT(*) FROM query_log WHERE action='nxdomain' AND ts >= {window}")[0]
            ratelimited= q(f"SELECT COUNT(*) FROM query_log WHERE action='ratelimited' AND ts >= {window}")[0]
            clients    = q(f"SELECT COUNT(DISTINCT client_ip) FROM query_log WHERE ts >= {window}")[0]
            auto_blocks= q(f"SELECT COUNT(*) FROM client_blocks WHERE blocked_at >= {window}")[0]

            top = conn.execute(
                f"""SELECT domain, COUNT(*) as cnt FROM query_log
                    WHERE action='blocked' AND ts >= {window}
                    GROUP BY domain ORDER BY cnt DESC LIMIT 10"""
            ).fetchall()

        pct = (blocked / total * 100) if total else 0
        return {
            "total": total, "blocked": blocked, "forwarded": forwarded,
            "nxdomain": nxdomain, "ratelimited": ratelimited,
            "clients": clients, "auto_blocks": auto_blocks,
            "block_pct": pct, "top_blocked": top,
        }
    except Exception as exc:
        log.error("digest_stats error: %s", exc)
        return {}


def _read_update_status() -> dict:
    import json
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


# ── Background loop ───────────────────────────────────────────────────────────

def _is_digest_day(freq: str, day_of_week: int, day_of_month: int) -> bool:
    """Check if today is the right day to send the digest based on frequency."""
    now = datetime.now()
    if freq == "weekly":
        return now.weekday() == day_of_week
    elif freq == "monthly":
        return now.day == day_of_month
    elif freq == "yearly":
        return now.month == 1 and now.day == day_of_month
    return False


async def run_notifier() -> None:
    global _last_block_check_ts, _last_digest_sent, _last_update_ts

    st = _read_update_status()
    _last_update_ts = st.get("last_updated", "")

    log.info("Notifier started")

    while True:
        await asyncio.sleep(60)

        ec = _cfg()
        if not ec.get("enabled"):
            continue

        # ── Security alerts (max 1 email per hour) ─────────────────────────
        if ec.get("notify_security", True):
            try:
                blocks = _new_blocks(_last_block_check_ts)
                _last_block_check_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                now_mono = time.monotonic()
                if blocks and (now_mono - _last_alert_sent) >= _ALERT_COOLDOWN:
                    _last_alert_sent = now_mono
                    count   = len(blocks)
                    subject = f"Security Alert — {count} client(s) auto-blocked"
                    await send_async(subject, _security_alert_plain(blocks), _security_alert_html(blocks))
                    log.info("Security alert sent for %d block(s)", count)
                elif blocks:
                    log.info("Security alert suppressed (cooldown) — %d new block(s)", len(blocks))
            except Exception as exc:
                log.error("Security alert failed: %s", exc)

        # ── Blocklist update notification ──────────────────────────────────
        if ec.get("notify_update", True):
            try:
                st = _read_update_status()
                ts = st.get("last_updated", "")
                if ts and ts != _last_update_ts:
                    _last_update_ts = ts
                    status_word = st.get("status", "unknown")
                    subject = f"Blocklist Update — {status_word}"
                    await send_async(subject, _update_plain(st), _update_html(st))
                    log.info("Update notification sent (status=%s)", status_word)
            except Exception as exc:
                log.error("Update notification failed: %s", exc)

        # ── Periodic digest (weekly / monthly / yearly) ────────────────────
        if ec.get("notify_digest", False):
            try:
                now        = datetime.now()
                today_str  = now.strftime("%Y-%m-%d")
                digest_hour = int(ec.get("digest_hour", ec.get("daily_hour", 8)))
                freq        = ec.get("digest_frequency", "weekly")
                dow         = int(ec.get("digest_day_of_week", 0))
                dom         = int(ec.get("digest_day_of_month", 1))
                days        = _FREQ_DAYS.get(freq, 7)

                if (today_str != _last_digest_sent
                        and now.hour >= digest_hour
                        and _is_digest_day(freq, dow, dom)):
                    _last_digest_sent = today_str
                    stats = _digest_stats(days)
                    if stats:
                        label   = freq.capitalize()
                        subject = f"{label} Digest"
                        await send_async(subject, _digest_plain(stats, freq, days), _digest_html(stats, freq, days))
                        log.info("%s digest sent (last %d days)", label, days)
            except Exception as exc:
                log.error("Digest failed: %s", exc)
