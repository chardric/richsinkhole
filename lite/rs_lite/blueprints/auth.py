from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import auth

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not auth.password_is_set():
        return redirect(url_for("auth.first_setup"))
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if auth.verify_password(pwd):
            auth.login_user()
            target = request.args.get("next") or url_for("status.index")
            return redirect(target)
        flash("Wrong password.", "error")
    return render_template("login.html")


@bp.route("/setup", methods=["GET", "POST"])
def first_setup():
    if auth.password_is_set():
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        pwd  = request.form.get("password", "")
        conf = request.form.get("confirm",  "")
        if pwd != conf:
            flash("Passwords do not match.", "error")
        else:
            try:
                auth.set_password(pwd)
            except ValueError as exc:
                flash(str(exc), "error")
            else:
                auth.login_user()
                return redirect(url_for("status.index"))
    return render_template("setup.html")


@bp.route("/logout", methods=["POST"])
def logout():
    auth.logout_user()
    return redirect(url_for("auth.login"))
