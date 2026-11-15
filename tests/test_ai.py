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
    return message([text_block(json.dumps({"questions": questions}))])


def test_質問を3つ返す(use_client):
    client = use_client(questions_message(QUESTIONS))

    result = ai.generate_questions("ベース", "トーンノブが効かない")

    assert result == QUESTIONS
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == 1024
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
    use_client(
        message([thinking_block(), text_block(json.dumps({"questions": QUESTIONS}))])
    )

    assert ai.generate_questions("ベース", "音が出ない") == QUESTIONS


def test_質問が多いときは先頭の3つだけ使う(use_client):
    use_client(questions_message(QUESTIONS + ["質問4ですか？"]))

    assert ai.generate_questions("ベース", "音が出ない") == QUESTIONS


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
