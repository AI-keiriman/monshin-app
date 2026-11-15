import logging
import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from monshin.extensions import csrf, db, migrate


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    # 本番は nginx の後ろで動かす。nginx が付けたヘッダーから、元の IP と https を読み取る
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or "dev",
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///monshin.sqlite"
        ),
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
    )
    if config is not None:
        app.config.update(config)
    if app.config["SECRET_KEY"] == "dev" and not (app.debug or app.testing):
        # 本番で SECRET_KEY を設定し忘れると、セッションを偽造される。起動を止めて気づかせる
        raise RuntimeError(
            "SECRET_KEY を .env（本番は EnvironmentFile）に設定してください"
        )

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    # login_manager は、ログインの機能を作るときに init_app する（extensions.py に用意してある）

    from monshin.views import main

    app.register_blueprint(main.bp)

    logging.basicConfig(level=logging.INFO)
    return app
