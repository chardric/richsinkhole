from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import auth, db
from ..updater import DOMAIN_RE

bp = Blueprint("allowlist", __name__, url_prefix="/allowlist")


@bp.route("/", methods=["GET"])
@auth.login_required
def index():
    return render_template("allowlist.html", entries=db.list_allowlist())


@bp.route("/add", methods=["POST"])
@auth.login_required
def add():
    domain = request.form.get("domain", "").strip().lower().rstrip(".")
    note   = request.form.get("note", "").strip()[:200]
    if not domain:
        flash("Domain is required.", "error")
    elif not DOMAIN_RE.match(domain):
        flash(f"{domain!r} is not a valid domain.", "error")
    else:
        db.add_allow(domain, note)
        flash(f"Added {domain}. Refresh the blocklist to apply.", "ok")
    return redirect(url_for("allowlist.index"))


@bp.route("/remove", methods=["POST"])
@auth.login_required
def remove():
    domain = request.form.get("domain", "").strip().lower()
    if domain:
        db.remove_allow(domain)
        flash(f"Removed {domain}.", "ok")
    return redirect(url_for("allowlist.index"))
