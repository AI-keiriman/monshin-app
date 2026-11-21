# ギター修理の AI 見積（monshin-app）

ギターやベースの持ち主が症状を入力すると、AI が質問をして、考えられる原因と料金の見積を出すアプリ。八幡平市スパルタキャンプ 2026 Python編の自主制作である。最終プレゼンのデモに使えればよい。実際の運用は想定しない。

## 技術

- Python 3.14、uv、Flask、Flask-SQLAlchemy（SQLAlchemy 2 の `Mapped` / `mapped_column`）、Flask-Migrate、Flask-Login、Flask-WTF、Jinja2、Pico CSS（CDN）
- データベースは、開発とテストは SQLite（`instance/`。テストはメモリ上）、本番は MySQL 8.0（`DATABASE_URL=mysql+pymysql://...?charset=utf8mb4`、ドライバーは PyMySQL）
- AI は Claude API（`anthropic` パッケージ）
- テストは pytest、整形と検査は Ruff

## 構成

`../marche-app` と同じ形にする。迷ったら、marche-app の同じ役割のファイルを読んで合わせる（読むだけ。変更しない）。

- `monshin/__init__.py` の `create_app(config=None)` がアプリを作る。拡張は `monshin/extensions.py`（db, migrate, login_manager, csrf）
- 画面は Blueprint ごとに `monshin/views/` に分ける（main = トップ、auth = 登録とログイン、consultations = 問診）。テンプレートは `monshin/templates/<blueprint名>/`
- モデルは `monshin/models.py`、フォームは `monshin/forms.py`（Flask-WTF）
- 外部サービスに触るコードは `monshin/services/` に閉じ込める（ai.py = Claude API）。views からは services の関数だけを呼ぶ
- AI のサービスは `create_app()` が `app.extensions["ai"]` に入れる。views は `current_app.extensions["ai"]` 経由で呼ぶ
- 料金表の初期データは `monshin/commands.py` の `flask seed` で入れる
- 診断の手引き（diagnosis_guides。症状ごとの確かめる点と見分け方）の初期データも、同じ `flask seed` で入れる。AI には、症状と一緒に全行を渡す
- テストは `tests/`。共通の fixture は `tests/conftest.py`（app、client、ユーザー、ログイン、フェイク AI）。フェイクは `create_app({"AI_SERVICE": FakeAI()})` のように設定で渡す

## このプロジェクトの決まり

- 文言は日本語。日付は「11月14日(土) 10:00」、金額は「1,200円」（3桁ごとのカンマ＋円）の形式
- 認可: 問診の画面はすべて `@login_required`。**他人の問診は、取得したあとに所有者を必ず確かめ、違えば 403 にする**。ロールは作らない
- フォームは Flask-WTF で作り、CSRF トークンを付ける
- 値を変える操作は、すべて POST にする
- 料金の金額は、**サーバー側で料金表（price_rules）から引く**。AI が返した金額や、フォームから来た金額は使わない
- テンプレートで `|safe` と `Markup()` を使わない。AI が作った文章も、自動エスケープのまま表示する
  - 例外：`monshin/__init__.py` のフィルター `br_sentences` だけは `Markup()` を使う。先に全体をエスケープしてから `<br>` を足すので、XSS にならない。`tests/test_sentence_breaks.py` で確かめている。ほかの場所では使わない
- SQL を文字列で組み立てない。SQLAlchemy の `select()` を使う
- SQLite でしか動かない書き方（SQLite 専用の SQL や関数。`strftime`、`PRAGMA` など）を使わない。本番の MySQL でも動く SQLAlchemy の書き方にする（文字列のカラムは `String(50)` のように長さを付ける）
- アップロードされた写真は、拡張子と中身（JPEG/PNG/WebP）とサイズ（5MB 以下）を確かめ、ファイル名はサーバーで付け直す
- **写真は `static/` に置かない。** 設定 `UPLOAD_FOLDER`（既定 `instance/uploads/`）に保存し、`GET /consultations/<id>/photo` からだけ返す。このビューは `@login_required` を付け、所有者を確かめ、違えば 403 にする。返すファイル名は DB の `image_filename` だけを使い、`send_from_directory` で返す
- テーブルを変えたら `uv run flask db migrate -m "..."` → `uv run flask db upgrade`。マイグレーションのファイルは読んでから適用する
- 機能を追加したら `tests/` に pytest のテストを追加し（正常系・権限なし・不正な入力）、`/check` が通ることを確認する

### AI 機能の決まり

- Claude API は `monshin/services/ai.py` の関数からだけ呼ぶ
- モデルは環境変数 `ANTHROPIC_MODEL`（既定 `claude-haiku-5-5`）。API キーは環境変数 `ANTHROPIC_API_KEY`
- AI を呼ぶのは、1回の問診につき2回だけ（質問を作る、結果を作る）。会話を何往復もさせない
- `max_tokens` は小さめにする（質問は 2048、結果は 2048。設定 `AI_MAX_TOKENS_QUESTIONS`、`AI_MAX_TOKENS_DIAGNOSIS`）。Claude Haiku 5.5 は、考える分（thinking）も `max_tokens` に数える。小さすぎると、返事が出る前に切れる。変えるときは、理由を説明してから変える。質問を 1024 から 2048 に上げた理由：選択肢を足した後、本番で返事が 1024 で切れた
- `output_config` の `effort` は `low` にする（考える量と費用を抑える）。返事の形は `output_config.format`（JSON スキーマ）で決める
- 1回の呼び出しで待つ時間は20秒、やり直しは1回まで（設定 `AI_TIMEOUT_SECONDS`、`AI_MAX_RETRIES`）。合計（40秒）を、本番の gunicorn の時間切れ（120秒）より短くする
- 質問を作るときは、先に原因の予想を3つ書かせる（`candidates`。画面には出さない）。その予想を見分ける質問を作らせる
- AI を使えるのは、ログインした人だけ。問診は1人1日5回まで（設定 `DAILY_CONSULTATION_LIMIT`、既定 5）
- 失敗は `AIError` にして、画面に「今は AI を使えません」と短く出す。画面を落とさない
- AI の返事は、決めた形（質問3つ。原因の候補と分類のコード）になっているかを確かめる。形が違えば `AIError` にする。分類のコードが料金表に無ければ `other` にする
- テストでは必ずフェイクに差し替え、本物の API を呼ばない。CI に API キーを登録しない

## コマンド

- コマンドは必ず `uv run` を付ける（`uv run flask run --debug`、`uv run pytest -q`、`uv run ruff check .`）。`pip` と `python` を直接使わない
- マイグレーション: `uv run flask db migrate -m "..."`、`uv run flask db upgrade`
- 料金表の初期データ: `uv run flask seed`
- 確認: `/check`
- 開発サーバーのポートは `.flaskenv` の `FLASK_RUN_PORT` で決める。marche-app（8000）と同時に動かせるように、8001 にする
- `migrations/` は Ruff の対象外（`pyproject.toml` の `[tool.ruff] extend-exclude`）
- パッケージの追加は `uv add <名前>`（開発用は `uv add --dev <名前>`）。追加する前に、パッケージ名と目的を説明する

## 作業の進め方

- 変更の前に、何をどのファイルに書くかを短く説明してから実装する
- 1回の指示で扱う範囲は1機能まで。大きい依頼は分割案を先に出す
- **設計書に書いていないことを、勝手に決めない。** 決まっていない点を見つけたら、実装する前に質問する
- 既存のファイルの書き方に合わせる（同じフォルダーのファイルを先に読む）
- `.env` を読まない。設定の項目は `.env.example` で確かめる。API キーやパスワードをコード、ログ、コミットに含めない
- 失敗したコマンドは、原因の推測と対処案を示してから再実行する

## 設計

- 要件定義: [docs/spec/requirements.md](docs/spec/requirements.md)
- 画面一覧: [docs/design/screens.md](docs/design/screens.md)
- データベース設計: [docs/design/database.md](docs/design/database.md)
- 用語: 問診（consultations。持ち主が症状を伝えてから結果が出るまでの1回分）、質問と答え（consultation_questions）、原因の候補（consultation_causes）、料金表（price_rules）、出口（choice。修理を依頼 `repair` / 買取査定 `sell` / そのまま使う `keep`。ボタンの名前は「修理依頼に進む」「ホームに戻る」「買取査定をする」）

### 画面と URL

- URL は screens.md のとおりにする。問診の画面は `/consultations/` の下に置く
- テンプレートの写真は `url_for("consultations.photo", ...)` を指す。`static` の URL を使わない
- 問診の状態は `asking`（質問に答える前） → `done`（結果あり）。状態と合わない URL を開いたときは、合う画面へ移す
- 問診を作る順番と、結果を作る順番は、screens.md の「順番」の節のとおりにする

### データ

- `instrument`、`status`、`choice` は文字列で保存し、Python 側は StrEnum（`Instrument`、`ConsultationStatus`、`Choice`）で比べる
- 金額は円の整数。料金の見積は、表示するたびに `price_rules` から引く
- 料金の表示は3通り。下限と上限がある →「16,000円〜90,000円」。下限だけ →「3,000円〜」。どちらも無い →「要見積」
- 今日の回数は、日本時間の 0:00 以降の問診を数える。0:00 の時刻は Python で作る

## デザイン

参考にしたのは、ギター工房のサイト（okita-guitar.jp）の雰囲気。写真が大きい。文字は明朝体。色は白と黒と茶色だけ。角は四角い。

- CSS は Pico CSS。色とフォントは `monshin/static/css/theme.css` の CSS 変数で変える。クラスは、なるべく足さない
- 色：背景は白（#ffffff）、文字は黒（#0a0a0a）、アクセントは茶色。ボタンとリンクは #702c00、見出しは #8a5f17。上と下の帯は黒。ほかの色は使わない
- フォント：Shippori Mincho（Google Fonts）。見出しは太さ 500、本文は 400
- 余白は広め。角は 0（四角）。丸くするのは、トップの「使い方」の写真だけ。影は使わない
- 見出し（h1、h2）は、中央にそろえる
- 配色は明るい方に固定する（`<html data-theme="light">`）
- static のファイルは、ブラウザーが7日間おぼえる（nginx の設定）。`theme.css` には、URL に版の番号が自動で付く。写真を差し替えるときは、ファイルの名前を変える
- 写真は `monshin/static/img/` に置く。トップの大きい写真は、作るときに暗くしてある（白い文字を読めるようにするため）
- グラデーション、絵文字、意味の無い画像、「ようこそ」の文は使わない
- 工房の写真（自分で撮ったもの）は、トップ以外で使う。ログインと会員登録は、左に縦長の写真、右に入力欄。問診の入力は、下の帯の背景に、作業台の横長の写真を幅いっぱいに置く（暗くしてあり、上に白い字を置く）
- 写真は、利用条件を確かめたフリー素材か、自分で撮ったものだけを使う。他社のロゴが写った写真は使わない

## やらないこと

範囲を広げない。頼まれても、先に「やらないことの一覧にある」と伝える。

- 音声の受け取り、保存、AI による読み取り（問診の入力の画面に、欄「音声・動画を追加（任意）」だけを出す。ファイルは選べるが、サーバーには送らない）
- 買い取りの査定と申し込み（結果の画面で「買取査定をする」を選ぶと、枠「買取査定」だけを出す）
- 修理の依頼の受け付けと送信（結果の画面で「修理依頼に進む」を選ぶと、枠「修理の依頼」だけを出す）
- 工房の側の画面（問診票の一覧、返信、見積）
- 修理の予約、決済、メールの送信
- AI との自由な会話（何往復もするチャット）
- パスワードの再設定、退会、プロフィールの編集
- 管理者の画面とロール
- 問診の削除と編集
- スマホ向けの作り込み（Pico CSS の標準のままにする）
- 料金の断り書き（「仮」「目安であり…」などの注意書き）
