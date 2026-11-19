"""診断の手引き：症状ごとの確かめる点と見分け方を、AI に渡す"""

import re

from monshin.commands import DIAGNOSIS_GUIDES, PRICE_RULES
from monshin.extensions import db
from monshin.models import DiagnosisGuide
from monshin.services import ai
from monshin.services.ai import GuideEntry


def guides_in_db():
    return db.session.scalars(db.select(DiagnosisGuide)).all()


def test_seedで手引きが入る(app):
    result = app.test_cli_runner().invoke(args=["seed"])
    assert result.exit_code == 0
    assert f"診断の手引きを{len(DIAGNOSIS_GUIDES)}件" in result.output
    assert {g.code for g in guides_in_db()} == {row[0] for row in DIAGNOSIS_GUIDES}


def test_seedは何度実行しても手引きの行が増えない(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["seed"])
    runner.invoke(args=["seed"])
    assert len(guides_in_db()) == len(DIAGNOSIS_GUIDES)


def test_手引きの分類は料金表にある():
    codes = {row[0] for row in PRICE_RULES}
    assert all(row[5] in codes for row in DIAGNOSIS_GUIDES)


def test_見分け方に書いた分類は料金表にある():
    codes = {row[0] for row in PRICE_RULES}
    for row in DIAGNOSIS_GUIDES:
        for code in re.findall(r"分類は ([a-z_]+)", row[4]):
            assert code in codes, f"{row[0]}：{code}"


def test_料金表は下限が上限以下():
    for code, _, _, low, high in PRICE_RULES:
        if low is not None and high is not None:
            assert low <= high, code


def test_手引きが無ければAIに渡す文は空():
    assert ai._guide_text(None) == ""
    assert ai._guide_text([]) == ""


def test_手引きの文には5つの項目が入る():
    text = ai._guide_text(
        [GuideEntry("症状A", "原因A", "確かめる点A", "見分け方A", "pot")]
    )
    for part in ("診断の手引き", "症状A", "原因A", "確かめる点A", "見分け方A", "pot"):
        assert part in text


def test_指示の文は手引きの使い方を書いている():
    assert "診断の手引き" in ai.QUESTIONS_SYSTEM
    assert "診断の手引き" in ai.DIAGNOSIS_SYSTEM
    # 近い行が無いときは、手引きに縛られない
    assert "近い行が無ければ" in ai.QUESTIONS_SYSTEM
    assert "手引きにこだわらない" in ai.DIAGNOSIS_SYSTEM


def test_質問を作るときに手引きをAIに渡す(client, user, login, fake_ai):
    login(user)
    client.post(
        "/consultations/",
        data={
            "instrument": "electric",
            "symptom": "トーンのノブを回しても、音が変わらない",
        },
    )
    guides = fake_ai.question_calls[0]["guides"]
    assert len(guides) == len(DIAGNOSIS_GUIDES)
    assert guides[0].category_code == "pot"
