import click

from monshin.extensions import db
from monshin.models import PriceRule

# 料金表の初期データ：(code, label, symptom_example, min_price, max_price)
# 金額は円の整数。無いときは None。中身は docs/design/database.md の表と合わせる
PRICE_RULES = [
    ("pot", "ポットの不良", "ノブが効かない。回すと雑音が出る", 3000, None),
    ("fret", "フレットの消耗", "音が詰まる。フレットがへこんでいる", 16000, 90000),
    ("neck_crack", "ネックの折れ、ひび", "ヘッドやネックが割れた", 65000, None),
    ("other", "その他、判断できない", "上のどれにも当たらない", None, None),
]


def seed_price_rules() -> None:
    """料金表を入れる。同じ code があれば、作り直さずに値を更新する"""
    for code, label, symptom_example, min_price, max_price in PRICE_RULES:
        rule = db.session.scalar(db.select(PriceRule).filter_by(code=code))
        if rule is None:
            rule = PriceRule(code=code)
            db.session.add(rule)
        rule.label = label
        rule.symptom_example = symptom_example
        rule.min_price = min_price
        rule.max_price = max_price
    db.session.commit()


def init_app(app):
    @app.cli.command("seed")
    def seed():
        """料金表の初期データを入れる。何度実行してもよい（既存の行は更新する）"""
        seed_price_rules()
        click.echo(f"料金表を{len(PRICE_RULES)}件、入れました")
