# Single-user password auth for the Lite dashboard.
# bcrypt-hashed password stored in state.db settings table.
#
# Developed by: Richard R. Ayuyang, PhD
# Copyright (c) 2026 DownStreamTech

import functools
import secrets

import bcrypt
from flask import current_app, redirect, request, session, url_for

from . import db

_PWD_KEY        = "password_hash"
_SECRET_KEY_KEY = "flask_secret"


def get_or_create_secret() -> bytes:
    raw = db.get_setting(_SECRET_KEY_KEY, "")
    if not raw:
        raw = secrets.token_hex(32)
        db.set_setting(_SECRET_KEY_KEY, raw)
    return raw.encode()


def password_is_set() -> bool:
    return bool(db.get_setting(_PWD_KEY, ""))


def set_password(plain: str) -> None:
    if len(plain) < 8:
        raise ValueError("Password must be at least 8 characters.")
    h = bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=10))
    db.set_setting(_PWD_KEY, h.decode())


def verify_password(plain: str) -> bool:
    stored = db.get_setting(_PWD_KEY, "")
    if not stored:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), stored.encode())
    except ValueError:
        return False


def login_user() -> None:
    session.clear()
    session["uid"] = "admin"
    session.permanent = True


def logout_user() -> None:
    session.clear()


def current_user() -> str | None:
    return session.get("uid")


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper
