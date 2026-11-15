import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from monshin.extensions import db
from monshin.forms import AnswersForm, ConsultationForm
from monshin.models import (
    CHOICE_LABELS,
    INSTRUMENT_LABELS,
    Choice,
    Consultation,
    ConsultationCause,
    ConsultationQuestion,
    ConsultationStatus,
    Instrument,
    PriceRule,
    now_jst,
)
from monshin.services.ai import AIError
from monshin.uploads import detect_media_type, save_image, upload_folder

bp = Blueprint("consultations", __name__, url_prefix="/consultations")
logger = logging.getLogger(__name__)

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


def load_image(consultation: Consultation) -> tuple[bytes, str] | None:
    """保存してある写真を読み、(バイト列, 種類) を返す。写真が無ければ None"""
    if not consultation.image_filename:
        return None
    path = upload_folder() / consultation.image_filename
    if not path.is_file():
        return None
    data = path.read_bytes()
    media_type = detect_media_type(data)
    if media_type is None:
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


def render_questions(consultation: Consultation, form: AnswersForm, status: int = 200):
    return (
        render_template(
            "consultations/questions.html", consultation=consultation, form=form
        ),
        status,
    )


@bp.route("/")
@login_required
def index():
    """自分の問診の一覧。新しい順"""
    consultations = db.session.scalars(
        db.select(Consultation)
        .filter_by(user_id=current_user.id)
        .order_by(Consultation.created_at.desc(), Consultation.id.desc())
    ).all()
    return render_template("consultations/index.html", consultations=consultations)


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
    # 結果がある問診は、結果の画面へ移す
    if consultation.status == ConsultationStatus.DONE:
        return redirect(url_for("consultations.show", consultation_id=consultation.id))
    form = AnswersForm()
    # 保存済みの答えがあれば、欄に入れておく
    for field, question in zip(form.answer_fields, consultation.questions):
        field.data = question.answer
    return render_questions(consultation, form)


@bp.route("/<int:consultation_id>/answers", methods=["POST"])
@login_required
def answers(consultation_id: int):
    consultation = get_own_consultation_or_403(consultation_id)
    # 結果がある問診は、診断をやり直さない（AI を二重に呼ばない）
    if consultation.status == ConsultationStatus.DONE:
        return redirect(url_for("consultations.show", consultation_id=consultation.id))

    # 1. 3つの答えを確かめて、保存する
    form = AnswersForm()
    if not form.validate_on_submit():
        return render_questions(consultation, form, 422)
    for field, question in zip(form.answer_fields, consultation.questions):
        question.answer = field.data
    db.session.commit()

    # 2. AI を呼ぶ。料金表の分類の一覧も渡す
    rules = db.session.scalars(db.select(PriceRule).order_by(PriceRule.id)).all()
    if not rules:
        logger.error("料金表が空である。uv run flask seed を実行する")
        flash("料金表が入っていないため、結果を出せません。")
        return render_questions(consultation, form, 503)
    ai = current_app.extensions["ai"]
    try:
        # 3. AI は、原因の候補（最大3つ）と、料金表の分類を1つ返す
        diagnosis = ai.diagnose(
            consultation.instrument_label,
            consultation.symptom,
            [(q.question, q.answer) for q in consultation.questions],
            [(r.code, r.label, r.symptom_example) for r in rules],
            load_image(consultation),
        )
    except AIError:
        # 6. 失敗しても、答えは保存したまま。もう一度送ると、やり直せる
        flash(AI_UNAVAILABLE + "答えは保存しました。")
        return render_questions(consultation, form, 503)

    # 4. AI が返した分類が料金表に無いときは、「その他」にする
    rules_by_code = {r.code: r for r in rules}
    rule = rules_by_code.get(diagnosis.category_code) or rules_by_code.get("other")

    # 5. 原因の候補と分類を保存し、状態を「結果あり」にする
    for position, cause in enumerate(diagnosis.causes, start=1):
        consultation.causes.append(
            ConsultationCause(
                position=position, name=cause.name, description=cause.description
            )
        )
    consultation.price_rule = rule
    consultation.status = ConsultationStatus.DONE
    consultation.completed_at = now_jst()
    db.session.commit()
    return redirect(url_for("consultations.show", consultation_id=consultation.id))


@bp.route("/<int:consultation_id>")
@login_required
def show(consultation_id: int):
    """診断の結果"""
    consultation = get_own_consultation_or_403(consultation_id)
    # 質問に答える前の問診は、質問の画面へ移す
    if consultation.status != ConsultationStatus.DONE:
        return redirect(
            url_for("consultations.questions", consultation_id=consultation.id)
        )
    return render_template(
        "consultations/show.html",
        consultation=consultation,
        choices=[(c.value, CHOICE_LABELS[c]) for c in Choice],
    )


@bp.route("/<int:consultation_id>/choice", methods=["POST"])
@login_required
def choose(consultation_id: int):
    """出口（直す／手放す／そのまま使う）を保存する。選び直せる"""
    consultation = get_own_consultation_or_403(consultation_id)
    if consultation.status != ConsultationStatus.DONE:
        return redirect(
            url_for("consultations.questions", consultation_id=consultation.id)
        )
    try:
        choice = Choice(request.form.get("choice", ""))
    except ValueError:
        abort(422)
    consultation.choice = choice
    db.session.commit()
    return redirect(url_for("consultations.show", consultation_id=consultation.id))


@bp.route("/<int:consultation_id>/photo")
@login_required
def photo(consultation_id: int):
    """問診の写真を返す。写真は公開のフォルダーに置かず、ここからだけ返す"""
    consultation = get_own_consultation_or_403(consultation_id)
    if not consultation.image_filename:
        abort(404)
    # ファイル名は DB の値だけを使う。URL やフォームからは受け取らない
    return send_from_directory(upload_folder(), consultation.image_filename)
