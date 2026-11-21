"""services/ai.py のテスト。本物の Claude API は呼ばず、クライアントを偽物に差し替える"""

import base64
import json
from types import SimpleNamespace

import anthropic
import pytest

from monshin.services import ai

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
QUESTIONS = ["質問1ですか？", "質問2ですか？", "質問3ですか？"]


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def thinking_block():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def message(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeClient:
    """anthropic.Anthropic の代わり。messages.create の引数を記録し、決めた返事を返す"""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def use_client(app, monkeypatch):
    """ai._client を偽物に差し替える。use_client(response=...) のように使う"""

    def _use(response=None, error=None):
        client = FakeClient(response, error)
        monkeypatch.setattr(ai, "_client", lambda: client)
        return client

    return _use


def questions_message(questions):
    """質問の返事を作る。文字の質問は、選択肢なしの質問にする"""
    items = [
        q if isinstance(q, dict) else {"question": q, "choices": []} for q in questions
    ]
    return message([text_block(json.dumps({"questions": items}))])


def texts(questions):
    return [q.text for q in questions]


def test_質問を3つ返す(use_client):
    client = use_client(questions_message(QUESTIONS))

    result = ai.generate_questions("ベース", "トーンノブが効かない")

    assert texts(result) == QUESTIONS
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == 2048
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["type"] == "json_schema"
    # 症状は、system ではなく user の文として渡す
    content = call["messages"][0]["content"]
    assert call["messages"][0]["role"] == "user"
    assert content == [
        {"type": "text", "text": "楽器の種類：ベース\n症状：\nトーンノブが効かない"}
    ]
    assert "トーンノブ" not in call["system"]


def test_モデルは設定で変えられる(app, use_client):
    app.config["ANTHROPIC_MODEL"] = "claude-sonnet-5-5"
    client = use_client(questions_message(QUESTIONS))

    ai.generate_questions("ベース", "音が出ない")

    assert client.calls[0]["model"] == "claude-sonnet-5-5"


def test_写真があれば画像のブロックを先に渡す(use_client):
    client = use_client(questions_message(QUESTIONS))

    ai.generate_questions("ベース", "音が出ない", (PNG, "image/png"))

    content = client.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "text"]
    assert content[0]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.standard_b64encode(PNG).decode("ascii"),
    }


def test_thinkingのブロックが先頭にあっても文を読める(use_client):
    block = questions_message(QUESTIONS).content[0]
    use_client(message([thinking_block(), block]))

    assert texts(ai.generate_questions("ベース", "音が出ない")) == QUESTIONS


def test_質問が多いときは先頭の3つだけ使う(use_client):
    use_client(questions_message(QUESTIONS + ["質問4ですか？"]))

    assert texts(ai.generate_questions("ベース", "音が出ない")) == QUESTIONS


@pytest.mark.parametrize(
    "response",
    [
        questions_message(QUESTIONS[:2]),  # 質問が足りない
        questions_message(["質問1", "", "   "]),  # 空の質問は数えない
        questions_message(["あ" * 256, "質問2", "質問3"]),  # 長すぎる
        message([text_block(json.dumps({"other": []}))]),  # 形が違う
        message([text_block(json.dumps(["質問1", "質問2", "質問3"]))]),  # dict でない
        message([text_block("JSON ではない文")]),
        message([thinking_block()], stop_reason="max_tokens"),  # 途中で切れた
        message([], stop_reason="refusal"),  # 断られた
        message([thinking_block()]),  # 文が無い
    ],
)
def test_返事の形が違うときはAIErrorにする(use_client, response):
    use_client(response)

    with pytest.raises(ai.AIError):
        ai.generate_questions("ベース", "音が出ない")


def test_APIの失敗はAIErrorにする(use_client):
    use_client(error=anthropic.AnthropicError("API キーが無い"))

    with pytest.raises(ai.AIError):
        ai.generate_questions("ベース", "音が出ない")


# --- API キーが無いとき

# autouse の no_real_ai が差し替える前の、本物の _client
REAL_CLIENT = ai._client


@pytest.mark.parametrize("value", [None, ""])
def test_APIキーが無いときはAIErrorにする(app, monkeypatch, value):
    monkeypatch.setattr(ai, "_client", REAL_CLIENT)
    if value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)

    # キーが無ければ、クライアントを作る前に止まる（外へは接続しない）
    with pytest.raises(ai.AIError):
        ai.generate_questions("エレキベース", "音が出ない")


def test_質問の指示の文に写しやすい例を置かない():
    # 例の文があると、AI がそのまま写す。形だけを示す
    assert "いつごろから出ていますか" not in ai.QUESTIONS_SYSTEM
    assert "そのまま写さない" in ai.QUESTIONS_SYSTEM


# --- 原因を予想してから、質問を作る


def test_質問の前に原因の予想を書かせる():
    schema = ai.QUESTIONS_SCHEMA
    # 予想（candidates）を、質問（questions）より先に書かせる
    assert list(schema["properties"]) == ["candidates", "questions"]
    assert schema["required"] == ["candidates", "questions"]
    assert "可能性が高い順に" in ai.QUESTIONS_SYSTEM
    assert "原因を1つに絞れる" in ai.QUESTIONS_SYSTEM


def test_原因の予想は画面に出す質問に混ざらない(use_client):
    message = questions_message(QUESTIONS)
    # 本物の返事には、予想も入る。使うのは質問だけ
    block = next(b for b in message.content if b.type == "text")
    data = json.loads(block.text)
    data["candidates"] = [{"cause": "ポットの故障", "how_to_tell": "回すと雑音が出る"}]
    block.text = json.dumps(data, ensure_ascii=False)
    use_client(message)

    assert texts(ai.generate_questions("エレキギター", "音が変わらない")) == QUESTIONS


# --- 答えの選択肢


def test_質問と一緒に答えの選択肢を返す(use_client):
    use_client(
        questions_message(
            [
                {"question": "質問1ですか？", "choices": [" はい ", "いいえ"]},
                {
                    "question": "質問2ですか？",
                    "choices": ["いつも", "ときどき", "弾くときだけ"],
                },
                {"question": "質問3は？", "choices": []},
            ]
        )
    )

    result = ai.generate_questions("ベース", "音が出ない")

    assert [q.choices for q in result] == [
        ["はい", "いいえ"],
        ["いつも", "ときどき", "弾くときだけ"],
        [],
    ]


@pytest.mark.parametrize(
    "choices",
    [
        ["はい"],  # 1つだけでは選べない
        ["A", "B", "C", "D", "E"],  # 多すぎる
        ["はい", "あ" * 31],  # 長すぎる
        ["はい", "い\nいえ"],  # 改行は、保存の区切りと重なる
        "はい",  # リストでない
    ],
)
def test_選択肢の形がおかしいときは選択肢だけ捨てて質問は使う(use_client, choices):
    questions = [
        {"question": "質問1ですか？", "choices": choices},
        {"question": "質問2ですか？", "choices": ["はい", "いいえ"]},
        {"question": "質問3ですか？", "choices": ["はい", "いいえ"]},
    ]
    use_client(questions_message(questions))

    result = ai.generate_questions("ベース", "音が出ない")

    assert texts(result) == QUESTIONS
    assert result[0].choices == []
    assert result[1].choices == ["はい", "いいえ"]


def test_返事の形で選択肢を必ず書かせる():
    item = ai.QUESTIONS_SCHEMA["properties"]["questions"]["items"]
    assert item["required"] == ["question", "choices"]
    assert "choices" in ai.QUESTIONS_SYSTEM
