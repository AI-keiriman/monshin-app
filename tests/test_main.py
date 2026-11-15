import pytest

from monshin import create_app


def test_top_page_returns_200(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "問診を始める" in response.get_data(as_text=True)


def test_app_refuses_to_start_without_secret_key(monkeypatch):
    """本番で SECRET_KEY を設定し忘れたら、起動を止める"""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)

    with pytest.raises(RuntimeError):
        create_app()
