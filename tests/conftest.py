import pytest

from monshin import create_app
from monshin.commands import seed_diagnosis_guides, seed_price_rules
from monshin.extensions import db
from monshin.models import Consultation, ConsultationQuestion, User
from monshin.services import ai
from monshin.services.ai import AIQuestion, Cause, Diagnosis

# 本物の外部サービス（Claude API）は、テストでは呼ばない。
# フェイク（偽物）のクラスを create_app() の設定で差し替える。

FAKE_QUESTIONS = [
    "ノブを回すと、音は少しでも変わりますか？",
    "ノブを回すときに、雑音は出ますか？",
    "ほかのノブやスイッチは、ふつうに動きますか？",
]
# フェイクの AI が、質問と一緒に返す選択肢。3つ目は選択肢なし（自由に書いて答える）
FAKE_CHOICES = [["はい", "いいえ"], ["いつも", "ときどき", "出ない"], []]


class FakeAI:
    """本物の Claude API（services/ai.py）の代わり。同じ名前の関数を持ち、呼ばれた引数を記録する"""

    def __init__(self):
        self.question_calls = []  # generate_questions が呼ばれたときの引数
        self.questions = [
            AIQuestion(text, list(choices))
            for text, choices in zip(FAKE_QUESTIONS, FAKE_CHOICES)
        ]
        self.diagnose_calls = []  # diagnose が呼ばれたときの引数
        self.diagnosis = Diagnosis(
            causes=[
                Cause(
                    "ポットの故障", "ノブの中の部品が、すり減っている可能性があります。"
                ),
                Cause("配線の接触不良", "はんだが外れかけている可能性があります。"),
            ],
            category_code="pot",
        )
        self.error = None  # 例外を入れておくと、それを投げる

    def generate_questions(self, instrument_label, symptom, image=None, guides=None):
        self.question_calls.append(
            {
                "instrument_label": instrument_label,
                "symptom": symptom,
                "image": image,
                "guides": guides,
            }
        )
        if self.error:
            raise self.error
        return list(self.questions)

    def diagnose(
        self, instrument_label, symptom, answers, categories, image=None, guides=None
    ):
        self.diagnose_calls.append(
            {
                "instrument_label": instrument_label,
                "symptom": symptom,
                "answers": answers,
                "categories": categories,
                "image": image,
                "guides": guides,
            }
        )
        if self.error:
            raise self.error
        return self.diagnosis


@pytest.fixture
def fake_ai():
    return FakeAI()


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch):
    """保険: テストの中で本物の Claude API のクライアントを作ろうとしたら、必ず失敗させる"""

    def refuse():
        raise AssertionError("テストで本物の Claude API を呼ぼうとしました")

    monkeypatch.setattr(ai, "_client", refuse)


@pytest.fixture
def app(fake_ai, tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            # テストの写真が instance/uploads に溜まらないように、一時フォルダーに保存する
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "AI_SERVICE": fake_ai,
        }
    )
    with app.app_context():
        db.create_all()
        # 料金表は、本番でも最初に入れておくデータなので、テストでも入れておく
        seed_price_rules()
        seed_diagnosis_guides()
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


@pytest.fixture
def make_consultation(app):
    """質問つきの問診を1つ作る。make_consultation(user, symptom="...") のように使う"""

    def _make(user, **values):
        values = {"instrument": "bass", "symptom": "トーンノブが効かない"} | values
        consultation = Consultation(user_id=user.id, **values)
        for position, question in enumerate(FAKE_QUESTIONS, start=1):
            consultation.questions.append(
                ConsultationQuestion(position=position, question=question)
            )
        db.session.add(consultation)
        db.session.commit()
        return consultation

    return _make


ANSWERS = {"answer_1": "変わりません", "answer_2": "出ます", "answer_3": "動きます"}


@pytest.fixture
def make_done_consultation(client, make_consultation, login):
    """結果ありの問診を1つ作る。本人としてログインし、答えを送って診断まで進める"""

    def _make(user, **values):
        consultation = make_consultation(user, **values)
        login(user)
        response = client.post(
            f"/consultations/{consultation.id}/answers", data=ANSWERS
        )
        assert response.status_code == 302
        return consultation

    return _make
