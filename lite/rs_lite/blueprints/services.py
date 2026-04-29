from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import auth, db, services_data

bp = Blueprint("services", __name__, url_prefix="/services")


def _grouped() -> list[dict]:
    blocked = db.blocked_service_ids()
    by_group: dict[str, list[dict]] = {g["id"]: [] for g in services_data.GROUPS}
    for svc in services_data.SERVICES:
        gid = svc.get("group", "")
        if gid not in by_group:
            continue
        by_group[gid].append({
            "id":      svc["id"],
            "name":    svc["name"],
            "domains": svc.get("domains", []),
            "blocked": svc["id"] in blocked,
        })
    return [
        {"id": g["id"], "name": g["name"], "entries": by_group[g["id"]]}
        for g in services_data.GROUPS if by_group[g["id"]]
    ]


@bp.route("/", methods=["GET"])
@auth.login_required
def index():
    return render_template("services.html", groups=_grouped())


@bp.route("/toggle", methods=["POST"])
@auth.login_required
def toggle():
    sid = request.form.get("service_id", "").strip()
    action = request.form.get("action", "")
    if not sid:
        flash("Missing service id.", "error")
        return redirect(url_for("services.index"))
    if not any(s["id"] == sid for s in services_data.SERVICES):
        flash(f"Unknown service {sid!r}.", "error")
        return redirect(url_for("services.index"))
    if action == "block":
        db.block_service(sid)
        flash(f"Blocking {sid}. Refresh the blocklist to apply.", "ok")
    elif action == "unblock":
        db.unblock_service(sid)
        flash(f"Unblocked {sid}. Refresh the blocklist to apply.", "ok")
    else:
        flash("Invalid action.", "error")
    return redirect(url_for("services.index"))
