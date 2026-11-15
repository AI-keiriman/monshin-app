import pytest

from monshin import create_app
from monshin.extensions import db

# 本物の外部サービス（Claude API）は、テストでは呼ばない。
# AI の機能を作るときに、フェイクのクラスをここに足し、create_app() の設定で差し替える。


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()
