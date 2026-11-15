from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from monshin.extensions import db

JST = ZoneInfo("Asia/Tokyo")


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
    REPAIR = "repair"  # 直す
    SELL = "sell"  # 手放す
    KEEP = "keep"  # そのまま使う


CHOICE_LABELS = {
    Choice.REPAIR: "直す",
    Choice.SELL: "手放す",
    Choice.KEEP: "そのまま使う",
}


def yen(value: int) -> str:
    """金額を「1,200円」の形にする"""
    return f"{value:,}円"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 小文字にそろえて保存する
    email: Mapped[str] = mapped_column(String(255), unique=True)
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
        """料金の目安の表示。下限と上限、下限だけ、どちらも無い、の3通り"""
        if self.min_price is None:
            return "要見積もり"
        if self.max_price is None:
            return f"{yen(self.min_price)}〜"
        return f"{yen(self.min_price)}〜{yen(self.max_price)}"


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
