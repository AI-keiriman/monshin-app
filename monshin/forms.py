from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField
from wtforms.validators import DataRequired, Length, Regexp

# email-validator パッケージを足さずに済むよう、形だけを正規表現で確かめる
EMAIL = Regexp(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$", message="メールアドレスの形式で入力してください"
)


def strip(value: str | None) -> str | None:
    """前後の空白を取る。貼り付けたメールアドレスに空白が付いていても通す"""
    return value.strip() if value else value


class RegisterForm(FlaskForm):
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
        validators=[DataRequired(message="パスワードを入力してください")],
    )
