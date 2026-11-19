import re

from monshin import create_app
from monshin.extensions import db
from monshin.models import User


def register(client, email="new@example.com", password="password123", name="新しい人"):
    return client.post(
        "/register", data={"name": name, "email": email, "password": password}
    )


def test_登録できる(client):
    response = register(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/consultations/new"
    assert (
        'action="/logout"' in client.get("/").text
    )  # 登録の後は、ログインした状態になる
    user = db.session.scalar(db.select(User).filter_by(email="new@example.com"))
    assert user is not None
    assert user.password_hash != "password123"  # パスワードはハッシュで保存する


def test_メールアドレスは小文字にそろえて保存する(client):
    register(client, email="  New@Example.COM ")

    assert db.session.scalar(db.select(User).filter_by(email="new@example.com"))


def test_同じメールアドレスでは登録できない(client, user):
    response = register(client, email=user.email)

    assert response.status_code == 422
    assert "登録済み" in response.text
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 1


def test_短いパスワードでは登録できない(client):
    response = register(client, password="short")

    assert response.status_code == 422
    assert "8文字以上" in response.text
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0


def test_メールアドレスの形でないと登録できない(client):
    response = register(client, email="not-an-email")

    assert response.status_code == 422
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0


def test_ログインとログアウトができる(client, user, login):
    response = login(user)
    assert response.status_code == 302
    assert 'action="/logout"' in client.get("/").text

    response = client.post("/logout")
    assert response.status_code == 302
    assert 'action="/logout"' not in client.get("/").text


def test_パスワードが違うとログインできない(client, user):
    response = client.post(
        "/login", data={"email": user.email, "password": "wrong-password"}
    )

    assert response.status_code == 422
    assert "メールアドレスかパスワードが違います" in response.text
    assert 'action="/logout"' not in client.get("/").text


def test_登録していないメールアドレスではログインできない(client):
    response = client.post(
        "/login", data={"email": "nobody@example.com", "password": "password"}
    )

    assert response.status_code == 422
    assert "メールアドレスかパスワードが違います" in response.text


def test_ログイン後のnextに外部URLは使えない(client, user):
    for target in (
        "https://evil.example.com/",
        "//evil.example.com/",
        # ブラウザーは、バックスラッシュ（%5C）を "/" と読む
        "/%5Cevil.example.com/",
        # ブラウザーは、タブと改行を取り除く
        "/%09/evil.example.com/",
        "/%0A/evil.example.com/",
    ):
        response = client.post(
            f"/login?next={target}",
            data={"email": user.email, "password": "password"},
        )
        assert response.headers["Location"] == "/consultations/new"
        client.post("/logout")


def test_nextつきでログインすると元の画面へ戻る(client, user):
    response = client.post(
        "/login?next=/register",
        data={"email": user.email, "password": "password"},
    )

    assert response.headers["Location"] == "/register"


def test_ログアウトはGETではできない(client, user, login):
    login(user)

    response = client.get("/logout")

    assert response.status_code == 405
    assert 'action="/logout"' in client.get("/").text


def test_未ログインでログアウトするとログイン画面へ(client):
    response = client.post("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_ログイン中は登録とログインの画面からトップへ移る(client, user, login):
    login(user)

    assert client.get("/login").headers["Location"] == "/"
    assert client.get("/register").headers["Location"] == "/"


def test_CSRFトークンが無いPOSTは受け付けない():
    """CSRF の保護を有効にしたアプリで確かめる（ふだんのテストでは無効にしている）"""
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        client = app.test_client()

        response = client.post(
            "/register", data={"email": "a@example.com", "password": "password123"}
        )
        assert response.status_code == 400
        assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0

        # 画面のフォームに入っているトークンを付ければ通る
        page = client.get("/register").text
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page).group(1)
        response = client.post(
            "/register",
            data={
                "name": "テスト",
                "email": "a@example.com",
                "password": "password123",
                "csrf_token": token,
            },
        )
        assert response.status_code == 302
        db.session.remove()


def test_長すぎるパスワードでは登録もログインもできない(client, user):
    too_long = "a" * 129

    assert register(client, password=too_long).status_code == 422
    response = client.post("/login", data={"email": user.email, "password": too_long})
    assert response.status_code == 422
    assert "128文字以内" in response.text


# --- アカウント名


def test_登録するとアカウント名が保存され画面の上に出る(client):
    register(client, name="  ギター好き  ")

    user = db.session.scalar(db.select(User).filter_by(email="new@example.com"))
    assert user.name == "ギター好き"  # 前後の空白は取る
    text = client.get("/").text
    assert "ギター好き" in text
    assert "new@example.com" not in text  # メールアドレスは、画面に出さない


def test_アカウント名が無いと登録できない(client):
    response = register(client, name="")

    assert response.status_code == 422
    assert "アカウント名を入力してください" in response.text
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0


def test_長すぎるアカウント名では登録できない(client):
    response = register(client, name="あ" * 31)

    assert response.status_code == 422
    assert "30文字以内" in response.text


def test_アカウント名が無い人でもメールアドレスは画面に出ない(client, user, login):
    # user は、アカウント名の欄ができる前に登録した人と同じ（名前が空）
    login(user)

    text = client.get("/").text
    assert 'action="/logout"' in text
    assert user.email not in text


def test_アカウント名はHTMLとして解釈されない(client):
    register(client, name="<b>x</b>")

    text = client.get("/").text
    assert "<b>x</b>" not in text
    assert "&lt;b&gt;x&lt;/b&gt;" in text
