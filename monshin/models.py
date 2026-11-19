from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from monshin.extensions import db

JST = ZoneInfo("Asia/Tokyo")
# アカウント名の長さの上限
NAME_MAX_LENGTH = 30


def now_jst() -> datetime:
    """日本時間の現在時刻。SQLite はタイムゾーンを保存しないので tzinfo を外して使う"""
    return datetime.now(JST).replace(tzinfo=None)


class Instrument(StrEnum):
    ACOUSTIC = "acoustic"
    ELECTRIC = "electric"
    BASS = "bass"


INSTRUMENT_LABELS = {
    Instrument.ACOUSTIC: "アコースティックギター",
    Instrument.ELECTRIC: "エレキギター",
    Instrument.BASS: "ベース",
}


class ConsultationStatus(StrEnum):
    ASKING = "asking"  # 質問に答える前
    DONE = "done"  # 結果あり


STATUS_LABELS = {
    ConsultationStatus.ASKING: "質問に答える前",
    ConsultationStatus.DONE: "結果あり",
}


class Choice(StrEnum):
    REPAIR = "repair"  # 修理を依頼する
    SELL = "sell"  # 買取査定をする
    KEEP = "keep"  # そのまま使う（何もせずにホームに戻る）


# 選んだ出口の名前。「今の選択」と、問診の一覧に出す
CHOICE_LABELS = {
    Choice.REPAIR: "修理を依頼",
    Choice.SELL: "買取査定",
    Choice.KEEP: "そのまま使う",
}

# 結果の画面のボタン。並べる順に書く。名前を見れば、押した後に何が起きるかが分かるようにする
CHOICE_BUTTONS = [
    (Choice.REPAIR, "修理依頼に進む"),
    (Choice.KEEP, "ホームに戻る"),
    (Choice.SELL, "買取査定をする"),
]


def yen(value: int) -> str:
    """金額を「1,200円」の形にする"""
    return f"{value:,}円"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 小文字にそろえて保存する
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # 画面の上の帯に出す名前。メールアドレスを画面に出さないために使う。
    # この欄ができる前に登録した人は、空（None）のまま
    name: Mapped[str | None] = mapped_column(String(NAME_MAX_LENGTH))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=now_jst)

    consultations: Mapped[list[Consultation]] = relationship(back_populates="user")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class PriceRule(db.Model):
    """料金表。AI は code を1つ選ぶだけで、金額はここから引く"""

    __tablename__ = "price_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    label: Mapped[str] = mapped_column(String(50))
    # 症状の例。AI に分類を選ばせるときに渡す
    symptom_example: Mapped[str] = mapped_column(String(255))
    # 円の整数。無いときは NULL
    min_price: Mapped[int | None]
    max_price: Mapped[int | None]

    @property
    def price_text(self) -> str:
        """料金の見積の表示。下限と上限、下限だけ、どちらも無い、の3通り"""
        if self.min_price is None:
            return "要見積"
        if self.max_price is None:
            return f"{yen(self.min_price)}〜"
        return f"{yen(self.min_price)}〜{yen(self.max_price)}"


# メーカーと機種名の長さの上限、使用年数の上限
INSTRUMENT_INFO_MAX_LENGTH = 50
YEARS_USED_MAX = 100


def instrument_info_text(
    maker: str | None, model_name: str | None, years_used: int | None
) -> str:
    """楽器の情報を「メーカー：○○　機種名：○○　使用年数：○年」の形にする。無い項目は書かない"""
    parts = []
    if maker:
        parts.append(f"メーカー：{maker}")
    if model_name:
        parts.append(f"機種名：{model_name}")
    if years_used is not None:
        parts.append(f"使用年数：{years_used}年")
    return "　".join(parts)


def symptom_with_info(symptom: str, info: str) -> str:
    """AI に渡す症状の文。楽器の情報があれば、症状の後ろに添える"""
    return f"{symptom}\n\n楽器の情報：{info}" if info else symptom


class Consultation(db.Model):
    """問診。持ち主が症状を伝えてから、結果が出るまでの1回分"""

    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 問診した本人。他人の問診は見せない
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    instrument: Mapped[str] = mapped_column(String(20))
    symptom: Mapped[str] = mapped_column(Text)
    # サーバーが付け直したファイル名（UUID + 拡張子）。写真なしは NULL
    image_filename: Mapped[str | None] = mapped_column(String(255))
    # 楽器の情報。どれも任意。AI に、症状と一緒に渡す
    maker: Mapped[str | None] = mapped_column(String(INSTRUMENT_INFO_MAX_LENGTH))
    model_name: Mapped[str | None] = mapped_column(String(INSTRUMENT_INFO_MAX_LENGTH))
    years_used: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(20), default=ConsultationStatus.ASKING)
    # AI が選んだ料金表の分類。結果ができたときに入る
    price_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_rules.id", ondelete="RESTRICT")
    )
    choice: Mapped[str | None] = mapped_column(String(20))
    # 今日の回数を数えるのに使う
    created_at: Mapped[datetime] = mapped_column(default=now_jst, index=True)
    completed_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(back_populates="consultations")
    price_rule: Mapped[PriceRule | None] = relationship()
    questions: Mapped[list[ConsultationQuestion]] = relationship(
        back_populates="consultation", order_by="ConsultationQuestion.position"
    )
    causes: Mapped[list[ConsultationCause]] = relationship(
        back_populates="consultation", order_by="ConsultationCause.position"
    )

    @property
    def instrument_label(self) -> str:
        return INSTRUMENT_LABELS[Instrument(self.instrument)]

    @property
    def instrument_info(self) -> str:
        """画面に出す、楽器の情報の1行。何も無ければ空の文字列"""
        return instrument_info_text(self.maker, self.model_name, self.years_used)

    @property
    def symptom_for_ai(self) -> str:
        return symptom_with_info(self.symptom, self.instrument_info)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[ConsultationStatus(self.status)]

    @property
    def choice_label(self) -> str | None:
        """選んだ出口の名前。まだ選んでいなければ None"""
        if self.choice is None:
            return None
        return CHOICE_LABELS[Choice(self.choice)]


class ConsultationQuestion(db.Model):
    """AI の質問と、本人の答え"""

    __tablename__ = "consultation_questions"
    __table_args__ = (
        UniqueConstraint(
            "consultation_id", "position", name="uq_consultation_questions_position"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int]  # 1〜3。画面に出す順番
    question: Mapped[str] = mapped_column(String(255))
    answer: Mapped[str | None] = mapped_column(Text)

    consultation: Mapped[Consultation] = relationship(back_populates="questions")


class ConsultationCause(db.Model):
    """AI が挙げた原因の候補"""

    __tablename__ = "consultation_causes"
    __table_args__ = (
        UniqueConstraint(
            "consultation_id", "position", name="uq_consultation_causes_position"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(
        ForeignKey("consultations.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int]  # 1〜3。可能性が高い順
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)

    consultation: Mapped[Consultation] = relationship(back_populates="causes")
