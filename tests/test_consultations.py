import io
from datetime import timedelta
from pathlib import Path

from monshin.extensions import db
from monshin.models import Consultation, ConsultationQuestion, now_jst
from monshin.services.ai import AIError

# 中身が本物の画像だと判定される、最小のバイト列
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def count(model) -> int:
    return db.session.scalar(db.select(db.func.count()).select_from(model))


def post_consultation(client, **data):
    data = {"instrument": "bass", "symptom": "トーンノブが効かない"} | data
    return client.post("/consultations/", data=data, content_type="multipart/form-data")


def uploaded_files(app) -> list[Path]:
    folder = Path(app.config["UPLOAD_FOLDER"])
    return sorted(folder.iterdir()) if folder.exists() else []


# --- 問診の入力の画面


def test_未ログインで問診の入力を開くとログイン画面へ(client):
    response = client.get("/consultations/new")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=")


def test_問診の入力の画面が出る(client, user, login):
    login(user)

    response = client.get("/consultations/new")

    assert response.status_code == 200
    assert "AI 見積を始める" in response.text
    assert "アコースティックギター" in response.text


def test_音声と動画の欄は選べるがサーバーには送らない(client, user, login):
    login(user)

    text = client.get("/consultations/new").text

    assert "音声・動画を追加（任意）" in text
    assert "準備中" not in text
    # name が無い欄は、ブラウザーが送らない（今は、欄だけ）
    assert '<input type="file" accept="audio/*,video/*">' in text


# --- 問診を作る


def test_問診を作ると質問が3つ保存される(client, user, login, fake_ai):
    login(user)

    response = post_consultation(client)

    consultation = db.session.scalar(db.select(Consultation))
    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}/questions"
    assert consultation.user_id == user.id
    assert consultation.instrument == "bass"
    assert consultation.symptom == "トーンノブが効かない"
    assert consultation.status == "asking"
    assert consultation.image_filename is None
    assert [q.position for q in consultation.questions] == [1, 2, 3]
    assert [q.question for q in consultation.questions] == fake_ai.questions
    # AI には、楽器の名前（日本語）と症状が渡る
    assert len(fake_ai.question_calls) == 1
    call = fake_ai.question_calls[0]
    assert call["instrument_label"] == "ベース"
    assert call["symptom"] == "トーンノブが効かない"
    assert call["image"] is None


def test_未ログインでは問診を作れない(client, fake_ai):
    response = post_consultation(client)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    assert count(Consultation) == 0
    assert fake_ai.question_calls == []


def test_症状が空だと問診を作れない(client, user, login, fake_ai):
    login(user)

    response = post_consultation(client, symptom="   ")

    assert response.status_code == 422
    assert "症状を入力してください" in response.text
    assert count(Consultation) == 0
    assert fake_ai.question_calls == []  # AI を呼ばない（費用がかからない）


def test_症状が長すぎると問診を作れない(client, user, login, fake_ai):
    login(user)

    response = post_consultation(client, symptom="あ" * 1001)

    assert response.status_code == 422
    assert "1,000文字以内" in response.text
    assert count(Consultation) == 0
    assert fake_ai.question_calls == []


def test_選択肢に無い楽器では問診を作れない(client, user, login, fake_ai):
    login(user)

    response = post_consultation(client, instrument="piano")

    assert response.status_code == 422
    assert count(Consultation) == 0
    assert fake_ai.question_calls == []


# --- 写真


def test_写真つきで問診を作れる(app, client, user, login, fake_ai):
    login(user)

    response = post_consultation(client, image=(io.BytesIO(PNG), "guitar.png"))

    consultation = db.session.scalar(db.select(Consultation))
    assert response.status_code == 302
    # ファイル名は、送られてきた名前ではなく、サーバーが付け直す
    assert consultation.image_filename.endswith(".png")
    assert "guitar" not in consultation.image_filename
    files = uploaded_files(app)
    assert [f.name for f in files] == [consultation.image_filename]
    assert files[0].read_bytes() == PNG
    # AI にも、写真の中身と種類が渡る
    assert fake_ai.question_calls[0]["image"] == (PNG, "image/png")


def test_拡張子を偽った写真は中身で判定する(app, client, user, login, fake_ai):
    login(user)

    # 名前は .png だが、中身は JPEG
    post_consultation(client, image=(io.BytesIO(JPEG), "photo.png"))

    consultation = db.session.scalar(db.select(Consultation))
    assert consultation.image_filename.endswith(".jpg")
    assert fake_ai.question_calls[0]["image"] == (JPEG, "image/jpeg")


def test_中身が画像でないファイルは受け付けない(app, client, user, login, fake_ai):
    login(user)

    response = post_consultation(
        client, image=(io.BytesIO(b"<script>alert(1)</script>"), "fake.png")
    )

    assert response.status_code == 422
    assert "JPEG・PNG・WebP の画像を選んでください" in response.text
    assert count(Consultation) == 0
    assert uploaded_files(app) == []
    assert fake_ai.question_calls == []


def test_許可していない拡張子のファイルは受け付けない(
    app, client, user, login, fake_ai
):
    login(user)

    response = post_consultation(client, image=(io.BytesIO(PNG), "photo.exe"))

    assert response.status_code == 422
    assert count(Consultation) == 0
    assert uploaded_files(app) == []
    assert fake_ai.question_calls == []


def test_大きすぎるリクエストは413で止める(app, client, user, login, fake_ai):
    login(user)
    too_big = PNG + b"\x00" * (7 * 1024 * 1024)

    response = post_consultation(client, image=(io.BytesIO(too_big), "big.png"))

    assert response.status_code == 413
    assert count(Consultation) == 0
    assert uploaded_files(app) == []
    assert fake_ai.question_calls == []


def test_音声のファイルを送っても保存しない(app, client, user, login, fake_ai):
    login(user)

    response = post_consultation(
        client, audio=(io.BytesIO(b"RIFF....WAVE"), "sound.wav")
    )

    # 問診は作られるが、音声はどこにも保存されず、AI にも渡らない
    assert response.status_code == 302
    assert count(Consultation) == 1
    assert uploaded_files(app) == []
    assert fake_ai.question_calls[0]["image"] is None


# --- 1日の上限


def test_1日の上限を超えると問診を始められない(
    client, user, login, fake_ai, make_consultation
):
    login(user)
    for _ in range(5):
        make_consultation(user)

    response = post_consultation(client)

    assert response.status_code == 429
    assert "上限に達しました" in response.text
    assert count(Consultation) == 5
    assert fake_ai.question_calls == []  # AI を呼ばない（費用がかからない）


def test_上限に達すると入力の画面のボタンが押せない(
    client, user, login, make_consultation
):
    login(user)
    for _ in range(5):
        make_consultation(user)

    text = client.get("/consultations/new").text

    assert "上限（1日5回）に達しました" in text
    assert '<button type="submit" disabled>' in text


def test_昨日の問診と他人の問診は上限に数えない(
    client, user, other_user, login, fake_ai, make_consultation
):
    login(user)
    yesterday = now_jst() - timedelta(days=1)
    for _ in range(5):
        make_consultation(user, created_at=yesterday)
        make_consultation(other_user)

    response = post_consultation(client)

    assert response.status_code == 302
    assert len(fake_ai.question_calls) == 1


# --- AI の失敗


def test_AIが失敗しても画面は落ちず何も保存しない(app, client, user, login, fake_ai):
    login(user)
    fake_ai.error = AIError("失敗")

    response = post_consultation(
        client, symptom="音が出ない", image=(io.BytesIO(PNG), "guitar.png")
    )

    assert response.status_code == 503
    assert "今は AI を使えません" in response.text
    assert "音が出ない" in response.text  # 入力した文は、欄に残る
    assert count(Consultation) == 0
    assert count(ConsultationQuestion) == 0
    assert uploaded_files(app) == []  # 写真も保存しない


def test_AIが失敗した問診は上限に数えない(client, user, login, fake_ai):
    login(user)
    fake_ai.error = AIError("失敗")
    for _ in range(6):
        post_consultation(client)
    fake_ai.error = None

    response = post_consultation(client)

    assert response.status_code == 302
    assert count(Consultation) == 1


# --- AI の質問に答える画面


def test_質問の画面に症状と質問が出る(client, user, login, fake_ai, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = client.get(f"/consultations/{consultation.id}/questions")

    assert response.status_code == 200
    assert "トーンノブが効かない" in response.text
    for question in fake_ai.questions:
        assert question in response.text


def test_AIが作った文は自動エスケープされる(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)
    consultation.questions[0].question = "<script>alert(1)</script>"
    db.session.commit()

    text = client.get(f"/consultations/{consultation.id}/questions").text

    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_他人の問診の質問の画面は見られない(
    client, user, other_user, login, make_consultation
):
    consultation = make_consultation(other_user)
    login(user)

    response = client.get(f"/consultations/{consultation.id}/questions")

    assert response.status_code == 403
    assert "トーンノブが効かない" not in response.text


def test_存在しない問診は404(client, user, login):
    login(user)

    assert client.get("/consultations/999/questions").status_code == 404


def test_未ログインで質問の画面を開くとログイン画面へ(client, user, make_consultation):
    consultation = make_consultation(user)

    response = client.get(f"/consultations/{consultation.id}/questions")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=")


# --- 答えを保存する


def answer_data(**overrides):
    return {
        "answer_1": "変わりません",
        "answer_2": "出ます",
        "answer_3": "動きます",
    } | (overrides)


def test_答えを保存できる(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = client.post(
        f"/consultations/{consultation.id}/answers", data=answer_data()
    )

    assert response.status_code == 302
    assert [q.answer for q in consultation.questions] == [
        "変わりません",
        "出ます",
        "動きます",
    ]


def test_答えが1つでも空だと保存しない(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = client.post(
        f"/consultations/{consultation.id}/answers", data=answer_data(answer_2="  ")
    )

    assert response.status_code == 422
    assert "答えを入力してください" in response.text
    assert [q.answer for q in consultation.questions] == [None, None, None]


def test_答えが長すぎると保存しない(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = client.post(
        f"/consultations/{consultation.id}/answers",
        data=answer_data(answer_3="あ" * 501),
    )

    assert response.status_code == 422
    assert [q.answer for q in consultation.questions] == [None, None, None]


def test_他人の問診には答えられない(client, user, other_user, login, make_consultation):
    consultation = make_consultation(other_user)
    login(user)

    response = client.post(
        f"/consultations/{consultation.id}/answers", data=answer_data()
    )

    assert response.status_code == 403
    assert [q.answer for q in consultation.questions] == [None, None, None]


def test_答えはGETでは保存できない(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = client.get(f"/consultations/{consultation.id}/answers")

    assert response.status_code == 405


# --- 写真を返す URL


def create_with_photo(client) -> Consultation:
    post_consultation(client, image=(io.BytesIO(PNG), "guitar.png"))
    return db.session.scalar(db.select(Consultation))


def test_本人は問診の写真を見られる(client, user, login):
    login(user)
    consultation = create_with_photo(client)

    response = client.get(f"/consultations/{consultation.id}/photo")

    assert response.status_code == 200
    assert response.data == PNG
    assert response.mimetype == "image/png"


def test_他人の問診の写真は見られない(client, user, other_user, login):
    login(other_user)
    consultation = create_with_photo(client)
    client.post("/logout")
    login(user)

    response = client.get(f"/consultations/{consultation.id}/photo")

    assert response.status_code == 403
    assert response.data != PNG


def test_未ログインで写真のURLを開くとログイン画面へ(client, user, login):
    login(user)
    consultation = create_with_photo(client)
    client.post("/logout")

    response = client.get(f"/consultations/{consultation.id}/photo")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=")


def test_写真が無い問診の写真のURLは404(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    assert client.get(f"/consultations/{consultation.id}/photo").status_code == 404


def test_写真は公開のフォルダーに置かれない(app, client, user, login):
    login(user)
    consultation = create_with_photo(client)

    # static の URL からは取れない
    response = client.get(f"/static/uploads/{consultation.image_filename}")

    assert response.status_code == 404
    assert Path(app.static_folder) not in Path(app.config["UPLOAD_FOLDER"]).parents


# --- レビューで足したテスト


def test_5MBを超える写真は422で止める(app, client, user, login, fake_ai):
    login(user)
    over_limit = PNG + b"\x00" * (5 * 1024 * 1024 + 1)

    response = post_consultation(client, image=(io.BytesIO(over_limit), "big.png"))

    assert response.status_code == 422
    assert "写真は5MB 以下にしてください" in response.text
    assert count(Consultation) == 0
    assert uploaded_files(app) == []
    assert fake_ai.question_calls == []


def test_上限は日本時間の0時で区切る(client, user, login, fake_ai, make_consultation):
    login(user)
    midnight = now_jst().replace(hour=0, minute=0, second=0, microsecond=0)

    # 昨日の 23:59:59 の問診は、今日の回数に数えない
    for _ in range(5):
        make_consultation(user, created_at=midnight - timedelta(seconds=1))
    assert post_consultation(client).status_code == 302

    # 今日の 0:00:00 の問診は、今日の回数に数える（上の1回と合わせて5回）
    for _ in range(4):
        make_consultation(user, created_at=midnight)
    assert post_consultation(client).status_code == 429


def test_送信のボタンは2回押せない印が付く(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    assert "data-once" in client.get("/consultations/new").text
    assert "data-once" in client.get(f"/consultations/{consultation.id}/questions").text


# --- 楽器の情報（メーカー、機種名、使用年数。どれも任意）

ANSWERS = {"answer_1": "変わりません", "answer_2": "出ます", "answer_3": "動きます"}


def test_楽器の情報を入れると保存されAIにも渡る(client, user, login, fake_ai):
    login(user)

    response = post_consultation(
        client, maker=" 見本楽器 ", model_name="モデルA", years_used="10"
    )

    consultation = db.session.scalar(db.select(Consultation))
    assert response.status_code == 302
    assert consultation.maker == "見本楽器"  # 前後の空白は取る
    assert consultation.model_name == "モデルA"
    assert consultation.years_used == 10
    # 症状の文は、そのまま保存する。AI には、楽器の情報を後ろに添えて渡す
    assert consultation.symptom == "トーンノブが効かない"
    sent = fake_ai.question_calls[0]["symptom"]
    assert sent.startswith("トーンノブが効かない")
    assert "メーカー：見本楽器" in sent
    assert "機種名：モデルA" in sent
    assert "使用年数：10年" in sent

    # 質問の画面にも出る。診断のときも、AI に渡る
    assert "使用年数：10年" in client.get(response.headers["Location"]).text
    client.post(f"/consultations/{consultation.id}/answers", data=ANSWERS)
    assert "メーカー：見本楽器" in fake_ai.diagnose_calls[0]["symptom"]
    assert "機種名：モデルA" in client.get(f"/consultations/{consultation.id}").text


def test_楽器の情報は空のままでも問診を始められる(client, user, login, fake_ai):
    login(user)

    response = post_consultation(client, maker="", model_name="", years_used="")

    consultation = db.session.scalar(db.select(Consultation))
    assert response.status_code == 302
    assert consultation.maker is None
    assert consultation.model_name is None
    assert consultation.years_used is None
    # 情報が無いときは、症状の文だけを AI に渡す
    assert fake_ai.question_calls[0]["symptom"] == "トーンノブが効かない"
    assert "メーカー" not in client.get(response.headers["Location"]).text


def test_使用年数が0年でも保存される(client, user, login, fake_ai):
    login(user)

    post_consultation(client, years_used="0")

    assert db.session.scalar(db.select(Consultation)).years_used == 0
    assert "使用年数：0年" in fake_ai.question_calls[0]["symptom"]


def test_使用年数が数字でないときは問診を作らない(client, user, login, fake_ai):
    login(user)

    for value in ("十年", "-1", "101", "1.5", "0100", "1" * 5000):
        response = post_consultation(client, years_used=value)
        assert response.status_code == 422
        assert "0〜100 の数字で入力してください" in response.text

    assert count(Consultation) == 0
    assert fake_ai.question_calls == []


def test_長すぎるメーカーと機種名では問診を作らない(client, user, login, fake_ai):
    login(user)

    response = post_consultation(client, maker="あ" * 51)
    assert response.status_code == 422
    assert "メーカーは50文字以内" in response.text
    response = post_consultation(client, model_name="あ" * 51)
    assert response.status_code == 422
    assert "機種名は50文字以内" in response.text

    assert count(Consultation) == 0
    assert fake_ai.question_calls == []
