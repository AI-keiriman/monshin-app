import logging
import os
import re
import secrets
from pathlib import Path

from flask import Flask, render_template
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from monshin.extensions import csrf, db, login_manager, migrate
from monshin.services import ai

# 「。」の後に文が続くところ。文の終わりと、かっこの中の終わりは除く
SENTENCE_BREAK = re.compile(r"。(?=[^）」\s])")


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    # 本番は nginx の後ろで動かす。nginx が付けたヘッダーから、元の IP と https を読み取る
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or None,
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///monshin.sqlite"
        ),
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        # ほかのサイトからの POST には、ログインの Cookie を付けない
        SESSION_COOKIE_SAMESITE="Lax",
        # AI のモデル。既定は安くて速い Haiku
        ANTHROPIC_MODEL=os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-5-5",
        # テストではフェイクを渡す。None なら本物の services/ai.py を使う
        AI_SERVICE=None,
        # 返事の長さの上限。考える分（thinking）もここに数えられるので、余裕を持たせる
        AI_MAX_TOKENS_QUESTIONS=1024,
        AI_MAX_TOKENS_DIAGNOSIS=2048,
        # 1回の呼び出しで待つ秒数と、やり直しの回数。
        # 質問の作成は、原因の予想も書くので10秒ほどかかることがある。
        # 合計（20秒×2回）は、本番の gunicorn の時間切れ（120秒）より短い
        AI_TIMEOUT_SECONDS=20.0,
        AI_MAX_RETRIES=1,
        # 1人が1日に始められる問診の数
        DAILY_CONSULTATION_LIMIT=5,
        # 写真は、公開のフォルダー（static/）の外に置く
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER")
        or os.path.join(app.instance_path, "uploads"),
        # 写真は5MB まで（フォームで確かめる）。それより大きく外れたリクエストは、読み込む前に 413 で止める
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    )
    if config is not None:
        app.config.update(config)
    if not app.config["SECRET_KEY"]:
        if not (app.debug or app.testing):
            # 本番で SECRET_KEY を設定し忘れると、セッションを偽造される。起動を止めて気づかせる
            raise RuntimeError(
                "SECRET_KEY を .env（本番は EnvironmentFile）に設定してください"
            )
        # 開発とテストでは、起動のたびに乱数の鍵を作る。
        # だれでも知っている固定の鍵は使わない（本番に FLASK_DEBUG=1 が残っても、偽造されない）
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    db.init_app(app)
    # 外部 API はここで差し替えられるようにする（テストではフェイクを渡す）
    app.extensions["ai"] = app.config["AI_SERVICE"] or ai
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "ログインしてください"

    # マイグレーションがテーブルを見つけられるように、モデルを読み込む
    from monshin import models  # noqa: F401
    from monshin.views import auth, consultations, main

    for module in (main, auth, consultations):
        app.register_blueprint(module.bp)

    from monshin import commands

    commands.init_app(app)

    # nginx は static のファイルを、ブラウザーに7日間おぼえさせる。
    # CSS を変えたのに古い見た目のままにならないように、URL に版の番号（ファイルの更新時刻）を付ける
    theme_css = Path(app.static_folder) / "css" / "theme.css"
    asset_version = int(theme_css.stat().st_mtime) if theme_css.exists() else 0

    @app.context_processor
    def inject_asset_version():
        return {"asset_version": asset_version}

    @app.template_filter("br_sentences")
    def br_sentences(value) -> Markup:
        """「。」の後に文が続くところで改行する。先にエスケープしてから <br> を足す"""
        return Markup(SENTENCE_BREAK.sub("。<br>", str(escape(value))))

    @app.template_filter("jp_datetime")
    def jp_datetime(value) -> str:
        """「11月14日(土) 10:00」の形にする"""
        weekday = "月火水木金土日"[value.weekday()]
        return f"{value.month}月{value.day}日({weekday}) {value:%H:%M}"

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template("errors/413.html"), 413

    @app.errorhandler(422)
    def unprocessable(error):
        return render_template("errors/422.html"), 422

    @app.errorhandler(500)
    def server_error(error):
        # 途中まで進んだ DB の変更を取り消してから、画面を出す
        db.session.rollback()
        return render_template("errors/500.html"), 500

    logging.basicConfig(level=logging.INFO)
    return app
