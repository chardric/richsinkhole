import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, render_template

from .. import auth, config, db, querylog

bp = Blueprint("status", __name__)

# Locations checked in _service_active. dbus/polkit aren't running on
# minimal DietPi images, so `systemctl is-active` fails for non-root users.
# We therefore check liveness directly:
#   * dnsmasq         — pidfile + /proc/<pid> exists
#   * timer units     — enabled symlink in timers.target.wants/
_DNSMASQ_PIDFILE = Path("/run/dnsmasq/dnsmasq.pid")
_TIMERS_WANTS    = Path("/etc/systemd/system/timers.target.wants")


def _read_meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":", 1)
                if len(parts) != 2:
                    continue
                k = parts[0].strip()
                v = parts[1].strip().split()[0]
                try:
                    out[k] = int(v)
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def _pid_alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def _service_active(name: str) -> str:
    """Return 'active' / 'inactive' / 'unknown' without dbus or sudo."""
    if name == "dnsmasq":
        try:
            pid = int(_DNSMASQ_PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return "inactive"
        return "active" if _pid_alive(pid) else "inactive"

    if name.endswith(".timer"):
        # systemd creates this symlink on `systemctl enable`.
        return "active" if (_TIMERS_WANTS / name).is_symlink() else "inactive"

    return "unknown"


def _hosts_count(p: Path) -> int:
    if not p.exists():
        return 0
    n = 0
    with open(p, "rb") as f:
        for line in f:
            if line and not line.startswith(b"#"):
                n += 1
    return n


@bp.route("/status")
@auth.login_required
def index():
    mem = _read_meminfo()
    total = mem.get("MemTotal", 0)
    avail = mem.get("MemAvailable", 0)
    mem_used_mb  = (total - avail) // 1024 if total else 0
    mem_total_mb = total // 1024 if total else 0

    du = shutil.disk_usage("/")
    disk_used_pct = round(du.used / du.total * 100, 1) if du.total else 0

    last_refresh   = db.get_setting("last_refresh_at",    "never")
    last_count     = db.get_setting("last_refresh_count", "0")
    last_feeds     = db.get_setting("last_refresh_feeds", "0/0")

    summary = querylog.summarize(querylog.parse_recent(), top_n=5)

    ctx = {
        "now":            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dnsmasq":        _service_active("dnsmasq"),
        "updater_timer":  _service_active("rs-lite-updater.timer"),
        "mem_used_mb":    mem_used_mb,
        "mem_total_mb":   mem_total_mb,
        "disk_used_pct":  disk_used_pct,
        "last_refresh":   last_refresh,
        "last_count":     last_count,
        "last_feeds":     last_feeds,
        "blocked_count":  _hosts_count(config.BLOCKED_HOSTS_FILE),
        "queries_total":  summary["total"],
        "queries_blocked": summary["total_blocked"],
        "top_blocked":    summary["top_blocked"],
        "top_clients":    summary["top_clients"],
    }
    return render_template("status.html", **ctx)
