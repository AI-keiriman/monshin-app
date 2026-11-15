from monshin.extensions import db
from monshin.models import PriceRule


def rules() -> dict[str, PriceRule]:
    return {r.code: r for r in db.session.scalars(db.select(PriceRule))}


def test_seedで料金表が入る(app):
    result = app.test_cli_runner().invoke(args=["seed"])

    assert result.exit_code == 0
    seeded = rules()
    assert set(seeded) == {"pot", "fret", "neck_crack", "other"}
    # 表示の3通り（下限と上限、下限だけ、どちらも無い）が、それぞれある
    assert (seeded["fret"].min_price, seeded["fret"].max_price) == (16000, 90000)
    assert (seeded["pot"].min_price, seeded["pot"].max_price) == (3000, None)
    assert (seeded["other"].min_price, seeded["other"].max_price) == (None, None)


def test_seedは何度実行しても行が増えず値を戻す(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["seed"])
    pot = rules()["pot"]
    pot.min_price = 1
    db.session.commit()

    result = runner.invoke(args=["seed"])

    assert result.exit_code == 0
    assert len(rules()) == 4
    assert rules()["pot"].min_price == 3000
