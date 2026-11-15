"""services/ai.py の diagnose のテスト。本物の Claude API は呼ばず、クライアントを偽物に差し替える"""

import json
from types import SimpleNamespace

import pytest

from monshin.services import ai

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ANSWERS = [("音は変わりますか？", "変わりません"), ("雑音は出ますか？", "出ます")]
CATEGORIES = [
    ("pot", "ポットの不良", "ノブが効かない"),
    ("fret", "フレットの消耗", "音が詰まる"),
    ("other", "その他、判断できない", "上のどれにも当たらない"),
]
CAUSES = [
    {"name": "ポットの故障", "description": "部品がすり減っている可能性があります。"},
    {
        "name": "配線の接触不良",
        "description": "はんだが外れかけている可能性があります。",
    },
]


def message(data, stop_reason="end_turn"):
    block = SimpleNamespace(type="text", text=json.dumps(data))
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.fixture
def use_client(app, monkeypatch):
    def _use(data):
        client = FakeClient(message(data))
        monkeypatch.setattr(ai, "_client", lambda: client)
        return client

    return _use


def diagnose(image=None):
    return ai.diagnose("ベース", "トーンノブが効かない", ANSWERS, CATEGORIES, image)


def test_原因の候補と分類を返す(use_client):
    client = use_client({"causes": CAUSES, "category_code": "pot"})

    result = diagnose()

    assert result.category_code == "pot"
    assert [(c.name, c.description) for c in result.causes] == [
        (c["name"], c["description"]) for c in CAUSES
    ]
    call = client.calls[0]
    assert call["max_tokens"] == 2048
    assert call["output_config"]["effort"] == "low"
    # 料金表にある code だけを選ばせる
    schema = call["output_config"]["format"]["schema"]
    assert schema["properties"]["category_code"]["enum"] == ["pot", "fret", "other"]
    # 症状、質問と答え、料金表の分類は、user の文として渡す
    text = call["messages"][0]["content"][0]["text"]
    for expected in ("ベース", "トーンノブが効かない", "変わりません", "ポットの不良"):
        assert expected in text
    assert "トーンノブ" not in call["system"]


def test_料金表の金額はAIに渡さない(use_client):
    client = use_client({"causes": CAUSES, "category_code": "pot"})

    diagnose()

    text = client.calls[0]["messages"][0]["content"][0]["text"]
    assert "円" not in text


def test_写真があれば画像のブロックを先に渡す(use_client):
    client = use_client({"causes": CAUSES, "category_code": "pot"})

    diagnose((PNG, "image/png"))

    content = client.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "text"]


def test_料金表に無い分類はその他にする(use_client):
    use_client({"causes": CAUSES, "category_code": "no_such_code"})

    assert diagnose().category_code == "other"


def test_原因が多いときは先頭の3つだけ使う(use_client):
    many = [{"name": f"原因{i}", "description": "説明"} for i in range(1, 6)]
    use_client({"causes": many, "category_code": "pot"})

    assert [c.name for c in diagnose().causes] == ["原因1", "原因2", "原因3"]


@pytest.mark.parametrize(
    "data",
    [
        {"causes": [], "category_code": "pot"},  # 原因が無い
        {"causes": [{"name": "", "description": "説明"}], "category_code": "pot"},
        {"causes": [{"name": "原因", "description": "  "}], "category_code": "pot"},
        {
            "causes": [{"name": "あ" * 101, "description": "説明"}],
            "category_code": "pot",
        },
        {
            "causes": [{"name": "原因", "description": "あ" * 501}],
            "category_code": "pot",
        },
        {"causes": "ポットの故障", "category_code": "pot"},  # 一覧でない
        {"category_code": "pot"},  # causes が無い
    ],
)
def test_返事の形が違うときはAIErrorにする(use_client, data):
    use_client(data)

    with pytest.raises(ai.AIError):
        diagnose()
