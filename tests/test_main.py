import pytest

from monshin import create_app


def test_top_page_returns_200(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "AI 見積を始める" in response.get_data(as_text=True)


def test_app_refuses_to_start_without_secret_key(monkeypatch):
    """本番で SECRET_KEY を設定し忘れたら、起動を止める"""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)

    with pytest.raises(RuntimeError):
        create_app()


def test_debug_mode_does_not_use_a_well_known_secret_key(monkeypatch):
    """開発用の設定が本番に残っても、だれでも知っている鍵では動かない"""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("FLASK_DEBUG", "1")

    first = create_app()
    second = create_app()

    assert len(first.config["SECRET_KEY"]) == 64
    assert first.config["SECRET_KEY"] != second.config["SECRET_KEY"]


def test_session_cookie_is_samesite_lax(app):
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_500_page_is_shown_in_japanese(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/boom")
    def boom():
        raise RuntimeError("テスト用のエラー")

    response = app.test_client().get("/boom")

    assert response.status_code == 500
    assert "エラーが起きました" in response.text


def test_theme_css_url_has_a_version(client):
    """CSS を変えたときに、ブラウザーが古い写しを使い続けないようにする"""
    text = client.get("/").get_data(as_text=True)

    assert "css/theme.css?v=" in text
    assert "css/theme.css?v=0" not in text


# --- 工房の連絡先


@pytest.mark.parametrize("path", ["/", "/login"])
def test_どの画面にも工房の連絡先と架空の注記がある(client, path):
    text = client.get(path).text

    assert "大更ギター工房" in text
    assert "〒028-7111 岩手県八幡平市大更25地割113番地" in text
    assert "info@example.com" in text
    assert "架空です" in text
