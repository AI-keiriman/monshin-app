"""「。」の後に文が続くところで、改行する"""


def test_filter_breaks_between_sentences(app):
    f = app.jinja_env.filters["br_sentences"]
    assert str(f("一つ目。二つ目。")) == "一つ目。<br>二つ目。"


def test_filter_keeps_single_sentence_and_brackets(app):
    f = app.jinja_env.filters["br_sentences"]
    assert str(f("一つだけ。")) == "一つだけ。"
    assert str(f("写真（任意。）です")) == "写真（任意。）です"


def test_filter_escapes_html(app):
    f = app.jinja_env.filters["br_sentences"]
    assert str(f("<b>太字</b>。次")) == "&lt;b&gt;太字&lt;/b&gt;。<br>次"


def test_top_page_breaks_lead(client):
    body = client.get("/").get_data(as_text=True)
    assert "AI が質問をします。<br>答えると" in body
