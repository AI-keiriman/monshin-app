from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileSize
from wtforms import EmailField, PasswordField, RadioField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Regexp

from monshin.models import INSTRUMENT_LABELS, NAME_MAX_LENGTH, Instrument

# email-validator パッケージを足さずに済むよう、形だけを正規表現で確かめる
EMAIL = Regexp(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$", message="メールアドレスの形式で入力してください"
)

SYMPTOM_MAX_LENGTH = 1000
ANSWER_MAX_LENGTH = 500
# 長すぎるパスワードは、ハッシュの計算でサーバーに負荷をかける。上限を決めておく
PASSWORD_MAX_LENGTH = 128
PASSWORD_TOO_LONG = Length(
    max=PASSWORD_MAX_LENGTH,
    message=f"パスワードは{PASSWORD_MAX_LENGTH}文字以内で入力してください",
)


def strip(value: str | None) -> str | None:
    """前後の空白を取る。貼り付けたメールアドレスに空白が付いていても通す"""
    return value.strip() if value else value


class RegisterForm(FlaskForm):
    name = StringField(
        f"アカウント名（{NAME_MAX_LENGTH}文字まで。画面の上に表示されます）",
        filters=[strip],
        validators=[
            DataRequired(message="アカウント名を入力してください"),
            Length(
                max=NAME_MAX_LENGTH,
                message=f"アカウント名は{NAME_MAX_LENGTH}文字以内で入力してください",
            ),
        ],
    )
    email = EmailField(
        "メールアドレス",
        filters=[strip],
        validators=[
            DataRequired(message="メールアドレスを入力してください"),
            EMAIL,
            Length(max=255, message="メールアドレスは255文字以内で入力してください"),
        ],
    )
    password = PasswordField(
        "パスワード（8文字以上）",
        validators=[
            DataRequired(message="パスワードを入力してください"),
            Length(min=8, message="パスワードは8文字以上で入力してください"),
            PASSWORD_TOO_LONG,
        ],
    )


class LoginForm(FlaskForm):
    email = EmailField(
        "メールアドレス",
        filters=[strip],
        validators=[DataRequired(message="メールアドレスを入力してください"), EMAIL],
    )
    password = PasswordField(
        "パスワード",
        validators=[
            DataRequired(message="パスワードを入力してください"),
            PASSWORD_TOO_LONG,
        ],
    )


class ConsultationForm(FlaskForm):
    """問診の入力。音声の欄は「準備中」の表示だけなので、フォームには入れない"""

    instrument = RadioField(
        "楽器の種類",
        choices=[(i.value, INSTRUMENT_LABELS[i]) for i in Instrument],
        default=Instrument.ELECTRIC.value,
        validators=[DataRequired(message="楽器の種類を選んでください")],
    )
    symptom = TextAreaField(
        "症状",
        filters=[strip],
        validators=[
            DataRequired(message="症状を入力してください"),
            Length(
                max=SYMPTOM_MAX_LENGTH,
                message=f"症状は{SYMPTOM_MAX_LENGTH:,}文字以内で入力してください",
            ),
        ],
    )
    # 拡張子と大きさはここで確かめる。中身が本当に画像かは、ビューで uploads.detect_media_type() が確かめる
    image = FileField(
        "写真（任意。JPEG・PNG・WebP、5MB まで）",
        validators=[
            FileAllowed(
                ["jpg", "jpeg", "png", "webp"],
                message="JPEG・PNG・WebP の画像を選んでください",
            ),
            FileSize(max_size=5 * 1024 * 1024, message="写真は5MB 以下にしてください"),
        ],
    )


def _answer_field() -> TextAreaField:
    return TextAreaField(
        "答え",
        filters=[strip],
        validators=[
            DataRequired(message="答えを入力してください"),
            Length(
                max=ANSWER_MAX_LENGTH,
                message=f"答えは{ANSWER_MAX_LENGTH}文字以内で入力してください",
            ),
        ],
    )


class AnswersForm(FlaskForm):
    """AI の3つの質問への答え。欄の順番は、質問の position（1〜3）と同じ"""

    answer_1 = _answer_field()
    answer_2 = _answer_field()
    answer_3 = _answer_field()

    @property
    def answer_fields(self) -> list[TextAreaField]:
        return [self.answer_1, self.answer_2, self.answer_3]
