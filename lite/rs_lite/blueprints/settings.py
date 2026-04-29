from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import auth, config, db, updater

bp = Blueprint("settings", __name__, url_prefix="/settings")


def _upstream_resolvers() -> list[str]:
    cfg = updater.load_sources_yml()
    val = cfg.get("upstream_resolvers")
    if isinstance(val, list) and val:
        return [str(v) for v in val]
    return ["1.1.1.1", "9.9.9.9"]  # the dnsmasq.d/rs-lite.conf default


@bp.route("/", methods=["GET"])
@auth.login_required
def index():
    return render_template(
        "settings.html",
        upstream_resolvers=_upstream_resolvers(),
        sources_yml=str(config.SOURCES_YML),
        state_db=str(config.STATE_DB),
        blocked_file=str(config.BLOCKED_HOSTS_FILE),
        dashboard_host=config.DASHBOARD_HOST,
        dashboard_port=config.DASHBOARD_PORT,
    )


@bp.route("/password", methods=["POST"])
@auth.login_required
def change_password():
    current = request.form.get("current",  "")
    new     = request.form.get("new",      "")
    confirm = request.form.get("confirm",  "")

    if not auth.verify_password(current):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("settings.index"))
    if new != confirm:
        flash("New passwords do not match.", "error")
        return redirect(url_for("settings.index"))
    try:
        auth.set_password(new)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.index"))

    # Force re-login: clear all session state, including this user's.
    auth.logout_user()
    flash("Password changed. Please log in again.", "ok")
    return redirect(url_for("auth.login"))
