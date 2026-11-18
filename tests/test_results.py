import io

import pytest

from monshin.extensions import db
from monshin.models import Consultation, ConsultationCause, PriceRule
from monshin.services.ai import AIError, Cause, Diagnosis

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ANSWERS = {"answer_1": "変わりません", "answer_2": "出ます", "answer_3": "動きます"}


def count(model) -> int:
    return db.session.scalar(db.select(db.func.count()).select_from(model))


def post_answers(client, consultation, **overrides):
    return client.post(
        f"/consultations/{consultation.id}/answers", data=ANSWERS | overrides
    )


# --- 答えを送ると、診断の結果ができる


def test_答えを送ると結果が保存される(client, user, login, fake_ai, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = post_answers(client, consultation)

    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}"
    assert consultation.status == "done"
    assert consultation.completed_at is not None
    assert consultation.price_rule.code == "pot"
    assert [(c.position, c.name) for c in consultation.causes] == [
        (1, "ポットの故障"),
        (2, "配線の接触不良"),
    ]


def test_AIには症状と答えと料金表の分類が渡る(
    client, user, login, fake_ai, make_consultation
):
    login(user)
    consultation = make_consultation(user)

    post_answers(client, consultation)

    call = fake_ai.diagnose_calls[0]
    assert call["instrument_label"] == "ベース"
    assert call["symptom"] == "トーンノブが効かない"
    assert call["answers"] == list(zip(fake_ai.questions, ANSWERS.values()))
    assert [code for code, _, _ in call["categories"]] == [
        "pot",
        "fret",
        "neck_crack",
        "other",
    ]
    assert call["image"] is None


def test_写真つきの問診では診断にも写真が渡る(client, user, login, fake_ai):
    login(user)
    client.post(
        "/consultations/",
        data={
            "instrument": "bass",
            "symptom": "音が出ない",
            "image": (io.BytesIO(PNG), "guitar.png"),
        },
        content_type="multipart/form-data",
    )
    consultation = db.session.scalar(db.select(Consultation))

    post_answers(client, consultation)

    assert fake_ai.diagnose_calls[0]["image"] == (PNG, "image/png")


def test_AIが料金表に無い分類を返したらその他にする(
    client, user, login, fake_ai, make_consultation
):
    login(user)
    consultation = make_consultation(user)
    fake_ai.diagnosis = Diagnosis(
        causes=[Cause("不明", "判断できません。")], category_code="no_such_code"
    )

    post_answers(client, consultation)

    assert consultation.price_rule.code == "other"


def test_AIが失敗しても答えは保存され画面は落ちない(
    client, user, login, fake_ai, make_consultation
):
    login(user)
    consultation = make_consultation(user)
    fake_ai.error = AIError("失敗")

    response = post_answers(client, consultation)

    assert response.status_code == 503
    assert "今は AI を使えません" in response.text
    assert "変わりません" in response.text  # 答えは、欄に残る
    assert [q.answer for q in consultation.questions] == list(ANSWERS.values())
    assert consultation.status == "asking"
    assert count(ConsultationCause) == 0


def test_AIが失敗した後にもう一度送るとやり直せる(
    client, user, login, fake_ai, make_consultation
):
    login(user)
    consultation = make_consultation(user)
    fake_ai.error = AIError("失敗")
    post_answers(client, consultation)
    fake_ai.error = None

    response = post_answers(client, consultation)

    assert response.status_code == 302
    assert consultation.status == "done"
    assert len(consultation.causes) == 2


def test_結果がある問診に答えを送り直してもAIを呼ばない(
    client, user, fake_ai, make_done_consultation
):
    consultation = make_done_consultation(user)

    response = post_answers(client, consultation, answer_1="別の答え")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}"
    assert len(fake_ai.diagnose_calls) == 1  # 最初の1回だけ
    assert consultation.questions[0].answer == "変わりません"
    assert len(consultation.causes) == 2


def test_料金表が空だと結果を出さずAIも呼ばない(
    client, user, login, fake_ai, make_consultation
):
    login(user)
    consultation = make_consultation(user)
    db.session.execute(db.delete(PriceRule))
    db.session.commit()

    response = post_answers(client, consultation)

    assert response.status_code == 503
    assert "料金表が入っていない" in response.text
    assert fake_ai.diagnose_calls == []
    assert consultation.status == "asking"


# --- 診断の結果の画面


def test_結果の画面に原因と料金の見積が出る(client, user, make_done_consultation):
    consultation = make_done_consultation(user)

    response = client.get(f"/consultations/{consultation.id}")

    assert response.status_code == 200
    assert "ポットの故障" in response.text
    assert "配線の接触不良" in response.text
    assert "3,000円〜" in response.text
    assert "ポットの不良" in response.text
    # 質問と答えも見られる
    assert "変わりません" in response.text
    # 3つの出口のボタンがある
    for label in ("直す", "手放す", "そのまま使う"):
        assert label in response.text


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("fret", "16,000円〜90,000円"),  # 下限と上限がある
        ("pot", "3,000円〜"),  # 下限だけがある
        ("other", "要見積もり"),  # どちらも無い
    ],
)
def test_料金の表示は3通り(
    client, user, fake_ai, make_done_consultation, code, expected
):
    fake_ai.diagnosis.category_code = code
    consultation = make_done_consultation(user)

    text = client.get(f"/consultations/{consultation.id}").text

    assert f"<strong>{expected}</strong>" in text


def test_料金はAIではなく料金表から引く(client, user, fake_ai, make_done_consultation):
    # AI が説明の中に金額を書いても、料金の見積は料金表の値のまま
    fake_ai.diagnosis = Diagnosis(
        causes=[Cause("ポットの故障", "修理代は999,999円です。")], category_code="pot"
    )
    consultation = make_done_consultation(user)

    text = client.get(f"/consultations/{consultation.id}").text

    assert "<strong>3,000円〜</strong>" in text


def test_AIが作った原因の文は自動エスケープされる(
    client, user, fake_ai, make_done_consultation
):
    fake_ai.diagnosis = Diagnosis(
        causes=[Cause("<b>太字</b>", "<script>alert(1)</script>")], category_code="pot"
    )
    consultation = make_done_consultation(user)

    text = client.get(f"/consultations/{consultation.id}").text

    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;b&gt;太字&lt;/b&gt;" in text


def test_他人の結果は見られない(
    client, user, other_user, login, make_done_consultation
):
    consultation = make_done_consultation(other_user)
    client.post("/logout")
    login(user)

    response = client.get(f"/consultations/{consultation.id}")

    assert response.status_code == 403
    assert "ポットの故障" not in response.text


def test_未ログインで結果を開くとログイン画面へ(client, user, make_done_consultation):
    consultation = make_done_consultation(user)
    client.post("/logout")

    response = client.get(f"/consultations/{consultation.id}")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=")


def test_質問に答える前の問診の結果を開くと質問の画面へ移る(
    client, user, login, make_consultation
):
    login(user)
    consultation = make_consultation(user)

    response = client.get(f"/consultations/{consultation.id}")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}/questions"


def test_結果がある問診の質問の画面を開くと結果へ移る(
    client, user, make_done_consultation
):
    consultation = make_done_consultation(user)

    response = client.get(f"/consultations/{consultation.id}/questions")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}"


# --- 出口を選ぶ


def choose(client, consultation, choice):
    return client.post(
        f"/consultations/{consultation.id}/choice", data={"choice": choice}
    )


def test_出口を選ぶと保存される(client, user, make_done_consultation):
    consultation = make_done_consultation(user)

    response = choose(client, consultation, "repair")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}"
    assert consultation.choice == "repair"
    assert (
        "今の選択：<strong>直す</strong>"
        in client.get(f"/consultations/{consultation.id}").text
    )


def test_出口は選び直せる(client, user, make_done_consultation):
    consultation = make_done_consultation(user)
    choose(client, consultation, "repair")

    choose(client, consultation, "keep")

    assert consultation.choice == "keep"


def test_手放すを選ぶと準備中の枠が出て金額は出ない(
    client, user, make_done_consultation
):
    consultation = make_done_consultation(user)
    before = client.get(f"/consultations/{consultation.id}").text

    choose(client, consultation, "sell")
    after = client.get(f"/consultations/{consultation.id}").text

    assert "買い取りの目安（準備中）" not in before
    assert "買い取りの目安（準備中）" in after
    # 金額は、料金の見積の1か所だけ。買い取りの金額は出ない
    assert after.count("円") == before.count("円")


def test_選択肢に無い出口は保存しない(client, user, make_done_consultation):
    consultation = make_done_consultation(user)

    for value in ("", "delete", "REPAIR"):
        response = choose(client, consultation, value)
        assert response.status_code == 422

    assert consultation.choice is None


def test_他人の問診の出口は選べない(
    client, user, other_user, login, make_done_consultation
):
    consultation = make_done_consultation(other_user)
    client.post("/logout")
    login(user)

    response = choose(client, consultation, "repair")

    assert response.status_code == 403
    assert consultation.choice is None


def test_質問に答える前の問診では出口を選べない(client, user, login, make_consultation):
    login(user)
    consultation = make_consultation(user)

    response = choose(client, consultation, "repair")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/consultations/{consultation.id}/questions"
    assert consultation.choice is None


def test_出口はGETでは選べない(client, user, make_done_consultation):
    consultation = make_done_consultation(user)

    response = client.get(f"/consultations/{consultation.id}/choice?choice=repair")

    assert response.status_code == 405
    assert consultation.choice is None


# --- 問診の一覧


def test_一覧に自分の問診だけが新しい順に出る(
    client, user, other_user, login, make_consultation
):
    make_consultation(other_user, symptom="他人の症状")
    make_consultation(user, symptom="古い症状")
    make_consultation(user, symptom="新しい症状")
    login(user)

    response = client.get("/consultations/")

    assert response.status_code == 200
    assert "他人の症状" not in response.text
    assert response.text.index("新しい症状") < response.text.index("古い症状")


def test_一覧に状態と選んだ出口が出る(
    client, user, make_consultation, make_done_consultation
):
    done = make_done_consultation(user)
    choose(client, done, "keep")
    asking = make_consultation(user)

    text = client.get("/consultations/").text

    assert "結果あり" in text
    assert "そのまま使う" in text
    assert f'href="/consultations/{done.id}"' in text
    assert "質問に答える前" in text
    assert f'href="/consultations/{asking.id}/questions"' in text


def test_問診が無いときの一覧(client, user, login):
    login(user)

    response = client.get("/consultations/")

    assert response.status_code == 200
    assert "問診は、まだありません" in response.text


def test_未ログインで一覧を開くとログイン画面へ(client):
    response = client.get("/consultations/")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login?next=")
