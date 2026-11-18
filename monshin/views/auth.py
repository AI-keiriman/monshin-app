from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from monshin.extensions import db, login_manager
from monshin.forms import LoginForm, RegisterForm
from monshin.models import User

bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


def safe_next(target: str | None) -> str | None:
    """ログインの後の移動先。自サイトのパスだけを許し、外部サイトへは飛ばさない"""
    if not target or not target.startswith("/") or target.startswith("//"):
        return None
    # ブラウザーは、バックスラッシュを "/" と読み、タブや改行を取り除く。
    # そのため "/\evil.example" や "/<タブ>/evil.example" は、外部サイトへの移動になる
    if "\\" in target or any(ord(c) < 0x20 or ord(c) == 0x7F for c in target):
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    return target


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if db.session.scalar(db.select(User).filter_by(email=email)):
            form.email.errors.append("このメールアドレスは登録済みです")
            return render_template("auth/register.html", form=form), 422
        user = User(email=email)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("登録しました")
        return redirect(url_for("consultations.new"))
    status = 422 if form.is_submitted() else 200
    return render_template("auth/register.html", form=form), status


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            db.select(User).filter_by(email=form.email.data.strip().lower())
        )
        if user is None or not user.check_password(form.password.data):
            flash("メールアドレスかパスワードが違います")
            return render_template("auth/login.html", form=form), 422
        login_user(user)
        return redirect(
            safe_next(request.args.get("next")) or url_for("consultations.new")
        )
    status = 422 if form.is_submitted() else 200
    return render_template("auth/login.html", form=form), status


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("ログアウトしました")
    return redirect(url_for("main.index"))
