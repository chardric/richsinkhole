from __future__ import annotations

from flask import Blueprint, render_template, request

from .. import auth, querylog

bp = Blueprint("logs", __name__, url_prefix="/logs")


@bp.route("/", methods=["GET"])
@auth.login_required
def index():
    try:
        limit = int(request.args.get("limit", "200"))
    except ValueError:
        limit = 200
    limit = max(20, min(limit, 1000))

    show = request.args.get("show", "all")  # all | blocked | allowed
    entries = querylog.parse_recent()
    if show == "blocked":
        filtered = [e for e in entries if e.blocked]
    elif show == "allowed":
        filtered = [e for e in entries if not e.blocked]
    else:
        filtered = entries

    summary = querylog.summarize(entries, top_n=10)
    recent  = list(reversed(filtered))[:limit]
    return render_template(
        "logs.html",
        recent=recent,
        summary=summary,
        show=show,
        limit=limit,
    )
