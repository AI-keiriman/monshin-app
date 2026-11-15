from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from monshin.extensions import db
from monshin.forms import AnswersForm, ConsultationForm
from monshin.models import (
    INSTRUMENT_LABELS,
    Consultation,
    ConsultationQuestion,
    Instrument,
    now_jst,
)
from monshin.services.ai import AIError
from monshin.uploads import detect_media_type, save_image, upload_folder

bp = Blueprint("consultations", __name__, url_prefix="/consultations")

AI_UNAVAILABLE = "今は AI を使えません。時間をおいて、もう一度お試しください。"


def get_own_consultation_or_403(consultation_id: int) -> Consultation:
    """問診を取得する。無ければ 404、ログイン中の本人の問診でなければ 403"""
    consultation = db.get_or_404(Consultation, consultation_id)
    if consultation.user_id != current_user.id:
        abort(403)
    return consultation


def consultations_today() -> int:
    """ログイン中の本人が、今日（日本時間の 0:00 以降）に始めた問診の数"""
    start = now_jst().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.session.scalar(
        db.select(db.func.count())
        .select_from(Consultation)
        .where(
            Consultation.user_id == current_user.id,
            Consultation.created_at >= start,
        )
    )


def limit_reached() -> bool:
    return consultations_today() >= current_app.config["DAILY_CONSULTATION_LIMIT"]


def read_image(form: ConsultationForm) -> tuple[bytes, str] | None:
    """フォームの写真を読み、(バイト列, 種類) を返す。写真が無ければ None。

    中身が画像でなければ、form.image.errors にメッセージを足して None を返す。
    """
    file = form.image.data
    if not file:
        return None
    data = file.read()
    media_type = detect_media_type(data)
    if media_type is None:
        form.image.errors.append("JPEG・PNG・WebP の画像を選んでください")
        return None
    return data, media_type


def render_new(form: ConsultationForm, status: int = 200):
    return (
        render_template(
            "consultations/new.html",
            form=form,
            limit=current_app.config["DAILY_CONSULTATION_LIMIT"],
            limit_reached=limit_reached(),
        ),
        status,
    )


@bp.route("/new")
@login_required
def new():
    return render_new(ConsultationForm())


@bp.route("/", methods=["POST"])
@login_required
def create():
    form = ConsultationForm()
    # 1. 入力を確かめる
    if not form.validate_on_submit():
        return render_new(form, 422)
    image = read_image(form)
    if form.image.errors:
        return render_new(form, 422)

    # 2. 今日の回数を確かめる。上限に達していたら、AI を呼ばない
    if limit_reached():
        flash("今日の問診の回数が、上限に達しました。明日、もう一度お試しください。")
        return render_new(form, 429)

    # 3. AI に質問を作らせる
    instrument = Instrument(form.instrument.data)
    ai = current_app.extensions["ai"]
    try:
        questions = ai.generate_questions(
            INSTRUMENT_LABELS[instrument], form.symptom.data, image
        )
    except AIError:
        # 5. 失敗したら、何も保存しない。入力した文は、フォームに残る
        flash(AI_UNAVAILABLE + "写真を付けていた場合は、選び直してください。")
        return render_new(form, 503)

    # 4. 成功したら、写真、問診、質問を保存する
    consultation = Consultation(
        user_id=current_user.id,
        instrument=instrument,
        symptom=form.symptom.data,
    )
    if image:
        consultation.image_filename = save_image(*image)
    for position, question in enumerate(questions, start=1):
        consultation.questions.append(
            ConsultationQuestion(position=position, question=question)
        )
    db.session.add(consultation)
    db.session.commit()
    return redirect(url_for("consultations.questions", consultation_id=consultation.id))


@bp.route("/<int:consultation_id>/questions")
@login_required
def questions(consultation_id: int):
    consultation = get_own_consultation_or_403(consultation_id)
    form = AnswersForm()
    # 保存済みの答えがあれば、欄に入れておく
    for field, question in zip(form.answer_fields, consultation.questions):
        field.data = question.answer
    return render_template(
        "consultations/questions.html", consultation=consultation, form=form
    )


@bp.route("/<int:consultation_id>/answers", methods=["POST"])
@login_required
def answers(consultation_id: int):
    consultation = get_own_consultation_or_403(consultation_id)
    form = AnswersForm()
    if not form.validate_on_submit():
        return (
            render_template(
                "consultations/questions.html", consultation=consultation, form=form
            ),
            422,
        )
    for field, question in zip(form.answer_fields, consultation.questions):
        question.answer = field.data
    db.session.commit()
    # 診断の結果（AI の2回目の呼び出し）は、次の機能で作る
    flash("答えを保存しました。診断の結果の画面は、これから作ります。")
    return redirect(url_for("consultations.questions", consultation_id=consultation.id))


@bp.route("/<int:consultation_id>/photo")
@login_required
def photo(consultation_id: int):
    """問診の写真を返す。写真は公開のフォルダーに置かず、ここからだけ返す"""
    consultation = get_own_consultation_or_403(consultation_id)
    if not consultation.image_filename:
        abort(404)
    # ファイル名は DB の値だけを使う。URL やフォームからは受け取らない
    return send_from_directory(upload_folder(), consultation.image_filename)
