from __future__ import annotations

import threading
from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import auth, config, db, updater

bp = Blueprint("blocklist", __name__, url_prefix="/blocklist")

# Single in-process refresh guard. Only one worker so a Lock is enough.
_refresh_lock = threading.Lock()
_refresh_running = False


def _is_running() -> bool:
    return _refresh_running


def _do_refresh() -> None:
    global _refresh_running
    if not _refresh_lock.acquire(blocking=False):
        return
    _refresh_running = True
    try:
        updater.run_once()
    except Exception:
        # run_once already logs; surface a setting so the dashboard can show it.
        db.set_setting(
            "last_refresh_error",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    finally:
        _refresh_running = False
        _refresh_lock.release()


@bp.route("/", methods=["GET"])
@auth.login_required
def index():
    cfg = updater.load_sources_yml()
    sources = updater.resolve_sources(cfg)
    ctx = {
        "sources":          sources,
        "last_refresh":     db.get_setting("last_refresh_at",    "never"),
        "last_count":       db.get_setting("last_refresh_count", "0"),
        "last_feeds":       db.get_setting("last_refresh_feeds", "0/0"),
        "last_secs":        db.get_setting("last_refresh_secs",  "0"),
        "last_error":       db.get_setting("last_refresh_error", ""),
        "running":          _is_running(),
        "blocked_file":     str(config.BLOCKED_HOSTS_FILE),
    }
    return render_template("blocklist.html", **ctx)


@bp.route("/refresh", methods=["POST"])
@auth.login_required
def refresh():
    if _is_running():
        flash("A refresh is already in progress.", "error")
        return redirect(url_for("blocklist.index"))
    t = threading.Thread(target=_do_refresh, name="rs-lite-refresh", daemon=True)
    t.start()
    flash("Refresh started — this can take a minute on the Pi Zero.", "ok")
    return redirect(url_for("blocklist.index"))
