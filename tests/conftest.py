import pytest

from monshin import create_app
from monshin.extensions import db
from monshin.models import User

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


def _make_user(email):
    user = User(email=email)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def user(app):
    return _make_user("owner@example.com")


@pytest.fixture
def other_user(app):
    return _make_user("other@example.com")


@pytest.fixture
def login(client):
    def do_login(user):
        return client.post("/login", data={"email": user.email, "password": "password"})

    return do_login
