# ギター修理の AI 見積（monshin-app）

ギターやベースの持ち主が症状を入力すると、AI が質問をして、考えられる原因と料金の見積を出すアプリ。八幡平市スパルタキャンプ 2026 Python編の自主制作。

## 動かし方

```bash
cp .env.example .env
uv sync
uv run flask db upgrade
uv run flask run --debug
```

ブラウザーで http://localhost:8001 を開く。

## 確認

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
```

## 設計

- [要件定義](docs/spec/requirements.md)
- [画面一覧](docs/design/screens.md)
- [データベース設計](docs/design/database.md)
