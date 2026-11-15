import pytest

from monshin import create_app
from monshin.extensions import db
from monshin.models import Consultation, ConsultationQuestion, User
from monshin.services import ai

# 本物の外部サービス（Claude API）は、テストでは呼ばない。
# フェイク（偽物）のクラスを create_app() の設定で差し替える。

FAKE_QUESTIONS = [
    "ノブを回すと、音は少しでも変わりますか？",
    "ノブを回すときに、雑音は出ますか？",
    "ほかのノブやスイッチは、ふつうに動きますか？",
]


class FakeAI:
    """本物の Claude API（services/ai.py）の代わり。同じ名前の関数を持ち、呼ばれた引数を記録する"""

    def __init__(self):
        self.question_calls = []  # generate_questions が呼ばれたときの引数
        self.questions = list(FAKE_QUESTIONS)
        self.error = None  # 例外を入れておくと、それを投げる

    def generate_questions(self, instrument_label, symptom, image=None):
        self.question_calls.append(
            {"instrument_label": instrument_label, "symptom": symptom, "image": image}
        )
        if self.error:
            raise self.error
        return list(self.questions)


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
