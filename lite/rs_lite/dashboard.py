# Flask app factory for the Lite dashboard.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

from __future__ import annotations

from datetime import timedelta

from flask import Flask, redirect, url_for

from . import auth, config, db
from .blueprints import (
    allowlist as bp_allowlist,
    auth as bp_auth,
    blocklist as bp_blocklist,
    logs as bp_logs,
    services as bp_services,
    settings as bp_settings,
    status as bp_status,
)


def create_app() -> Flask:
    db.init_db()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = auth.get_or_create_secret()
    app.permanent_session_lifetime = timedelta(hours=config.SESSION_LIFETIME_HOURS)
    app.config.update(
        SESSION_COOKIE_NAME=config.SESSION_COOKIE_NAME,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,  # LAN-only, plain HTTP
        MAX_CONTENT_LENGTH=64 * 1024,  # forms only — small bodies
    )

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        return resp

    app.register_blueprint(bp_auth.bp)
    app.register_blueprint(bp_status.bp)
    app.register_blueprint(bp_allowlist.bp)
    app.register_blueprint(bp_blocklist.bp)
    app.register_blueprint(bp_services.bp)
    app.register_blueprint(bp_logs.bp)
    app.register_blueprint(bp_settings.bp)

    @app.route("/")
    def _root():
        return redirect(url_for("status.index"))

    return app


# WSGI entry point used by gunicorn.
app = create_app()
